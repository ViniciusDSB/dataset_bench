# Dataset Processing System — Software Design Document

## 1. Introduction

This is a system to help process and modify image datasets used for training
models, or simply for visualization. It replaces a collection of standalone
scripts (thresholding, cropping, format conversion, etc.) with a single
VS Code–style desktop application: a sidebar for browsing datasets, tabs for
open items, a plugin system for processing operations, and a preview panel
with live pixel inspection.

The system is designed around three principles:

- **Single language.** Everything is Python, to minimize maintenance surface
  and keep existing scripts reusable with light adaptation.
- **Modularity.** Every processing operation (cut, threshold, future ops) is
  a self-contained plugin file. Plugins are independently runnable and
  independently droppable into the system — no core code changes needed to
  add a new one.
- **Non-destructive by default.** The system never overwrites an original
  dataset unless the user explicitly directs it to.

---

## 2. Dependencies

| Dependency | Purpose |
|---|---|
| Python 3.x | Single implementation language |
| PyQt or PySide (Qt for Python) | Desktop UI: docked sidebar, tabbed workspace, menus/toolbar, image preview widget |
| NumPy | In-memory image representation, pixel access |
| Pillow / tifffile / astropy (`astropy.io.fits`) | Image I/O across formats (jpg, jpeg, png, tiff, fits) |
| `dataclasses` (stdlib) | `Dataset` object definition |
| `uuid` (stdlib) | Unique dataset/tab identifiers |
| `pathlib` (stdlib) | Path handling |
| `importlib`, `pkgutil` (stdlib) | Plugin auto-discovery |
| `json` (stdlib, optional) | Persisting the per-tab operation queue if needed across sessions |

Format conversion logic (jpg/png/tiff/fits interconversion) is deferred —
covered by existing scripts to be integrated later. `core/image_io.py` will
expose a stable `load_image(path)` / `save_image(path, data)` interface now,
with format-specific logic filled in later without changing plugin code.

---

## 3. Data Model

### 3.1 Dataset Types (constants)

Three ways of reading a dataset are supported:

| Value | Name | Structure |
|---|---|---|
| `0` | `SINGLE_IMAGE` | A single image file |
| `1` | `CLASSIFICATION` | `dataset_folder/class_x/.../image...` |
| `2` | `SEGMENTATION` | `dataset_folder/{img,mask}_folders/.../image...` |

```python
from enum import IntEnum

class DatasetType(IntEnum):
    SINGLE_IMAGE = 0
    CLASSIFICATION = 1
    SEGMENTATION = 2
```

### 3.2 `Dataset` object

Represents one opened file or folder. Datasets are stored in a
`dict[str, Dataset]` keyed by `uid` (not list position — avoids id
invalidation on delete/reorder).

```python
@dataclass
class Dataset:
    path: Path              # current READ location; updates to save_path after each save
    save_path: Path | None  # current WRITE location; None until first "Save As"
    type: DatasetType
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict = field(default_factory=dict)  # cached info + per-plugin remembered params
```

- **`path`** always points to where the system currently reads from. It is
  reassigned to `save_path` after a successful save, so subsequent
  operations chain onto the latest result.
- **`save_path`** starts as `None`. If a save happens before the user has
  explicitly chosen a location, the system defaults to a sibling folder next
  to the original (e.g. `dataset_x/` → `dataset_x_processed/`), so the
  original is never silently overwritten.
- **Save is always "Save As."** There is no plain "Save." Clicking Save As
  lets the user set/confirm `save_path`. Whether two operations land in the
  same output dataset or two separate ones depends entirely on whether Save
  As was clicked between them:
  - Cut → (no Save As) → Threshold → **one** dataset with both applied.
  - Cut → Save As → Threshold → **two** datasets, one with each operation.
- **`metadata`** holds cached dataset info (shape, file listing, etc.) and
  per-plugin remembered parameters, e.g. `metadata["Cut"] = {"x_i": 264,
  "x_f": 1720, "y_i": 264, "y_f": 1720}`, used when reapplying the same
  operation across the whole dataset.

---

## 4. Plugin Contract

Each plugin is a standalone Python file under `plugins/`, importable and
runnable on its own (so it can also be copied out and used independently of
the system), and implements a common interface so the app can discover it
automatically.

**A plugin receives:**
- `input_path` — where to read from
- `output_path` — where to write results to
- `dataset_type` — which of the three structures it's reading (the plugin
  branches its own iteration/reading logic internally based on this; there
  is no shared external iterator dispatching calls on the plugin's behalf)
- `**params` — operation-specific parameters (for `Cut`: `x_i, x_f, y_i,
  y_f`)

