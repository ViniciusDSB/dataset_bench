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

Four ways of reading a dataset are supported:

| Value | Name | Structure |
|---|---|---|
| `0` | `SINGLE_IMAGE` | A single image file |
| `1` | `CLASSIFICATION` | `dataset_folder/class_x/.../image...` |
| `2` | `SEGMENTATION` | `dataset_folder/{img,mask}_folders/.../image...` |
| `3` | `FOLDER` | `dataset_folder/.../image...` — plain images, no class or img/mask convention |

```python
from enum import IntEnum

class DatasetType(IntEnum):
    SINGLE_IMAGE = 0
    CLASSIFICATION = 1
    SEGMENTATION = 2
    FOLDER = 3
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

**A plugin's `run()` receives:**
- `input_path` — where to read from
- `output_path` — where to write results to
- `dataset_type` — which of the four structures it's reading (the plugin
  branches its own iteration/reading logic internally based on this; there
  is no shared external iterator dispatching calls on the plugin's behalf)

```python
class Plugin(ABC):
    name: str
    applies_to: list[DatasetType]   # which dataset types this plugin supports

    @abstractmethod
    def run(self, input_path: Path, output_path: Path,
            dataset_type: DatasetType) -> ProcessResult:
        """Reads from input_path according to dataset_type, applies the
        operation, writes result to output_path. Used identically whether
        called on a single temp preview image or iterated across a full
        dataset."""
```

There is no static parameter schema on the class. If a plugin needs input
from the user, it asks for it itself, from *inside* `run()`, via
`datasetbenchlib.dialog` — a small host API the app injects a live session
into before calling `run()`. This means a plugin's dialogs can be however
simple or complex it needs (one field, ten fields, several dialogs in
sequence) without the app needing to know their shape ahead of time — new
plugins never require any UI code to be written elsewhere.

### 4.1 `datasetbenchlib.dialog` API

```python
from datasetbenchlib import dialog

dialog.write("Please enter the cut coordinates.")            # optional help text
values = dialog.request({"x_i": 0, "x_f": 100,                # one call, many fields
                          "y_i": 0, "y_f": 100})
x_i, x_f, y_i, y_f = values["x_i"], values["x_f"], values["y_i"], values["y_f"]
```

- **`write(text)`** queues a line of help text, shown above the fields in
  the *next* `request()` call. Can be called more than once to build up a
  short message; cleared after that `request()`.
- **`request(fields) -> dict`** shows one dialog with one input per
  `{name: default_value}` entry and blocks until submitted. The widget type
  is inferred from each default's Python type:

  | Default type | Widget |
  |---|---|
  | `bool` | checkbox |
  | `int` | spin box |
  | `float` | spin box (decimal) |
  | `list[(a, b), ...]` | dynamic range list (add/remove rows) |
  | anything else | text field |

  Raises `dialog.PluginCancelled` if the user cancels — plugins can just
  let that propagate; the app treats it as a clean abort, not an error.

**Convention:** call every `request()` a plugin needs *before* branching on
`dataset_type`, at the top of `run()`. This keeps the call count and order
identical on every invocation, which is what makes the replay mechanism
below possible.

### 4.2 Why "Apply to Dataset" doesn't re-prompt per file

`run()` gets called once per image when applying to a whole dataset —
without care, that would mean opening a dialog hundreds of times. Instead,
the app runs two kinds of session, via `dialog.start_session()` /
`dialog.end_session()`:

- **Interactive session** (single-image tab, one real invocation): each
  `request()` shows a real dialog and the answer gets *recorded*.
  `end_session()` returns everything recorded, in call order.
- **Replay session** (Apply to Dataset, once per file): `start_session(...,
  replay=<recorded list>)` means `request()` does **not** show a dialog —
  it just returns the next recorded answer in sequence.

The app stores the recorded list on the queued operation
(`QueuedOp.recorded_calls`) and on `dataset.metadata[plugin_name]`, so a
plugin is only ever prompted once per use, no matter how many files it
later gets applied to.

### 4.3 Standalone use

If a plugin is run directly (`python plugins/cut.py ...`) with no session
bound, `request()` falls back to a plain console prompt
(`x_i [0]: `), so plugins stay fully runnable outside the app.

### 4.4 Example (`plugins/cut.py`)

```python
class CutPlugin(Plugin):
    name = "Cut"
    applies_to = [DatasetType.SINGLE_IMAGE, DatasetType.CLASSIFICATION,
                  DatasetType.SEGMENTATION, DatasetType.FOLDER]

    def run(self, input_path, output_path, dataset_type):
        dialog.write("Please enter the cut coordinates.")
        values = dialog.request({"x_i": 0, "x_f": 100, "y_i": 0, "y_f": 100})
        x_i, x_f, y_i, y_f = values["x_i"], values["x_f"], values["y_i"], values["y_f"]

        # dataset_type branches folder-walking logic internally
        # e.g. crop = img[y_i:y_f, x_i:x_f]
        ...
        return ProcessResult(output_path=output_path)
```

The app scans `plugins/` on startup, registers any `Plugin` subclass found,
and enables/disables toolbar actions based on whether `applies_to` matches
the active tab's dataset type.

`core/dataset_io.py` provides shared read-helpers (`iter_single`,
`iter_images`, `iter_classification`, `iter_segmentation`) — plain
file-pairing generators with no processing logic — so plugins can reuse
folder-walking code instead of duplicating it per plugin.

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
2. Click "Cut" → the plugin's own `dialog.request()` call shows a dialog
   asking for `x_i, x_f, y_i, y_f`.
3. Plugin runs: reads `processed.tiff`, writes result back to
   `processed.tiff`. Preview updates.
4. The operation is appended to an in-memory **queue** for the tab, along
   with whatever the plugin's dialog session recorded:
   ```python
   queue = [QueuedOp(plugin_name="Cut",
                      recorded_calls=[{"x_i": 264, "x_f": 1720,
                                        "y_i": 264, "y_f": 1720}])]
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
   operations in order. For each queued op, the app starts a **replay
   session** (`dialog.start_session(..., replay=op.recorded_calls)`) so the
   plugin's `run()` executes exactly as it did interactively, without
   re-prompting — see §4.2.
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

- Threshold plugin logic — the queue/replay mechanism already accommodates
  it; the ranges themselves will come from `dialog.request({"ranges": [(0,
  None)]})`, which renders as an add/remove-able list of (low, high) rows
  (see §4.1).
- Format conversion between jpg/jpeg/png/tiff/fits (existing scripts to be
  integrated into `core/image_io.py` later).
- Persisting queues/state across app restarts.
