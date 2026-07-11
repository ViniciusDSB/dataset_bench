from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from core.dataset import Dataset, DatasetManager, DatasetType
from core.dataset_io import IMAGE_EXTENSIONS
from core.image_io import load_image, save_image
from core.plugin_base import PluginRegistry
from datasetbenchlib import dialog
from ui.preview_widget import ImagePreviewWidget
from ui.tab_state import PROJECT_TMP_DIR, QueuedOp, TabState

# Sidebar tree item data roles: which dataset an item belongs to, and the
# specific image file it points to. Group nodes (dataset root, class name,
# img/mask folders) carry no PATH_ROLE and are not directly openable.
UID_ROLE = Qt.UserRole
PATH_ROLE = Qt.UserRole + 1


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DatasetBench")
        self.resize(1200, 800)

        self._clear_stale_tmp_dirs()

        self.dataset_manager = DatasetManager()
        self.plugin_registry = PluginRegistry()
        self.plugin_registry.discover()

        self._tab_states: dict[int, TabState] = {}  # id(preview_widget) -> TabState

        self._build_sidebar()
        self._build_tabs()
        self._build_top_tabs()
        self._build_status_bar()

    @staticmethod
    def _clear_stale_tmp_dirs() -> None:
        """Every tab's temp workspace normally gets removed when its tab is
        closed (see _close_tab) or when the app closes normally (see
        closeEvent). If the app was killed/crashed instead, those folders
        are orphaned -- nothing in a fresh session can reference them
        anyway, so it's safe to sweep tmp/ clean on startup."""
        if not PROJECT_TMP_DIR.is_dir():
            return
        for child in PROJECT_TMP_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Clean up every still-open tab's temp workspace when the app
        closes, not just the ones explicitly closed via their tab's 'x'."""
        for state in list(self._tab_states.values()):
            state.cleanup()
        super().closeEvent(event)

    # --- UI construction ---------------------------------------------

    def _build_status_bar(self) -> None:
        """Action confirmations (Save, Apply to Dataset, errors...) use the
        status bar's normal message area, on the left, as before. Pixel
        coordinates/values and zoom get their own permanent label on the
        right, so hovering the image never wipes out a save confirmation."""
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        self._pixel_label = QLabel("")
        status_bar.addPermanentWidget(self._pixel_label)

    def _build_sidebar(self) -> None:
        self.sidebar = QTreeWidget()
        self.sidebar.setHeaderHidden(True)
        self.sidebar.setMaximumWidth(320)
        self.sidebar.itemClicked.connect(self._on_sidebar_item_clicked)
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

        file_actions = [
            ("Open", self._open_dialog),
            ("Close Folder", self._close_dataset),
            ("Save", self._save),
            ("Save As", self._save_as),
            ("Reset", self._reset_tab),
            ("Apply to Dataset", self._apply_to_dataset),
        ]
        for label, handler in file_actions:
            button = QToolButton()
            button.setText(label)
            button.setAutoRaise(True)
            button.clicked.connect(handler)
            layout.addWidget(button)

        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        zoom_actions = [
            ("Zoom In", self._zoom_in),
            ("Zoom Out", self._zoom_out),
            ("Reset Zoom", self._zoom_reset),
        ]
        for label, handler in zoom_actions:
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
        image_button = choice_box.addButton("Image", QMessageBox.AcceptRole)
        folder_button = choice_box.addButton("Folder", QMessageBox.AcceptRole)
        classification_button = choice_box.addButton(
            "Classification Dataset", QMessageBox.AcceptRole
        )
        segmentation_button = choice_box.addButton(
            "Segmentation Dataset", QMessageBox.AcceptRole
        )
        choice_box.addButton(QMessageBox.Cancel)
        choice_box.exec()

        clicked = choice_box.clickedButton()
        if clicked is image_button:
            path_str, _ = QFileDialog.getOpenFileName(self, "Open image")
            if not path_str:
                return
            self._open_path(Path(path_str), DatasetType.SINGLE_IMAGE)

        elif clicked is folder_button:
            path_str = QFileDialog.getExistingDirectory(self, "Open folder of images")
            if not path_str:
                return
            self._open_path(Path(path_str), DatasetType.FOLDER)

        elif clicked is classification_button:
            path_str = QFileDialog.getExistingDirectory(
                self, "Open classification dataset"
            )
            if not path_str:
                return
            self._open_path(Path(path_str), DatasetType.CLASSIFICATION)

        elif clicked is segmentation_button:
            path_str = QFileDialog.getExistingDirectory(
                self, "Open segmentation dataset"
            )
            if not path_str:
                return
            self._open_path(Path(path_str), DatasetType.SEGMENTATION)

        else:
            return  # Cancel: stop here, don't chain into another dialog

    def _open_path(self, path: Path, dataset_type: DatasetType) -> None:
        dataset = Dataset(path=path, type=dataset_type)
        self.dataset_manager.add(dataset)

        if dataset_type == DatasetType.SINGLE_IMAGE:
            item = QTreeWidgetItem([path.name])
            item.setData(0, UID_ROLE, dataset.uid)
            item.setData(0, PATH_ROLE, str(path))
            self.sidebar.addTopLevelItem(item)
            self._open_tab_for_image(dataset, path)
        else:
            root_item = QTreeWidgetItem([f"{path.name}  [{dataset_type.name}]"])
            root_item.setData(0, UID_ROLE, dataset.uid)  # no PATH_ROLE: not directly openable
            self.sidebar.addTopLevelItem(root_item)
            self._add_dir_children(root_item, path, dataset)
            root_item.setExpanded(True)
            self.statusBar().showMessage(
                f"Loaded {dataset_type.name} dataset at {path}", 5000
            )

    def _add_dir_children(
        self, parent_item: QTreeWidgetItem, dir_path: Path, dataset: Dataset
    ) -> None:
        """Mirrors the real filesystem structure as-is -- folders as group
        nodes, recognized image files as openable leaves -- regardless of
        whether the dataset is Classification or Segmentation. That
        distinction is only consulted by plugins, not by this tree."""
        for entry in sorted(dir_path.iterdir()):
            if entry.is_dir():
                child_item = QTreeWidgetItem([entry.name])
                parent_item.addChild(child_item)
                self._add_dir_children(child_item, entry, dataset)
            elif entry.suffix.lower() in IMAGE_EXTENSIONS:
                leaf = QTreeWidgetItem([entry.name])
                leaf.setData(0, UID_ROLE, dataset.uid)
                leaf.setData(0, PATH_ROLE, str(entry))
                parent_item.addChild(leaf)

    def _on_sidebar_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        uid = item.data(0, UID_ROLE)
        path_str = item.data(0, PATH_ROLE)
        if not uid or not path_str:
            return  # a group node (dataset root or plain folder), not a file

        dataset = self.dataset_manager.get(uid)
        if dataset is None:
            return
        self._open_tab_for_image(dataset, Path(path_str))

    def _close_dataset(self) -> None:
        item = self.sidebar.currentItem()
        if item is None:
            QMessageBox.information(
                self, "Close Folder", "Select a dataset in the sidebar first."
            )
            return

        # Walk up to the top-level (dataset root) item, in case a nested
        # folder/file within the dataset was selected instead of the root.
        while item.parent() is not None:
            item = item.parent()

        uid = item.data(0, UID_ROLE)
        if not uid:
            return
        dataset = self.dataset_manager.get(uid)

        # Close any open tabs backed by this dataset before dropping it.
        for i in reversed(range(self.tabs.count())):
            widget = self.tabs.widget(i)
            state = self._tab_states.get(id(widget))
            if state and state.dataset_uid == uid:
                self._close_tab(i)

        if dataset is not None:
            self.dataset_manager.remove(uid)

        index = self.sidebar.indexOfTopLevelItem(item)
        self.sidebar.takeTopLevelItem(index)
        self.statusBar().showMessage("Closed dataset", 3000)

    # --- Tabs -------------------------------------------------------------

    def _open_tab_for_image(self, dataset: Dataset, image_path: Path) -> None:
        existing_index = self._find_tab_index(dataset.uid, image_path)
        if existing_index is not None:
            self.tabs.setCurrentIndex(existing_index)
            return

        try:
            state = TabState.create(dataset_uid=dataset.uid, image_path=image_path)
            array = load_image(state.processed_path)
        except Exception as exc:
            QMessageBox.critical(
                self, "Open", f"Could not open {image_path.name}:\n{exc}"
            )
            return

        preview = ImagePreviewWidget()
        preview.set_array(array)

        preview.pixel_hovered.connect(
            lambda x, y, v: self._pixel_label.setText(f"({x}, {y}): {v}")
        )
        preview.pixel_left.connect(lambda: self._pixel_label.setText(""))
        preview.zoom_changed.connect(
            lambda z: self._pixel_label.setText(f"Zoom: {z:.0%}")
        )

        index = self.tabs.addTab(preview, image_path.name)
        self._tab_states[id(preview)] = state
        self.tabs.setCurrentIndex(index)

    def _find_tab_index(self, dataset_uid: str, image_path: Path) -> int | None:
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            state = self._tab_states.get(id(widget))
            if state and state.dataset_uid == dataset_uid and state.image_path == image_path:
                return i
        return None

    def _close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        state = self._tab_states.pop(id(widget), None)
        if state:
            state.cleanup()
        self.tabs.removeTab(index)

    def _current_state(self) -> TabState | None:
        widget = self.tabs.currentWidget()
        return self._tab_states.get(id(widget)) if widget is not None else None

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

        # Interactive session: the plugin's own dialog.write()/request()
        # calls (inside run()) show real dialogs here, and whatever the
        # user enters gets recorded for later replay in Apply to Dataset.
        dialog.start_session(self)
        succeeded = True
        try:
            plugin.run(
                input_path=state.processed_path,
                output_path=state.processed_path,
                dataset_type=DatasetType.SINGLE_IMAGE,
            )
        except dialog.PluginCancelled:
            succeeded = False
        except Exception as exc:
            QMessageBox.critical(self, plugin_name, f"'{plugin_name}' failed:\n{exc}")
            succeeded = False
        finally:
            recorded = dialog.end_session()

        if not succeeded:
            self.statusBar().showMessage(f"{plugin_name} cancelled", 3000)
            return

        state.queue.append(QueuedOp(plugin_name=plugin_name, recorded_calls=recorded))
        dataset.metadata[plugin_name] = recorded  # remembered for "apply to all"

        self._current_preview().set_array(load_image(state.processed_path))
        self.statusBar().showMessage(f"Applied {plugin_name}", 7000)

    def _reset_tab(self) -> None:
        state = self._current_state()
        if state is None:
            return
        state.reset()
        self._current_preview().set_array(load_image(state.processed_path))
        self.statusBar().showMessage("Reset to loaded image", 3000)

    def _zoom_in(self) -> None:
        preview = self._current_preview()
        if preview:
            preview.zoom_in()

    def _zoom_out(self) -> None:
        preview = self._current_preview()
        if preview:
            preview.zoom_out()

    def _zoom_reset(self) -> None:
        preview = self._current_preview()
        if preview:
            preview.reset_zoom()

    # --- Save / Save As / Apply to Dataset --------------------------------

    def _save_as(self) -> None:
        """Only sets/updates WHERE things get written. Does not write."""
        state = self._current_state()
        if state is None:
            QMessageBox.information(self, "Save As", "Open an image first.")
            return
        dataset = self.dataset_manager.get(state.dataset_uid)
        self._prompt_save_location(dataset)

    def _prompt_save_location(self, dataset: Dataset) -> bool:
        """Opens the folder picker and sets dataset.save_path. Returns False
        if the user cancelled, so callers can abort instead of proceeding
        with an unconfirmed location."""
        path_str = QFileDialog.getExistingDirectory(self, "Choose save location")
        if not path_str:
            return False
        dataset.save_path = Path(path_str)
        self.statusBar().showMessage(f"Save location set to {path_str}", 5000)
        return True

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

        self.statusBar().showMessage("Processing...")
        QApplication.processEvents()  # force the message to paint before the blocking save

        save_image(output_path, load_image(state.processed_path))
        dataset.path = output_path  # chain further ops onto the saved result
        self.statusBar().showMessage(f"Saved to {output_path}", 7000)

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

        if dataset.save_path is None:
            if not self._prompt_save_location(dataset):
                return  # user cancelled -- don't apply with an unconfirmed location

        output_path = dataset.resolve_save_path()
        current_input = dataset.path

        self.statusBar().showMessage("Processing...")
        QApplication.processEvents()  # force the message to paint before the blocking loop

        try:
            for op in state.queue:
                plugin = self.plugin_registry.get(op.plugin_name)
                dialog.start_session(self, replay=op.recorded_calls)
                try:
                    plugin.run(
                        input_path=current_input,
                        output_path=output_path,
                        dataset_type=dataset.type,
                    )
                finally:
                    dialog.end_session()
                current_input = output_path  # chain subsequent ops onto the result
        except Exception as exc:
            QMessageBox.critical(
                self, "Apply to Dataset", f"Failed while applying '{op.plugin_name}':\n{exc}"
            )
            return

        dataset.path = output_path
        self.statusBar().showMessage(f"Applied to dataset -> {output_path}", 7000)
