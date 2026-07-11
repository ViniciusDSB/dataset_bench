"""Dialog shown for a plugin's dialog.request() calls. Infers one input
widget per field from that field's default value's Python type -- plugin
authors never touch Qt directly, they just pass a {name: default} dict."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from ui.range_widget import RangeListWidget


def _looks_like_ranges(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(v, tuple) and len(v) == 2 for v in value
    )


class PluginRequestDialog(QDialog):
    def __init__(
        self, text: str, fields: dict[str, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Input needed")
        self._fields: dict[str, QWidget] = {}

        layout = QFormLayout(self)

        if text:
            label = QLabel(text)
            label.setWordWrap(True)
            layout.addRow(label)

        for name, default in fields.items():
            widget = self._make_widget(default)
            self._fields[name] = widget
            layout.addRow(name, widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @staticmethod
    def _make_widget(default: Any) -> QWidget:
        # bool check MUST come before int -- bool is a subclass of int.
        if isinstance(default, bool):
            widget = QCheckBox()
            widget.setChecked(default)
            return widget
        if isinstance(default, int):
            widget = QSpinBox()
            widget.setRange(-1_000_000, 1_000_000)
            widget.setValue(default)
            return widget
        if isinstance(default, float):
            widget = QDoubleSpinBox()
            widget.setRange(-1_000_000.0, 1_000_000.0)
            widget.setValue(default)
            return widget
        if _looks_like_ranges(default):
            return RangeListWidget(initial=default)
        # Fallback covers str, None, and anything else: plain text field.
        return QLineEdit("" if default is None else str(default))

    def _on_accept(self) -> None:
        try:
            self.values()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return
        self.accept()

    def values(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, widget in self._fields.items():
            if isinstance(widget, QCheckBox):
                result[name] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                result[name] = widget.value()
            elif isinstance(widget, RangeListWidget):
                result[name] = widget.get_ranges()  # raises ValueError if invalid
            elif isinstance(widget, QLineEdit):
                result[name] = widget.text()
        return result
