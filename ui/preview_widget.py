"""Image preview widget: displays a numpy array and reports (x, y): value
under the mouse cursor, the same way matplotlib does when you hover over
an imshow plot. Supports zooming (buttons or Ctrl+wheel) without breaking
that coordinate mapping or the window-sizing fix from the scroll area."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QWheelEvent
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
    mouse moves over it, pixel_left() when the mouse leaves the image, and
    zoom_changed(factor) whenever the zoom level changes."""

    pixel_hovered = Signal(int, int, str)
    pixel_left = Signal()
    zoom_changed = Signal(float)

    ZOOM_STEP = 1.25
    MIN_ZOOM = 0.1
    MAX_ZOOM = 8.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._array: np.ndarray | None = None
        self._base_pixmap: QPixmap | None = None  # native resolution, never scaled
        self._zoom: float = 1.0

        self._label = QLabel("No image loaded")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setMouseTracking(True)
        self._label.installEventFilter(self)
        self.setMouseTracking(True)

        # Scroll area keeps the label at its true (possibly zoomed) pixel
        # size without forcing this widget -- and therefore the whole
        # window -- to grow to the image's dimensions. Small/zoomed-out
        # images stay centered; large/zoomed-in images get scrollbars.
        scroll_area = QScrollArea()
        scroll_area.setWidget(self._label)
        scroll_area.setWidgetResizable(False)
        scroll_area.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area)
        layout.setContentsMargins(0, 0, 0, 0)

    # --- image loading ----------------------------------------------

    def set_array(self, array: np.ndarray) -> None:
        self._array = array
        self._base_pixmap = array_to_qpixmap(array)
        self._zoom = 1.0
        self._refresh_pixmap()

    def array(self) -> np.ndarray | None:
        return self._array

    # --- zoom ---------------------------------------------------------

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom * self.ZOOM_STEP)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom / self.ZOOM_STEP)

    def reset_zoom(self) -> None:
        self._set_zoom(1.0)

    def zoom(self) -> float:
        return self._zoom

    def _set_zoom(self, value: float) -> None:
        if self._base_pixmap is None:
            return
        clamped = max(self.MIN_ZOOM, min(self.MAX_ZOOM, value))
        if clamped == self._zoom:
            return
        self._zoom = clamped
        self._refresh_pixmap()
        self.zoom_changed.emit(self._zoom)

    def _refresh_pixmap(self) -> None:
        if self._base_pixmap is None:
            return
        w = max(1, round(self._base_pixmap.width() * self._zoom))
        h = max(1, round(self._base_pixmap.height() * self._zoom))
        scaled = self._base_pixmap.scaled(
            w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._label.setPixmap(scaled)
        self._label.resize(scaled.size())

    # --- mouse tracking / zoom shortcut --------------------------------

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        if obj is self._label and self._array is not None:
            if event.type() == QMouseEvent.MouseMove:
                self._handle_mouse_move(event)
            elif event.type() == QMouseEvent.Leave:
                self.pixel_left.emit()
            elif event.type() == QEvent.Wheel and (event.modifiers() & Qt.ControlModifier):
                self._handle_wheel_zoom(event)
                return True  # consumed: don't let the scroll area also scroll
        return super().eventFilter(obj, event)

    def _handle_wheel_zoom(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def _handle_mouse_move(self, event: QMouseEvent) -> None:
        pos = event.position() if hasattr(event, "position") else event.pos()
        # Displayed pixmap is scaled by self._zoom; divide back down to get
        # the coordinate in the original, unscaled array.
        x = int(pos.x() / self._zoom)
        y = int(pos.y() / self._zoom)

        h, w = self._array.shape[0], self._array.shape[1]
        if not (0 <= x < w and 0 <= y < h):
            self.pixel_left.emit()
            return

        value = self._array[y, x]
        value_str = str(value.tolist() if hasattr(value, "tolist") else value)
        self.pixel_hovered.emit(x, y, value_str)
