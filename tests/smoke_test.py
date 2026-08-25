"""Smoke tests for MusicTagTool (PySide6 build).

Priority #1 (the historical blocker): MANY rows must render on screen.
This is validated through the Qt model/view path with a real pixel
grab — the exact failure mode of the old Tk build (rows not
rendering/drawing) would be caught here.

Also covers the reused business core: AudioTags needs/plan, scanner
parsing of tag values, and the CSV/album-group logic pulled from the
old app (pure data, no network, no real writes).

Run from project root:   python tests/smoke_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QTableView  # noqa: E402

from model import AudioTags, FIELDS, FIELD_DESC  # noqa: E402
import scanner  # noqa: E402
from app.table_model import TagTableModel, HEADERS, KEYS  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from app.workers import QueryWorker  # noqa: E402


def test_fields_integrity():
    keys = [k for k, _ in FIELDS]
    assert set(keys) == set(KEYS), "KEYS must match FIELDS keys"
    assert len(keys) == len(set(keys))
    assert "title" in keys and "genre" in keys
    # every field has a Chinese label
    for k, zh in FIELDS:
        assert zh and zh != k, f"{k} has no label"
    print(f"OK: FIELDS integrity ({len(keys)} fields)")


def test_audio_tags_needs_and_plan():
    t = AudioTags(path="x.m4a")
    t.current = {"title": "Old", "artist": "", "album": "A",
                 "genre": "", "track": "", "disc": "",
                 "album_artist": "", "date": "", "composer": "",
                 "comment": ""}
    # needs() when candidate differs or current empty
    t.candidate["genre"] = "Rock"
    assert t.needs("genre") is True
    t.candidate["artist"] = "NewArtist"
    assert t.needs("artist") is True
    t.candidate["album"] = "A"            # same as current
    assert t.needs("album") is False
    t.candidate["title"] = ""            # empty candidate → no
    assert t.needs("title") is False
    # plan() only includes enabled + needs
    enabled = {"genre", "artist", "title", "album"}
    plan = t.plan(enabled)
    plan_keys = [k for k, _, _ in plan]
    assert "genre" in plan_keys and "artist" in plan_keys
    assert "album" not in plan_keys and "title" not in plan_keys
    print("OK: AudioTags.needs/plan")


def test_scanner_value_parsing():
    # scanner._first is a pure value normalizer; test against edge inputs.
    assert scanner._first(None) == ""
    assert scanner._first([]) == ""
    assert scanner._first(["Pop"], 0) == "Pop"
    assert scanner._first(b"\xe6\xb5\x81\xe6\xb4\xbe") != ""  # bytes → not blank
    assert scanner._first(["12/15"]) == "12/15"
    assert scanner._trk_num(["12/15"]) == "12"
    assert scanner._trk_mp4([]) == ""
    assert scanner.is_audio("a.m4a") and scanner.is_audio("b.FLAC")
    assert not scanner.is_audio("c.txt")
    print("OK: scanner value parsing + is_audio")


def _mk_rows(n, album="专辑A"):
    rows = []
    for i in range(n):
        t = AudioTags(path=f"f{i}.m4a")
        t.current = {"title": f"T{i}", "artist": "歌手A", "album": album,
                     "genre": "", "track": "", "disc": "", "album_artist": "",
                     "date": "", "composer": "", "comment": ""}
        rows.append({"path": f"f{i}.m4a", "rel": f"专辑A/曲{i}.m4a",
                     "tags": t, "platform": "-", "plan": []})
    return rows


def test_table_model_render(app: QApplication, rows):
    """THE historical blocker: many rows must all render."""
    n = len(rows)
    left = TagTableModel()
    right = TagTableModel()
    model_rows = [(r["rel"], r["tags"].current) for r in rows]
    left.set_rows(model_rows)
    # a couple of diff rows (genre candidate) to test highlight too
    rows[0]["tags"].candidate["genre"] = "Rock"
    rows[0]["plan"] = [("genre", "", "Rock")]
    right_rows = [(r["rel"], r["tags"].candidate) for r in rows]
    right.set_rows(right_rows, diff_rows={0} if n > 0 else set())

    app._left = QTableView()
    app._right = QTableView()
    app._left.setModel(left)
    app._right.setModel(right)
    for t in (app._left, app._right):
        t.resize(760, 500)
        t.show()
    QTest.qWait(50)

    # LEFT: all n rows have correct title text in model
    assert left.rowCount() == n
    for i in range(n):
        assert left.data(left.index(i, 1)) == f"T{i}", f"row {i} title"
        assert left.data(left.index(i, 2)) == "歌手A"
    # RIGHT: diff row highlight set
    if n:
        bg = right.data(right.index(0, 0), Qt.BackgroundRole)
        assert bg is not None or right._diff, "diff row should be marked"
    # pixel render: both tables must actually paint content
    total_dark = 0
    for t in (app._left, app._right):
        img = t.grab().toImage()
        assert not img.isNull() and img.width() > 0 and img.height() > 0, "null/empty grab"
        w, h = img.width(), img.height()
        dark = 0
        for y in range(0, h, 3):
            for x in range(0, w, 3):
                px = img.pixel(x, y)  # ARGB int; avoids pixelColor's offscreen quirk
                if (px & 0xFF) + ((px >> 8) & 0xFF) + ((px >> 16) & 0xFF) < 700:
                    dark += 1
        total_dark += dark
        assert dark > 40, f"table blank: only {dark} samples ({w}x{h})"
    print(f"OK: {n} rows in both tables, pixel-render {total_dark} samples (NOT blank)")


def test_csv_export_import():
    inst = MainWindow.__new__(MainWindow)
    inst.rows = _mk_rows(3)
    inst.field_cbs = {k: type("CB", (), {"isChecked": lambda self: True})()
                      for k, _ in FIELDS}
    # run export data
    data = inst._csv_export_data()
    header = data[0]
    assert header[0] == "文件"
    assert "流派(当前)" in header and "流派(新值)" in header
    # cover field was removed entirely — no 封面插画 column should exist
    assert "封面插画" not in header
    assert all(zh + "(当前)" in header for _k, zh in FIELDS), "every field exported"
    assert len(data) == 1 + 3
    # import: apply genre to row0
    h = header
    def c(suffix): return h.index(suffix)
    import_rows = [h]
    row0 = ["专辑A/曲0.m4a"] + [""] * (len(h) - 1)
    row0[c("流派(新值)")] = "慢摇"
    import_rows.append(row0)
    taken, applied = inst._csv_import_data(import_rows)
    assert taken == 1 and applied == [0], (taken, applied)
    assert inst.rows[0]["tags"].candidate["genre"] == "慢摇"
    print("OK: CSV export/import")


def test_album_group():
    inst = MainWindow.__new__(MainWindow)
    inst.rows = _mk_rows(3)
    # row1 and row2 same dir+album; row3 different album
    inst.rows = [
        {"rel": "A/1.m4a", "path": "p1", "tags": _mk_audio("专辑A"),
         "platform": "-", "plan": []},
        {"rel": "A/2.m4a", "path": "p2", "tags": _mk_audio("专辑A"),
         "platform": "-", "plan": []},
        {"rel": "B/x.m4a", "path": "px", "tags": _mk_audio("专辑B"),
         "platform": "-", "plan": []},
    ]
    inst.field_cbs = {k: type("CB", (), {"isChecked": lambda self: True})()
                      for k, _ in FIELDS}
    # row0 has candidate genre
    inst.rows[0]["tags"].candidate["genre"] = "摇滚"
    group, warns = inst._group_for(0)
    assert group == [1], group
    changed = inst._apply_candidates(0, [1])
    assert changed == [1]
    assert inst.rows[1]["tags"].candidate["genre"] == "摇滚"
    assert inst.rows[0]["tags"].candidate["genre"] == "摇滚"  # unchanged src
    # row2 different dir → not in group
    assert inst._group_for(2)[0] == []
    print("OK: album-group apply")


def _mk_audio(album):
    t = AudioTags(path="")
    t.current = {"title": "曲", "artist": "歌手", "album": album,
                 "genre": "", "track": "", "disc": "", "album_artist": "",
                 "date": "", "composer": "", "comment": ""}
    return t


def test_mainwindow_smoke(app):
    """Instantiate the real window offscreen to catch build/API errors."""
    win = MainWindow()
    app._win = win
    assert win.btn_query is not None
    # new scan/query control buttons exist
    for name in ("btn_scan_pause", "btn_scan_resume", "btn_scan_stop",
                 "btn_query_pause", "btn_query_resume", "btn_query_stop",
                 "btn_query_requery"):
        assert getattr(win, name) is not None, name
    print("OK: MainWindow constructed + control buttons present")


def test_pause_controls_present(app):
    """Button wiring doesn't crash on construction (OFFSCREEN)."""
    win = MainWindow()
    app._w = win
    # no worker running -> control buttons disabled
    assert not win.btn_scan_pause.isEnabled()
    assert not win.btn_query_stop.isEnabled()
    print("OK: control buttons initial disabled state")


