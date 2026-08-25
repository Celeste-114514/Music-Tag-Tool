"""Background workers (QThread). All network/disk work happens here so
the GUI thread never blocks — results come back via Qt Signals.

Each worker supports pause/resume (threading.Event) and stop (flag).
Stopping does NOT discard already-produced rows: the GUI keeps whatever
was emitted, and restarting a scan/query resumes from the same worker's
internal index (breakpoint continuation)."""
import os
import threading

from PySide6.QtCore import QThread, Signal

from model import AudioTags, FIELDS
import scanner
import writer


class _PausableThread(QThread):
    """Base: pause()/resume() via an Event, stop() via a flag.
    Run-loop should call self._gate() at each unit of work."""

    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._coef = threading.Event()
        self._coef.set()
        self._stop = False
        self._lock = threading.Lock()

    def pause(self):
        self._coef.clear()

    def resume(self):
        self._coef.set()

    def stop(self):
        self._stop = True
        self._coef.set()   # release any wait so the loop can see the flag

    def _gate(self):
        """Block the thread while paused. Returns False if stop requested."""
        if self._stop:
            return False
        self._coef.wait()      # blocks until resumed
        return not self._stop

    def is_paused(self):
        return not self._coef.is_set()

    def is_stopped(self):
        return self._stop


class ScanWorker(_PausableThread):
    """Lists files (off-thread) then reads tags one file at a time.
    Emits row_added per file so the GUI can show rows incrementally and
    keep them across pause/stop. Restarting this worker resumes from the
    current index (breakpoint) instead of re-scanning everything."""

    progress = Signal(int, int, str)  # done, total, phase("list"/"read")
    row_added = Signal(int, dict)     # (index, row_dict) appended
    finished = Signal()               # normal completion (all files scanned)

    def __init__(self, folder: str, start_index=0, prior_count=0, parent=None):
        super().__init__(parent)
        self._folder = folder
        self._start = start_index   # resume point
        self._prior = prior_count   # rows already in GUI (for indices)

    def run(self):
        # list phase (not cancellable between files; fast)
        files = scanner.list_files(self._folder)
        total = len(files)
        self.progress.emit(self._prior, total, "list")
        i = self._start
        while i < total:
            if not self._gate():
                return  # stopped: nothing further emitted
            p = files[i]
            tags = AudioTags(path=p)
            try:
                tags.current = scanner.read_file_tags(p)
            except Exception:
                pass
            rel = os.path.relpath(p, self._folder)
            row = {"path": p, "rel": rel, "tags": tags,
                   "platform": "-", "plan": []}
            self.row_added.emit(i, row)
            i += 1
            if i % 10 == 0 or i == total:
                self.progress.emit(i, total, "read")
        self.finished.emit()


class QueryWorker(_PausableThread):
    """Queries providers for each row (optionally from a resume index).
    Emits row_updated per row so candidates appear incrementally."""

    log = Signal(str)
    progress = Signal(int, int)
    row_updated = Signal(int)
    finished = Signal()

    def __init__(self, rows, provs, enabled_fields, storefronts, start_index=0,
                 parent=None):
        super().__init__(parent)
        self._rows = rows
        self._provs = provs   # list of ("apple"/"mb", provider)
        self._enabled = enabled_fields
        self._sf = storefronts
        self._start = start_index
        self.last_processed = start_index - 1  # last fully-processed row index

    def run(self):
        # Skip rows that already have a candidate for every enabled reachable
        # from a prior run only when resuming from a fresh start; when resuming
        # mid-way we trust the stored start index.
        for i in range(self._start, len(self._rows)):
            if not self._gate():
                return  # stopped/paused-out
            r = self._rows[i]
            t = r["tags"]
            entry = None
            for pk, prov in self._provs:
                try:
                    if pk == "apple":
                        cand = prov.search(t.current.get("artist"),
                                           t.current.get("title"),
                                           t.current.get("album"),
                                           storefronts=self._sf)
                    else:
                        cand = prov.search(t.current.get("artist"),
                                           t.current.get("title"),
                                           t.current.get("album"))
                except Exception:
                    cand = None
                if cand and any(cand.get(k) for k, _ in FIELDS):
                    entry = cand
                    r["platform"] = "Apple" if pk == "apple" else "MusicBrainz"
                    break
            if entry:
                for k, _ in FIELDS:
                    v = entry.get(k)
                    t.candidate[k] = v if isinstance(v, bytes) else (str(v).strip() if v else "")
                r["plan"] = t.plan(self._enabled)
            else:
                r["platform"] = "-"
                r["plan"] = []
            self.progress.emit(i + 1, len(self._rows))
            self.row_updated.emit(i)
            self.last_processed = i
        self.log.emit("✅ 查询完成")
        self.finished.emit()


class WriteWorker(_PausableThread):
    """Applies each file's plan (only enabled fields) and re-reads tags."""

    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(int, int, int)  # ok, skip, err

    def __init__(self, rows, enabled_fields, parent=None):
        super().__init__(parent)
        self._rows = rows
        self._enabled = enabled_fields

    def run(self):
        todo = [r for r in self._rows if r.get("plan")]
        ok = skip = err = 0
        for i, r in enumerate(todo):
            if not self._gate():
                # stopped: keep whatever we already wrote
                self.progress.emit(i, len(todo))
                break
            plan = [(k, c, n) for (k, c, n) in r["plan"] if k in self._enabled]
            if not plan:
                skip += 1
            else:
                try:
                    writer.write_fields(r["path"], plan)
                    ok += 1
                    r["tags"].current = scanner.read_file_tags(r["path"])
                    r["plan"] = []
                except Exception as e:
                    err += 1
                    self.log.emit(f"  ⚠ 写入失败: {r['rel']} -> {str(e)[:90]}")
            self.progress.emit(i + 1, len(todo))
        self.finished.emit(ok, skip, err)
