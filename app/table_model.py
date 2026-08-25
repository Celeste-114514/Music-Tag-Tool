"""QAbstractTableModel for the two comparison tables.

Shared by both the LEFT table (current tags) and the RIGHT table
(candidate tags). The RIGHT table can hide the leading "file" column.
Model/view architecture means Qt paints every cell — this is the design
that removes the historical "rows don't render" failure mode on
high-DPI Windows, without any manual redraw code.
"""
import os

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from model import FIELD_DESC, FIELDS

KEYS = [k for k, _ in FIELDS]
FIELD_HEADERS = [FIELD_DESC[k] for k in KEYS]          # tag columns only
HEADERS = ["文件"] + FIELD_HEADERS                       # left table (with file col)


class TagTableModel(QAbstractTableModel):
    """One table of rows. with_file_col controls whether the leading
    filename column is shown (left table yes, right table no).
    """

    def __init__(self, parent=None, with_file_col=True):
        super().__init__(parent)
        self._with_file = with_file_col
        self._rows = []     # list of (rel, values_dict)
        self._diff = set()  # row indices that have an actionable diff
        self._diff_cols = {}  # row -> set of column indices with diff

    # ---- data entry ----

    def set_rows(self, rows, diff_rows=(), diff_cols=None, diff_data=None):
        """rows: list[(rel, dict)]. diff_rows: indices to highlight whole row.
        diff_cols/diff_data: for per-cell diff on the right table."""
        self.beginResetModel()
        self._rows = list(rows)
        self._diff = set(diff_rows)
        self._diff_cols = diff_cols or {}
        self._diff_data = diff_data or {}
        self.endResetModel()

    def append_row(self, rel, values):
        """Append one row and emit a row-inserted signal (incremental scan)."""
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append((rel, dict(values)))
        self.endInsertRows()

    def update_row(self, row, values, diff=False, diff_cols=None):
        """In-place update of one row's values (incremental query refresh).
        Emits a dataChanged signal for the changed row."""
        if not (0 <= row < len(self._rows)):
            return
        rel = self._rows[row][0]
        self._rows[row] = (rel, dict(values))
        if diff:
            self._diff.add(row)
        else:
            self._diff.discard(row)
        if diff_cols is not None:
            self._diff_cols[row] = diff_cols
        top = self.index(row, 0)
        bottom = self.index(row, self.columnCount() - 1)
        self.dataChanged.emit(top, bottom, [])

    def rel_equals(self, row, rel):
        """True if the model row's path matches rel (used to locate rows)."""
        return 0 <= row < len(self._rows) and self._rows[row][0] == rel

    def row_count(self):
        return len(self._rows)

    # ---- QAbstractTableModel interface ----

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(HEADERS) if self._with_file else len(FIELD_HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if not (0 <= r < len(self._rows)):
            return None
        total_cols = self.columnCount()
        if c >= total_cols:
            return None
        values = self._rows[r][1]
        # map visible column -> value
        if self._with_file:
            if c == 0:
                text = self._rows[r][0]
            else:
                text = self._cell_text(KEYS[c - 1], values)
        else:
            text = self._cell_text(KEYS[c], values)
        if role == Qt.DisplayRole:
            return text
        if role == Qt.ToolTipRole:
            return self._rows[r][0]
        if role == Qt.BackgroundRole or role == Qt.ForegroundRole:
            if r in self._diff:
                return Qt.yellow if role == Qt.BackgroundRole else Qt.black
            if r in self._diff_cols and c in self._diff_cols[r]:
                return (Qt.lightGray if role == Qt.BackgroundRole else Qt.black)
        return None

    @staticmethod
    def _cell_text(key, values):
        v = values.get(key, "")
        if isinstance(v, bytes):
            return "✓" if v else ""
        return v

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if self._with_file:
                return HEADERS[section]
            return FIELD_HEADERS[section]
        return None

    def row_rel(self, row):
        if 0 <= row < len(self._rows):
            return self._rows[row][0]
        return ""
