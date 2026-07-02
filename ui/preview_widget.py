"""Image preview widget: displays a numpy array and reports (x, y): value
under the mouse cursor, the same way matplotlib does when you hover over
an imshow plot."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget


def array_to_qpixmap(array: np.ndarray) -> QPixmap:
    """Normalize any numeric array to 8-bit for on-screen display only.
    The original array (not this pixmap) remains the source of truth for
    pixel-value lookups."""
    arr = array
    if arr.ndim == 3 and arr.shape[2] == 1:
        arr = arr[:, :, 0]

    arr = arr.astype(np.float32)
    lo, hi = np.percentile(arr, (0.5, 99.5)) if arr.size else (0, 1)
    if hi <= lo:
        hi = lo + 1
    arr = np.clip((arr - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)

    if arr.ndim == 2:
        h, w = arr.shape
        qimg = QImage(arr.data, w, h, w, QImage.Format_Grayscale8)
    else:
        h, w, ch = arr.shape
        fmt = QImage.Format_RGB888 if ch == 3 else QImage.Format_RGBA8888
        qimg = QImage(arr.data, w, h, w * ch, fmt)

    return QPixmap.fromImage(qimg.copy())


class ImagePreviewWidget(QWidget):
    """Shows the current image; emits pixel_hovered(x, y, value_str) as the
    mouse moves over it, and pixel_left() when the mouse leaves the image."""

    pixel_hovered = Signal(int, int, str)
    pixel_left = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._array: np.ndarray | None = None
        self._pixmap: QPixmap | None = None

        self._label = QLabel("No image loaded")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setMouseTracking(True)
        self._label.installEventFilter(self)
        self.setMouseTracking(True)

        # Scroll area keeps the label at its true pixel size (required for
        # correct mouse-to-pixel mapping) without forcing this widget -- and
        # therefore the whole window -- to grow to the image's dimensions.
        # Small images stay centered; large images get scrollbars instead
        # of stretching the window off-screen or getting cropped.
        scroll_area = QScrollArea()
        scroll_area.setWidget(self._label)
        scroll_area.setWidgetResizable(False)
        scroll_area.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area)
        layout.setContentsMargins(0, 0, 0, 0)

    def set_array(self, array: np.ndarray) -> None:
        self._array = array
        self._pixmap = array_to_qpixmap(array)
        self._label.setPixmap(self._pixmap)
        self._label.resize(self._pixmap.size())

    def array(self) -> np.ndarray | None:
        return self._array

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        if obj is self._label and self._array is not None:
            if event.type() == QMouseEvent.MouseMove:
                self._handle_mouse_move(event)
            elif event.type() == QMouseEvent.Leave:
                self.pixel_left.emit()
        return super().eventFilter(obj, event)

    def _handle_mouse_move(self, event: QMouseEvent) -> None:
        pos = event.position() if hasattr(event, "position") else event.pos()
        x, y = int(pos.x()), int(pos.y())

        h, w = self._array.shape[0], self._array.shape[1]
        if not (0 <= x < w and 0 <= y < h):
            self.pixel_left.emit()
            return

        value = self._array[y, x]
        value_str = str(value.tolist() if hasattr(value, "tolist") else value)
        self.pixel_hovered.emit(x, y, value_str)