def test_pausable_semantics():
    """_gate() pause/resume/stop behavior, fully synchronous (no threads)."""
    from app.workers import _PausableThread
    import threading, time

    class Fake(_PausableThread):
        def __init__(self):
            super().__init__()
        def run(self):
            pass

    t = Fake()
    assert t._gate() is True and t.is_paused() is False
    t.pause()
    assert t.is_paused() is True and not t._coef.is_set()
    t.resume()
    assert t.is_paused() is False
    assert t._gate() is True
    # stop wins over pause, no deadlock
    t2 = Fake()
    t2.pause()
    t2.stop()
    res = []
    threading.Thread(target=lambda: res.append(t2._gate())).start()
    time.sleep(0.15)
    assert res == [False], f"stop must un-gate even while paused: {res}"
    assert t2.is_stopped() is True
    print("OK: pause/resume/stop gate semantics")


def test_query_breakpoint_continuation():
    """Stopping a query then resuming from the worker's last-processed row
    must continue exactly where it left off (no row lost/duplicated)."""
    from model import FIELDS  # reuse module-level FIELDS
    import app.workers as W

    class SlowProv:
        def search(self, *a, **k):
            import time
            time.sleep(0.05)
            return None

    rows = []
    for i in range(60):
        t = AudioTags(path="p%d" % i)
        t.current = {"title": "S%d" % i, "artist": "A", "album": "B",
                     "genre": "", "track": "", "disc": "", "album_artist": "",
                     "date": "", "composer": "", "comment": ""}
        rows.append({"path": "p%d" % i, "rel": "f%d" % i, "tags": t,
                     "platform": "-", "plan": []})
    enabled = {k for k, _ in FIELDS}
    w1 = QueryWorker(rows, [("apple", SlowProv())], enabled, ["CN"],
                     start_index=0)
    w1.start()
    import time
    time.sleep(1.2)
    bp = w1.last_processed + 1
    w1.stop()
    w1.wait()
    assert bp > 0 and bp < 60, f"breakpoint oob: {bp}"
    # resume
    from PySide6.QtWidgets import QApplication as _App
    w2 = QueryWorker(rows, [("apple", SlowProv())], enabled, ["CN"],
                     start_index=bp)
    seen = []
    w2.row_updated.connect(lambda i: seen.append(i))
    w2.start()
    deadline = time.time() + 15
    while w2.isRunning() and time.time() < deadline:
        _App.processEvents()
        time.sleep(0.03)
    _App.processEvents()
    assert len(seen) == 60 - bp, f"resume processed {len(seen)}, expected {60-bp}"
    assert all(i >= bp for i in seen), "resume re-processed already-done rows"
    print(f"OK: query breakpoint @{bp} -> continued {len(seen)}/60 rows, no dup")


def main() -> int:
    app = QApplication(sys.argv)
    test_fields_integrity()
    test_audio_tags_needs_and_plan()
    test_scanner_value_parsing()
    rows = _mk_rows(50)
    test_table_model_render(app, rows)
    test_csv_export_import()
    test_album_group()
    test_mainwindow_smoke(app)
    test_pause_controls_present(app)
    test_pausable_semantics()
    test_query_breakpoint_continuation()
    print("\nALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
