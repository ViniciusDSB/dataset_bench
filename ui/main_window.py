from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSlider,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from core.dataset import Dataset, DatasetManager, DatasetType
from core.image_io import load_image, save_image
from core.plugin_base import Plugin, PluginRegistry
from ui.preview_widget import ImagePreviewWidget
from ui.tab_state import QueuedOp, TabState


class ParamsDialog(QDialog):
    """Generic parameter form, built from a plugin's parameters() dict.
    Any new plugin gets a working dialog for free, no UI code needed.

    Expected parameters() shapes:
      {"name": ("int", default)}
      {"name": ("float", default)}
      {"name": ("slider", min, max, default)}
      {"name": ("str", default)}   # fallback for anything else
    """

    def __init__(self, plugin: Plugin, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(plugin.name)
        self._fields: dict[str, QWidget] = {}

        layout = QFormLayout(self)
        for pname, spec in plugin.parameters().items():
            ptype = spec[0]
            if ptype == "int":
                default = spec[1] if len(spec) > 1 else 0
                widget = QSpinBox()
                widget.setRange(-1_000_000, 1_000_000)
                widget.setValue(default)
            elif ptype == "float":
                default = spec[1] if len(spec) > 1 else 0.0
                widget = QDoubleSpinBox()
                widget.setRange(-1_000_000.0, 1_000_000.0)
                widget.setValue(default)
            elif ptype == "slider":
                lo, hi, default = spec[1], spec[2], spec[3]
                widget = QSlider(Qt.Horizontal)
                widget.setRange(lo, hi)
                widget.setValue(default)
            else:
                default = spec[1] if len(spec) > 1 else ""
                widget = QLineEdit(str(default))

            self._fields[pname] = widget
            layout.addRow(pname, widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def params(self) -> dict:
        result = {}
        for name, widget in self._fields.items():
            if isinstance(widget, (QSpinBox, QSlider, QDoubleSpinBox)):
                result[name] = widget.value()
            elif isinstance(widget, QLineEdit):
                result[name] = widget.text()
        return result


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DatasetBench")
        self.resize(1200, 800)

        self.dataset_manager = DatasetManager()
        self.plugin_registry = PluginRegistry()
        self.plugin_registry.discover()

        self._tab_states: dict[int, TabState] = {}  # tab index -> TabState

        self._build_sidebar()
        self._build_tabs()
        self._build_top_tabs()
        self.setStatusBar(QStatusBar())

    # --- UI construction ---------------------------------------------

    def _build_sidebar(self) -> None:
        self.sidebar = QListWidget()
        self.sidebar.setMaximumWidth(280)
        dock = QDockWidget("Datasets", self)
        dock.setWidget(self.sidebar)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.setCentralWidget(self.tabs)

    def _build_top_tabs(self) -> None:
        """Two tabs at the top: 'Default' (Open/Save/Reset/Apply) and
        'Plugins' (one button per discovered plugin, generated automatically
        -- drop a new file in plugins/ and it shows up here, no UI changes
        needed)."""
        self.top_tabs = QTabWidget()
        self.top_tabs.setMaximumHeight(60)

        self.top_tabs.addTab(self._build_default_tab(), "Default")

        self.plugins_tab = QWidget()
        self.plugins_layout = QHBoxLayout(self.plugins_tab)
        self.plugins_layout.setContentsMargins(6, 4, 6, 4)
        self._populate_plugins_tab()
        self.top_tabs.addTab(self.plugins_tab, "Plugins")

        toolbar = QToolBar("Top")
        toolbar.setMovable(False)
        toolbar.addWidget(self.top_tabs)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

    def _build_default_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(6, 4, 6, 4)

        actions = [
            ("Open", self._open_dialog),
            ("Save", self._save),
            ("Save As", self._save_as),
            ("Reset", self._reset_tab),
            ("Apply to Dataset", self._apply_to_dataset),
        ]
        for label, handler in actions:
            button = QToolButton()
            button.setText(label)
            button.setAutoRaise(True)
            button.clicked.connect(handler)
            layout.addWidget(button)
        layout.addStretch()
        return tab

    def _populate_plugins_tab(self) -> None:
        for plugin in self.plugin_registry.all():
            button = QToolButton()
            button.setText(plugin.name)
            button.setAutoRaise(True)
            button.clicked.connect(
                lambda checked=False, name=plugin.name: self._run_plugin(name)
            )
            self.plugins_layout.addWidget(button)
        self.plugins_layout.addStretch()

    # --- Open flow ------------------------------------------------------

    def _open_dialog(self) -> None:
        choice_box = QMessageBox(self)
        choice_box.setWindowTitle("Open")
        choice_box.setText("What would you like to open?")
        file_button = choice_box.addButton("File", QMessageBox.AcceptRole)
        folder_button = choice_box.addButton("Folder", QMessageBox.AcceptRole)
        choice_box.addButton(QMessageBox.Cancel)
        choice_box.exec()

        clicked = choice_box.clickedButton()
        if clicked is file_button:
            path_str, _ = QFileDialog.getOpenFileName(self, "Open image")
        elif clicked is folder_button:
            path_str = QFileDialog.getExistingDirectory(self, "Open dataset folder")
        else:
            return  # Cancel: stop here, don't chain into another dialog

        if not path_str:
            return  # user cancelled the file/folder picker itself
        self._open_path(Path(path_str))

    def _open_path(self, path: Path) -> None:
        dataset_type = self._infer_dataset_type(path)
        dataset = Dataset(path=path, type=dataset_type)
        self.dataset_manager.add(dataset)

        item = QListWidgetItem(f"{path.name}  [{dataset_type.name}]")
        item.setData(1000, dataset.uid)
        self.sidebar.addItem(item)

        if dataset_type == DatasetType.SINGLE_IMAGE:
            self._open_tab_for_image(dataset, path)
        else:
            # For folder datasets, opening just registers it; user picks an
            # image from within it later (sidebar expansion is a follow-up).
            self.statusBar().showMessage(
                f"Loaded {dataset_type.name} dataset at {path}", 5000
            )

    @staticmethod
    def _infer_dataset_type(path: Path) -> DatasetType:
        if path.is_file():
            return DatasetType.SINGLE_IMAGE
        if (path / "img").is_dir() or (path / "mask").is_dir():
            return DatasetType.SEGMENTATION
        return DatasetType.CLASSIFICATION

    # --- Tabs -------------------------------------------------------------

    def _open_tab_for_image(self, dataset: Dataset, image_path: Path) -> None:
        state = TabState.create(dataset_uid=dataset.uid, image_path=image_path)
        preview = ImagePreviewWidget()
        preview.set_array(load_image(state.processed_path))

        preview.pixel_hovered.connect(
            lambda x, y, v: self.statusBar().showMessage(f"({x}, {y}): {v}")
        )
        preview.pixel_left.connect(self.statusBar().clearMessage)

        index = self.tabs.addTab(preview, image_path.name)
        self._tab_states[index] = state
        self.tabs.setCurrentIndex(index)

    def _close_tab(self, index: int) -> None:
        state = self._tab_states.pop(index, None)
        if state:
            state.cleanup()
        self.tabs.removeTab(index)

    def _current_state(self) -> TabState | None:
        return self._tab_states.get(self.tabs.currentIndex())

    def _current_preview(self) -> ImagePreviewWidget | None:
        return self.tabs.currentWidget()

    # --- Plugins (Cut, and any future plugin) ---------------------------

    def _run_plugin(self, plugin_name: str) -> None:
        state = self._current_state()
        if state is None:
            QMessageBox.information(self, plugin_name, "Open an image first.")
            return

        plugin = self.plugin_registry.get(plugin_name)
        dataset = self.dataset_manager.get(state.dataset_uid)
        if not plugin.supports(dataset.type):
            QMessageBox.warning(
                self,
                plugin_name,
                f"'{plugin_name}' does not support {dataset.type.name} datasets.",
            )
            return

        param_spec = plugin.parameters()
        if param_spec:
            dialog = ParamsDialog(plugin, self)
            if dialog.exec() != QDialog.Accepted:
                return
            params = dialog.params()
        else:
            params = {}

        plugin.run(
            input_path=state.processed_path,
            output_path=state.processed_path,
            dataset_type=DatasetType.SINGLE_IMAGE,
            **params,
        )
        state.queue.append(QueuedOp(plugin_name=plugin_name, params=params))
        dataset.metadata[plugin_name] = params  # remembered for "apply to all"

        self._current_preview().set_array(load_image(state.processed_path))
        self.statusBar().showMessage(f"Applied {plugin_name}: {params}", 5000)

    def _reset_tab(self) -> None:
        state = self._current_state()
        if state is None:
            return
        state.reset()
        self._current_preview().set_array(load_image(state.processed_path))
        self.statusBar().showMessage("Reset to loaded image", 3000)

    # --- Save / Save As / Apply to Dataset --------------------------------

    def _save_as(self) -> None:
        """Only sets/updates WHERE things get written. Does not write."""
        state = self._current_state()
        if state is None:
            QMessageBox.information(self, "Save As", "Open an image first.")
            return
        dataset = self.dataset_manager.get(state.dataset_uid)

        path_str = QFileDialog.getExistingDirectory(self, "Choose save location")
        if not path_str:
            return
        dataset.save_path = Path(path_str)
        self.statusBar().showMessage(f"Save location set to {path_str}", 5000)

    def _save(self) -> None:
        """Writes the current tab's processed image to the resolved save
        location (whatever Save As set, or the default sibling file if it
        was never clicked)."""
        state = self._current_state()
        if state is None:
            QMessageBox.information(self, "Save", "Open an image first.")
            return
        dataset = self.dataset_manager.get(state.dataset_uid)

        output_path = dataset.resolve_save_path()
        if output_path.suffix == "":
            # save_path was set via the folder picker in Save As; keep the
            # original filename inside it.
            output_path = output_path / state.image_path.name

        save_image(output_path, load_image(state.processed_path))
        dataset.path = output_path  # chain further ops onto the saved result
        self.statusBar().showMessage(f"Saved to {output_path}", 5000)

    def _apply_to_dataset(self) -> None:
        state = self._current_state()
        if state is None:
            QMessageBox.information(self, "Apply to Dataset", "Open a dataset first.")
            return
        dataset = self.dataset_manager.get(state.dataset_uid)

        if not state.queue:
            QMessageBox.information(
                self, "Apply to Dataset", "No operations queued for this tab."
            )
            return

        # Compatibility check before touching any files.
        for op in state.queue:
            plugin = self.plugin_registry.get(op.plugin_name)
            if not plugin.supports(dataset.type):
                QMessageBox.warning(
                    self,
                    "Apply to Dataset",
                    f"'{op.plugin_name}' does not support {dataset.type.name} "
                    "datasets. Aborted before writing anything.",
                )
                return

        output_path = dataset.resolve_save_path()
        current_input = dataset.path
        for op in state.queue:
            plugin = self.plugin_registry.get(op.plugin_name)
            plugin.run(
                input_path=current_input,
                output_path=output_path,
                dataset_type=dataset.type,
                **op.params,
            )
            current_input = output_path  # chain subsequent ops onto the result

        dataset.path = output_path
        self.statusBar().showMessage(f"Applied to dataset -> {output_path}", 5000)