```python
class Plugin(ABC):
    name: str
    applies_to: list[DatasetType]   # which dataset types this plugin supports

    @abstractmethod
    def run(self, input_path: Path, output_path: Path,
            dataset_type: DatasetType, **params) -> ProcessResult:
        """Reads from input_path according to dataset_type, applies the
        operation, writes result to output_path. Used identically whether
        called on a single temp preview image or iterated across a full
        dataset."""

    def parameters(self) -> dict:
        """Describes the inputs the UI should render for this plugin,
        e.g. {"x_i": ("int", 0), "x_f": ("int", 0), ...}"""
```

Example (`plugins/cut.py`):

```python
class CutPlugin(Plugin):
    name = "Cut"
    applies_to = [DatasetType.SINGLE_IMAGE, DatasetType.CLASSIFICATION,
                  DatasetType.SEGMENTATION]

    def run(self, input_path, output_path, dataset_type, x_i, x_f, y_i, y_f):
        # dataset_type branches folder-walking logic internally
        # e.g. crop = img[y_i:y_f, x_i:x_f]
        ...
        return ProcessResult(output_path=output_path)
```

The app scans `plugins/` on startup, registers any `Plugin` subclass found,
and enables/disables toolbar actions based on whether `applies_to` matches
the active tab's dataset type.

`core/dataset_io.py` provides shared read-helpers (`iter_single`,
`iter_classification`, `iter_segmentation`) — plain file-pairing generators
with no processing logic — so plugins can reuse folder-walking code instead
of duplicating it per plugin.

---

## 5. Workflows

### 5.1 Opening a dataset

1. User clicks Open (file or folder).
2. System initializes a `Dataset` object (`path`, inferred/selected `type`,
   `save_path = None`, fresh `uid`), stores it in the datasets dict.
3. A new tab opens showing the path; sidebar updates to reflect it.
4. Toolbar options become available based on `dataset.type`
   (`applies_to` filtering).

### 5.2 Single-image preview and processing (prototype scope: Cut only)

Each open tab has its own temp workspace:

```
tmp/<tab_id>/loaded.tiff       # immutable copy, this session's "original"
tmp/<tab_id>/processed.tiff    # current working result
```

Flow:

1. Click an image in the sidebar → copied to `tmp/<tab_id>/loaded.tiff`,
   also copied to `processed.tiff` initially, and displayed.
2. Click "Cut" → user enters `x_i, x_f, y_i, y_f`.
3. Plugin runs: reads `processed.tiff`, writes result back to
   `processed.tiff`. Preview updates.
4. The operation is appended to an in-memory **queue** for the tab:
   ```python
   queue = [{"op": "cut", "params": {"x_i": 264, "x_f": 1720,
                                      "y_i": 264, "y_f": 1720}}]
   ```
5. Further operations continue reading/writing `processed.tiff` and append
   to the same queue, in order.
6. **Reset button** — clears the queue, copies `loaded.tiff` back over
   `processed.tiff`, preview reverts to original. The next operation then
   starts a fresh queue from the clean state.

### 5.3 Preview pixel inspection

The preview widget holds the current image as a NumPy array. On mouse move,
widget coordinates are mapped to array indices (accounting for any
zoom/scale factor), and `array[y, x]` is read directly from the same array
driving the display, updating a status readout of `(x, y): value` — no
extra file I/O involved.

### 5.4 Apply to dataset

1. User clicks **"Apply to Dataset."**
2. System takes `dataset.type` and the tab's operation queue.
3. Compatibility check: every queued op's `applies_to` must include
   `dataset.type`; if not, abort with an error before touching any files.
4. System resolves the output location: `dataset.save_path` if already set
   via Save As, otherwise the default sibling folder next to `dataset.path`.
5. Using the appropriate loader for `dataset.type`
   (`SingleImageLoader` / `ClassificationLoader` / `SegmentationLoader`),
   every image in the dataset is processed by replaying the queue's
   operations in order, via each operation's plugin `run()`.
6. Original dataset files are left untouched; the existing dataset folder
   structure (classes/img-mask pairing) is preserved in the output.
7. After a successful write, `dataset.path` is updated to point at the
   output location, so subsequent operations chain onto this result.

### 5.5 Save As

1. User clicks **Save As**, chooses/confirms a location.
2. `dataset.save_path` is set to that location.
3. Subsequent "Apply to Dataset" calls write there. If the user clicks
   Save As again before the next apply, a new `save_path` is set, and the
   next apply produces a separate dataset rather than chaining onto the
   previous output.

---

## 6. Deferred / Out of Scope (for now)

- Threshold plugin logic (queue/data structure already accommodates it —
  `{"op": "threshold", "params": {...}}` — implementation to follow later).
- Format conversion between jpg/jpeg/png/tiff/fits (existing scripts to be
  integrated into `core/image_io.py` later).
- Persisting queues/state across app restarts.
