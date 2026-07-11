"""A dynamic list of (start, end) integer ranges: one row per range, a
button to add more, and a way to remove rows (at least one always stays).
Used by PluginRequestDialog whenever a field's default value looks like
a list of (lo, hi) tuples -- e.g. for a future Threshold plugin needing
several pixel-value ranges."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class RangeListWidget(QWidget):
    def __init__(
        self,
        initial: list[tuple[int, int | None]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._rows: list[tuple[QLineEdit, QLineEdit, QWidget]] = []

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)

        add_button = QPushButton("+ Add Range")
        add_button.clicked.connect(lambda: self._add_row())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._rows_layout)
        outer.addWidget(add_button)

        for lo, hi in (initial or [(0, None)]):
            self._add_row(lo, hi)

    def _add_row(self, lo: int = 0, hi: int | None = None) -> None:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        lo_edit = QLineEdit(str(lo))
        hi_edit = QLineEdit("" if hi is None else str(hi))
        hi_edit.setPlaceholderText("max")

        remove_button = QPushButton("-")
        remove_button.setFixedWidth(24)
        remove_button.clicked.connect(lambda: self._remove_row(row_widget))

        row_layout.addWidget(QLabel("from"))
        row_layout.addWidget(lo_edit)
        row_layout.addWidget(QLabel("to"))
        row_layout.addWidget(hi_edit)
        row_layout.addWidget(remove_button)

        self._rows_layout.addWidget(row_widget)
        self._rows.append((lo_edit, hi_edit, row_widget))

    def _remove_row(self, row_widget: QWidget) -> None:
        if len(self._rows) <= 1:
            return  # at least one range must remain
        self._rows = [r for r in self._rows if r[2] is not row_widget]
        self._rows_layout.removeWidget(row_widget)
        row_widget.deleteLater()

    def get_ranges(self) -> list[tuple[int, int | None]]:
        if not self._rows:
            raise ValueError("At least one range is required.")

        ranges: list[tuple[int, int | None]] = []
        for lo_edit, hi_edit, _ in self._rows:
            lo_text = lo_edit.text().strip()
            hi_text = hi_edit.text().strip()
            if not lo_text:
                raise ValueError("Every range needs a starting value.")
            try:
                lo = int(lo_text)
            except ValueError:
                raise ValueError(f"'{lo_text}' is not a valid integer.")

            hi: int | None = None
            if hi_text:
                try:
                    hi = int(hi_text)
                except ValueError:
                    raise ValueError(f"'{hi_text}' is not a valid integer.")

            ranges.append((lo, hi))
        return ranges
