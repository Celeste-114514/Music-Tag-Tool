"""GUI main window (PySide6).

Reuses the proven business core from the old project (model.AudioTags,
scanner, writer, providers) but with a Qt model/view GUI — this is the
layer that replaces the failing Tk Listbox rendering.
"""
import os
import csv

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from model import FIELDS, FIELD_DESC, AudioTags
import scanner
import writer
from app.table_model import TagTableModel, KEYS
from app.workers import ScanWorker, QueryWorker, WriteWorker

APPLE_STOREFRONTS = [("CN", "CN"), ("US", "US"), ("JP", "JP")]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎵 音乐标签批量修改工具")
        self.resize(1200, 740)
        self.setMinimumSize(980, 600)

        self.cache_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        self.rows = []  # list[dict]: path, rel, tags(AudioTags), platform, plan
        self._scan_worker = None
        self._query_worker = None
        self._write_worker = None
        self._scan_paused = False
        self._query_paused = False
        self._scan_index = 0        # breakpoint: how many rows already scanned
        self._query_index = 0       # breakpoint: how many rows already queried

        self._build_ui()
        self._log("欢迎使用！选择文件夹 → 扫描 → 查询标签 → 核对两表后写入。")

    # ---------------- UI ----------------
    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # ---- top control card ----
        top = QVBoxLayout()

        row1 = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("目标文件夹…")
        btn_pick = QPushButton("选择文件夹…")
        btn_pick.clicked.connect(self._choose_folder)
        self.btn_scan = QPushButton("扫描文件夹")
        self.btn_scan.clicked.connect(self._scan)
        row1.addWidget(btn_pick)
        row1.addWidget(self.folder_edit, 1)
        row1.addWidget(self.btn_scan)
        # scan control: pause / continue / stop (enabled while scanning)
        self.btn_scan_pause = QPushButton("⏸ 暂停扫描")
        self.btn_scan_pause.clicked.connect(self._scan_pause)
        self.btn_scan_resume = QPushButton("▶ 继续扫描")
        self.btn_scan_resume.clicked.connect(self._scan_resume)
        self.btn_scan_stop = QPushButton("■ 停止扫描")
        self.btn_scan_stop.clicked.connect(self._scan_stop)
        for b in (self.btn_scan_pause, self.btn_scan_resume, self.btn_scan_stop):
            b.setEnabled(False)
            row1.addWidget(b)
        self.apple_cb = QCheckBox("Apple")
        self.apple_cb.setChecked(True)
        self.mb_cb = QCheckBox("MusicBrainz")
        row1.addWidget(QLabel("数据源:"))
        row1.addWidget(self.apple_cb)
        row1.addWidget(self.mb_cb)
        top.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("店区:"))
        self.sf_cbs = {}
        for code, label in APPLE_STOREFRONTS:
            cb = QCheckBox(label)
            cb.setChecked(True)
            self.sf_cbs[code] = cb
            row2.addWidget(cb)
        row2.addSpacing(14)
        self.field_cbs = {}
        for k, zh in FIELDS:
            cb = QCheckBox(zh)
            cb.setChecked(True)
            self.field_cbs[k] = cb
            row2.addWidget(cb)
        btn_sel = QPushButton("全选")
        btn_sel.clicked.connect(lambda: self._set_fields(True))
        btn_clr = QPushButton("清空")
        btn_clr.clicked.connect(lambda: self._set_fields(False))
        row2.addSpacing(6)
        row2.addWidget(btn_sel)
        row2.addWidget(btn_clr)
        top.addLayout(row2)

        row3 = QHBoxLayout()
        self.btn_query = QPushButton("查询标签")
        self.btn_query.clicked.connect(self._query)
        self.btn_query_pause = QPushButton("⏸ 暂停查询")
        self.btn_query_pause.clicked.connect(self._query_pause)
        self.btn_query_resume = QPushButton("▶ 继续查询")
        self.btn_query_resume.clicked.connect(self._query_resume)
        self.btn_query_stop = QPushButton("■ 停止查询")
        self.btn_query_stop.clicked.connect(self._query_stop)
        self.btn_query_requery = QPushButton("🔄 重新查询")
        self.btn_query_requery.clicked.connect(self._requery)
        self.btn_write = QPushButton("写入勾选字段")
        self.btn_write.clicked.connect(self._write_selected)
        self.btn_csv_out = QPushButton("导出 CSV…")
        self.btn_csv_out.clicked.connect(self._csv_export)
        self.btn_csv_in = QPushButton("导入 CSV…")
        self.btn_csv_in.clicked.connect(self._csv_import)
        self.btn_group = QPushButton("整专辑套用")
        self.btn_group.clicked.connect(self._apply_to_group)
        self.status = QLabel("")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(160)
        self.progress.setRange(0, 100)
        for b in (self.btn_write, self.btn_csv_out, self.btn_csv_in,
                  self.btn_group, self.btn_query_pause, self.btn_query_resume,
                  self.btn_query_stop, self.btn_query_requery):
            b.setEnabled(False)
        row3.addWidget(self.btn_query)
        row3.addWidget(self.btn_query_pause)
        row3.addWidget(self.btn_query_resume)
        row3.addWidget(self.btn_query_stop)
        row3.addWidget(self.btn_query_requery)
        row3.addSpacing(6)
        row3.addWidget(self.btn_write)
        row3.addSpacing(8)
        row3.addWidget(self.btn_csv_out)
        row3.addWidget(self.btn_csv_in)
        row3.addWidget(self.btn_group)
        row3.addStretch(1)
        row3.addWidget(self.status)
        row3.addWidget(self.progress)
        top.addLayout(row3)
        outer.addLayout(top)

        # ---- two comparison tables ----
        tables = QHBoxLayout()
        left_box = QVBoxLayout()
        self.left_model = TagTableModel(self)
        self.tableL = self._setup_table(self.left_model)
        left_box.addWidget(QLabel("原标签（当前文件里的值）"))
        left_box.addWidget(self.tableL, 1)

        right_box = QVBoxLayout()
        self.right_model = TagTableModel(self, with_file_col=False)
        self.tableR = self._setup_table(self.right_model)
        right_box.addWidget(QLabel("数据源搜到的标签（候选，黄色行=有差异可写）"))
        right_box.addWidget(self.tableR, 1)

        tables.addLayout(left_box, 1)
        tables.addLayout(right_box, 1)
        outer.addLayout(tables, 1)

        # selection sync both ways
        self.tableL.selectionModel().selectionChanged.connect(
            lambda *_: self._sync_sel(self.tableL, self.tableR))
        self.tableR.selectionModel().selectionChanged.connect(
            lambda *_: self._sync_sel(self.tableR, self.tableL))

        # ---- log ----
        self.logtxt = QPlainTextEdit()
        self.logtxt.setReadOnly(True)
        self.logtxt.setMaximumBlockCount(4000)
        outer.addWidget(QLabel("日志"))
        outer.addWidget(self.logtxt)

    # ---------------- helpers ----------------
    def _log(self, msg):
        self.logtxt.appendPlainText(msg)
        self.logtxt.verticalScrollBar().setValue(
            self.logtxt.verticalScrollBar().maximum())

    def _status(self, msg):
        self.status.setText(msg)

    def _set_fields(self, val):
        for cb in self.field_cbs.values():
            cb.setChecked(val)

    def _setup_table(self, model):
        """Create a QTableView with uniform row height and single-line
        (ellipsized) cells so the two tables stay visually aligned — a
        long field (e.g. comment) can no longer stretch one row and make
        left/right rows differ."""
        t = QTableView()
        t.setModel(model)
        t.setSelectionBehavior(QTableView.SelectRows)
        t.setSelectionMode(QTableView.SingleSelection)
        t.setAlternatingRowColors(True)
        # fixed uniform row height; ignore per-cell autosize entirely
        t.verticalHeader().setDefaultSectionSize(26)
        t.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        # single line, ellipsis instead of wrapping/overflow
        t.setTextElideMode(Qt.ElideRight)
        t.setWordWrap(False)
        # no horizontal scrollbar juggling; let columns stretch
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        return t

    def _sync_sel(self, src, dst):
        sm = src.selectionModel()
        if not sm.hasSelection():
            return
        row = sm.selectedRows()[0].row()
        dsm = dst.selectionModel()
        dsm.clearSelection()
        if 0 <= row < dst.model().row_count():
            dsm.select(dst.model().index(row, 0),
                       dsm.Select | dsm.Rows)

    def _enabled_fields(self):
        return {k for k, cb in self.field_cbs.items() if cb.isChecked()}

    def _enabled_providers(self):
        out = []
        if self.apple_cb.isChecked():
            out.append("apple")
        if self.mb_cb.isChecked():
            out.append("mb")
        return out

    def _apple_storefronts(self):
        codes = [c for c, _ in APPLE_STOREFRONTS if self.sf_cbs[c].isChecked()]
        return codes or ["CN", "US", "JP"]

    def _set_busy(self, busy):
        """Enable/disable action buttons. Worker-specific control buttons
        are managed separately (see the scan/query state machine)."""
        self.btn_query.setEnabled(not busy and bool(self.rows))
        self.btn_write.setEnabled(not busy and bool(self.rows))
        self.btn_csv_out.setEnabled(not busy and bool(self.rows))
        self.btn_csv_in.setEnabled(not busy and bool(self.rows))
        self.btn_group.setEnabled(not busy and bool(self.rows))
        self.btn_scan.setEnabled(not busy)

    # ---------------- actions ----------------
    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择音乐文件夹")
        if d:
            self.folder_edit.setText(os.path.normpath(d))

    def closeEvent(self, event):
        """Stop all background workers cleanly before the window closes, so
        no QThread outlives the MainWindow (avoids shutdown races/crashes)."""
        for w in (self._scan_worker, self._query_worker, self._write_worker):
            if w is not None and w.isRunning():
                w.stop()
                w.wait()
        self._scan_worker = None
        self._query_worker = None
        self._write_worker = None
        super().closeEvent(event)

    # ---- scan state machine ----
    def _scan(self):
        """Start a fresh scan, or resume a paused/stored partial scan if one
        exists for the same folder (breakpoint continuation)."""
        folder = self.folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "提示", "请先选择有效的文件夹")
            return
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        # Resume from the breakpoint if a partial scan already produced rows
        # (rows + models already hold them); otherwise scan from scratch.
        prior = len(self.rows)
        self._scan_index = prior
        self._scan_columns_done = False
        self._set_busy(True)
        self._scan_paused = False
        self._status("扫描中…")
        self._scan_worker = ScanWorker(folder, start_index=prior,
                                       prior_count=prior, parent=self)
        self._scan_worker.progress.connect(self._scan_progress)
        self._scan_worker.row_added.connect(self._scan_row_added)
        self._scan_worker.finished.connect(self._scan_done)
        self._scan_worker.start()
        self._set_scan_ctrl_enabled()

    def _set_scan_ctrl_enabled(self):
        running = self._scan_worker is not None and self._scan_worker.isRunning()
        self.btn_scan_pause.setEnabled(running and not self._scan_paused)
        self.btn_scan_resume.setEnabled(running and self._scan_paused)
        self.btn_scan_stop.setEnabled(running)

    def _scan_progress(self, done, total, what):
        if what == "list":
            self._status(f"正在列出文件… {done}/{total}")
        else:
            self._status(f"正在读取标签… {done}/{total}")
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)

    def _scan_row_added(self, index, row):
        """Incremental: append the scanned row to models and rows list."""
        self.rows.append(row)
        self.left_model.append_row(row["rel"], row["tags"].current)
        self.right_model.append_row(row["rel"], row["tags"].candidate)
        if not self._scan_columns_done:
            # apply column widths once the table has its first row visible
            self._apply_track_columns(self.tableL, with_file=True)
            self._apply_track_columns(self.tableR, with_file=False)
            self._scan_columns_done = True

    def _scan_done(self):
        self._scan_worker = None
        self._scan_paused = False
        self._scan_index = len(self.rows)
        self._set_busy(False)
        self._set_scan_ctrl_enabled()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self._status(f"就绪：共 {len(self.rows)} 个文件（左表=当前标签）")

    def _scan_pause(self):
        if self._scan_worker is not None:
            self._scan_worker.pause()
            self._scan_paused = True
            self._set_scan_ctrl_enabled()
            self._status(f"扫描已暂停（已 {len(self.rows)} 个，可继续或停止）")

    def _scan_resume(self):
        if self._scan_worker is not None:
            self._scan_worker.resume()
            self._scan_paused = False
            self._set_scan_ctrl_enabled()
            self._status("扫描继续…")

    def _scan_stop(self):
        """Stop and KEEP already-scanned rows (they stay in the tables)."""
        if self._scan_worker is not None:
            self._scan_worker.stop()
            self._scan_worker.wait()
            self._scan_worker = None
        self._scan_paused = False
        self._set_busy(False)
        self._set_scan_ctrl_enabled()
        self._status(f"扫描已停止：保留已扫到的 {len(self.rows)} 个文件")

    def _refresh_tables(self):
        left_rows = [(r["rel"], r["tags"].current) for r in self.rows]
        self.left_model.set_rows(left_rows)
        diff_rows = [i for i, r in enumerate(self.rows) if r["plan"]]
        # per-cell diff highlight applies to the RIGHT table only, whose
        # column 0 is the first tag (no leading file column), so use the
        # key index directly.
        right_rows = [(r["rel"], r["tags"].candidate) for r in self.rows]
        diff_cols = {i: self._diff_cols_for(r) for i, r in enumerate(self.rows)}
        self.right_model.set_rows(right_rows, diff_rows=diff_rows,
                                  diff_cols=diff_cols)
        # Column widths: user-resizable (Interactive) with sensible initial
        # widths. Recommended width per tag key so left/right stay aligned;
        # right table has no leading file column so its tag columns start
        # at index 0.
        self._apply_track_columns(self.tableL, with_file=True)
        self._apply_track_columns(self.tableR, with_file=False)

    _COL_W = {
        "title": 160, "artist": 130, "album": 150, "album_artist": 130,
        "genre": 110, "date": 90, "track": 70, "disc": 60,
        "composer": 120, "comment": 150,
    }

    def _apply_track_columns(self, table, with_file):
        """Set initial widths for a table. Interactive lets the user drag
        any column separator to widen long titles."""
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        if with_file:
            hh.setSectionResizeMode(0, QHeaderView.Interactive)
            hh.resizeSection(0, 200)
            start = 1
        else:
            start = 0
        for col in range(start, table.model().columnCount()):
            key = KEYS[col - (1 if with_file else 0)]
            hh.resizeSection(col, self._COL_W.get(key, 120))

    def _diff_cols_for(self, r):
        """column indices (into the right table, col0 = first tag) that differ."""
        t = r["tags"]
        cols = set()
        for k, _done in FIELDS:
            if t.needs(k):
                cols.add(KEYS.index(k))
        return cols

    def _query(self):
        """Start/continue querying. If a partial query result already exists
        (paused/stopped mid-way), continue from that breakpoint."""
        if not self.rows:
            QMessageBox.warning(self, "提示", "请先【扫描文件夹】")
            return
        providers = self._enabled_providers()
        if not providers:
            QMessageBox.warning(self, "提示", "请至少勾选一个数据源")
            return
        if self._query_index > 0 and self._query_index < len(self.rows):
            resume = QMessageBox.question(
                self, "继续查询",
                f"已有 {self._query_index}/{len(self.rows)} 行查询结果。\n"
                f"从第 {self._query_index + 1} 行继续，还是重新完整查询？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes)
            if resume == QMessageBox.Yes:
                self._start_query_provider(start_index=self._query_index)
                return
            # No -> start over
        self._query_index = 0
        self._start_query_provider(start_index=0)

    def _requery(self):
        """Re-run the query from scratch using the CURRENT options
        (data source checkboxes, storefronts, enabled fields)."""
        if not self.rows:
            QMessageBox.warning(self, "提示", "请先【扫描文件夹】")
            return
        providers = self._enabled_providers()
        if not providers:
            QMessageBox.warning(self, "提示", "请至少勾选一个数据源")
            return
        # clear previous results so re-query is clean
        for r in self.rows:
            r["tags"].candidate = {k: "" for k, _ in FIELDS}
            r["plan"] = []
            r["platform"] = "-"
        self._start_query_provider(start_index=0)

    def _start_query_provider(self, start_index):
        providers = self._enabled_providers()
        from providers import AppleMusicProvider, MusicBrainzProvider
        provs = []
        if "apple" in providers:
            provs.append(("apple", AppleMusicProvider(self.cache_dir)))
        if "mb" in providers:
            provs.append(("mb", MusicBrainzProvider(self.cache_dir)))
        self._set_busy(True)
        self._query_paused = False
        self._query_index = start_index
        self.progress.setRange(0, len(self.rows))
        self.progress.setValue(start_index)
        self._log(f"开始查询（联网中，请稍候…）从第 {start_index + 1} 行开始")
        self._query_worker = QueryWorker(self.rows, provs,
                                         self._enabled_fields(),
                                         self._apple_storefronts(),
                                         start_index=start_index, parent=self)
        self._query_worker.progress.connect(self._query_progress)
        self._query_worker.row_updated.connect(self._update_row)
        self._query_worker.finished.connect(self._query_done)
        self._query_worker.start()
        self._set_query_ctrl_enabled()

    def _set_query_ctrl_enabled(self):
        running = self._query_worker is not None and self._query_worker.isRunning()
        self.btn_query.setEnabled(not running)
        self.btn_query_pause.setEnabled(running and not self._query_paused)
        self.btn_query_resume.setEnabled(running and self._query_paused)
        self.btn_query_stop.setEnabled(running)
        self.btn_query_requery.setEnabled(bool(self.rows) and not running)

    def _query_progress(self, done, total):
        self.progress.setValue(done)
        self._query_index = done

    def _update_row(self, i):
        """Incremental: refresh row i in the models + log if unmatched."""
        if not (0 <= i < len(self.rows)):
            return
        r = self.rows[i]
        # Debug unmatched rows so the user can see why they're missing.
        if not r["plan"] and not r["tags"].candidate.get("title"):
            t = r["tags"].current
            self._log(f"  · 未匹配: {r['rel']}"
                      f" (title={t.get('title') or '空'}, artist={t.get('artist') or '空'})")
        self.left_model.update_row(i, r["tags"].current)
        diff_cols = self._diff_cols_for(r) if r["plan"] else set()
        self.right_model.update_row(
            i, r["tags"].candidate, diff=bool(r["plan"]),
            diff_cols=diff_cols)

    def _query_pause(self):
        if self._query_worker is not None:
            self._query_worker.pause()
            self._query_paused = True
            self._set_query_ctrl_enabled()
            self._status(f"查询已暂停（已完成 {self._query_index} 行，可继续或停止）")

    def _query_resume(self):
        if self._query_worker is not None:
            self._query_worker.resume()
            self._query_paused = False
            self._set_query_ctrl_enabled()
            self._status("查询继续…")

    def _query_stop(self):
        """Stop the query and KEEP already-queried candidates.
        The resume point is taken from the worker's last fully-processed
        row so no row is lost or duplicated on continue."""
        w = self._query_worker
        resume_from = (w.last_processed + 1) if w is not None else self._query_index
        if w is not None:
            w.stop()
            w.wait()
            self._query_worker = None
        self._query_paused = False
        self._query_index = resume_from
        self._set_busy(False)
        self._set_query_ctrl_enabled()
        self._refresh_tables()
        self._status(f"查询已停止：已处理 {resume_from} 行，可继续查询从第 {resume_from + 1} 行恢复")

    def _query_done(self):
        self._query_worker = None
        self._query_paused = False
        self._query_index = len(self.rows)
        self._set_busy(False)
        self._set_query_ctrl_enabled()
        self._refresh_tables()
        self._log("✅ 查询完成。黄色行=候选与原值不同，可写入。")
        self._status("查询完成，请核对两表后写入")

    def _write_selected(self):
        enabled = self._enabled_fields()
        todo = [r for r in self.rows if r.get("plan")]
        if not todo:
            QMessageBox.information(self, "没有可写内容",
                                    "请先【查询标签】并核对右表候选。")
            return
        total = sum(len([p for p in r["plan"] if p[0] in enabled]) for r in todo)
        files = len(todo)
        if not QMessageBox.question(
                self, "确认写入",
                f"将更新 {files} 个文件、共 {total} 个字段。\n"
                f"仅写入你在界面勾选的字段，其余标签保持不变。\n\n继续吗？",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            return
        self._set_busy(True)
        self.progress.setRange(0, len(todo))
        self._write_worker = WriteWorker(self.rows, enabled, self)
        self._write_worker.log.connect(self._log)
        self._write_worker.progress.connect(self._write_progress)
        self._write_worker.finished.connect(self._write_done)
        self._write_worker.start()

    def _write_progress(self, done, total):
        self.progress.setValue(done)

    def _write_done(self, ok, skip, err):
        self._write_worker = None
        self._set_busy(False)
        self._refresh_tables()
        self._refresh_tables()
        msg = f"写入完成：成功 {ok}，跳过 {skip}，失败 {err}。"
        self._log("✅ " + msg)
        self._status(msg)
        QMessageBox.information(self, "完成", msg)

    def _csv_export(self):
        if not self.rows:
            QMessageBox.warning(self, "提示", "请先【扫描文件夹】")
            return
        dst, _ = QFileDialog.getSaveFileName(
            self, "导出为 CSV", "标签编辑.csv", "CSV 文件 (*.csv)")
        if not dst:
            return
        data = self._csv_export_data()
        try:
            with open(dst, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerows(data)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            return
        self._log(f"✅ 已导出 CSV：{dst}")
        self._status("已导出 CSV，可在 Excel 中编辑『新值』列后导入")

    def _csv_export_data(self):
        cols = []
        for k, zh in FIELDS:
            cols.append((k, zh + "(当前)", zh + "(新值)"))
        header = ["文件"] + [label for _k, _c, _n in cols for label in (_c, _n)]
        out = [header]
        for r in self.rows:
            t = r["tags"]
            row = [r["rel"]]
            for k, _c, _n in cols:
                v = t.current.get(k)
                row.append("" if isinstance(v, bytes) else ("" if v is None else str(v).strip()))
                v = t.candidate.get(k)
                row.append("" if isinstance(v, bytes) else ("" if v is None else str(v).strip()))
            out.append(row)
        return out

    def _csv_import(self):
        if not self.rows:
            QMessageBox.warning(self, "提示", "请先【扫描文件夹】")
            return
        src, _ = QFileDialog.getOpenFileName(
            self, "选择要导入的 CSV", "", "CSV 文件 (*.csv)")
        if not src:
            return
        try:
            with open(src, encoding="utf-8-sig") as f:
                data = list(csv.reader(f))
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))
            return
        taken, _applied = self._csv_import_data(data)
        self._refresh_tables()
        self._log(f"✅ 导入 CSV 完成：更新了 {taken} 个文件的行")
        self._status("CSV 导入完成，请核对右表黄色行后写入")
        QMessageBox.information(self, "导入完成",
                                f"已从 {os.path.basename(src)} 应用 {taken} 个文件的新值。")

    def _csv_import_data(self, csv_rows):
        if len(csv_rows) < 2:
            return 0, []
        header = csv_rows[0]
        cols = []
        for k, zh in FIELDS:
            cname, nname = zh + "(当前)", zh + "(新值)"
            if cname in header and nname in header:
                cols.append((k, header.index(cname), header.index(nname)))
        taken = 0
        applied = []
        enabled = self._enabled_fields()
        for row in csv_rows[1:]:
            if not row:
                continue
            rel = row[0].strip()
            r = next((r for r in self.rows if r["rel"] == rel), None)
            if r is None:
                continue
            t = r["tags"]
            changed = False
            for k, cidx, nidx in cols:
                nval = row[nidx].strip() if len(row) > nidx else ""
                if not nval:
                    continue
                cur = t.current.get(k)
                cur_s = "" if isinstance(cur, bytes) else (str(cur).strip() if cur else "")
                if nval == cur_s:
                    continue
                t.candidate[k] = nval
                changed = True
            if changed:
                r["plan"] = t.plan(enabled)
                taken += 1
                applied.append(self.rows.index(r))
        return taken, applied

    def _apply_to_group(self):
        sel = self.tableL.selectionModel() or self.tableR.selectionModel()
        sm = self.tableL.selectionModel()
        if not sm.hasSelection() or not self.rows:
            QMessageBox.warning(self, "提示", "请先在左/右表中选中一首歌")
            return
        idx = sm.selectedRows()[0].row()
        if idx >= len(self.rows):
            return
        group, warns = self._group_for(idx)
        if "无候选" in warns:
            QMessageBox.information(self, "无候选",
                                    "选中行的字段没有可套用的候选值，请先对该文件查询/导入候选。")
            return
        if "无同专辑" in warns:
            QMessageBox.information(self, "无同专辑",
                                    "未找到与选中行「同目录 + 同专辑名」的其它文件。\n"
                                    "请确保文件按专辑分好目录、且专辑名标签一致。")
            return
        src = self.rows[idx]
        enabled = self._enabled_fields()
        src_have = {k for k in enabled if src["tags"].candidate.get(k)}
        desc = "、".join(sorted(FIELD_DESC[k] for k in src_have))
        if not QMessageBox.question(
                self, "整组套用",
                f"将把选中行查询到的字段（{desc}）\n"
                f"套用到同专辑（{src['tags'].current.get('album') or ''}）"
                f"的 {len(group)} 个文件。\n只写界面勾选的字段，其余保持。继续吗？",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            return
        changed = self._apply_candidates(idx, group)
        self._refresh_tables()
        self._log(f"✅ 整组套用完成：同专辑共套用 {len(changed)} 个文件")
        self._status(f"整组套用完成：{len(changed)} 个文件获得候选")
        QMessageBox.information(self, "完成",
                                f"已将选中行的候选套用到同专辑 {len(changed)} 个文件，请核对后写入。")

    def _group_for(self, idx):
        src = self.rows[idx]
        src_album = (src["tags"].current.get("album") or "").strip().casefold()
        src_dir = os.path.dirname(src["rel"])
        enabled = self._enabled_fields()
        src_have = {k for k in enabled if src["tags"].candidate.get(k)}
        group, warns = [], []
        if not src_have:
            warns.append("无候选")
            return group, warns
        for i, r in enumerate(self.rows):
            if i == idx:
                continue
            if os.path.dirname(r["rel"]) != src_dir:
                continue
            r_album = (r["tags"].current.get("album") or "").strip().casefold()
            if r_album == src_album:
                group.append(i)
        if not group:
            warns.append("无同专辑")
        return group, warns

    def _apply_candidates(self, idx, group_indices):
        src = self.rows[idx]
        enabled = self._enabled_fields()
        src_have = {k for k in enabled if src["tags"].candidate.get(k)}
        changed = []
        for i in group_indices:
            t = self.rows[i]["tags"]
            any_v = False
            for k in src_have:
                v = src["tags"].candidate.get(k)
                if isinstance(v, bytes) or v:
                    t.candidate[k] = v
                    any_v = True
            if any_v:
                self.rows[i]["plan"] = t.plan(enabled)
                changed.append(i)
        return changed
