# DatasetBench

A desktop workbench for processing and preparing image datasets used to
train models — or just for visualization. Built to replace a pile of
standalone scripts (thresholding, cropping, format conversion, etc.) with a
single interface: a sidebar for browsing datasets, tabs for open items, a
plugin system for processing operations, and a live preview with pixel
inspection.

## Why

Running the same preprocessing scripts over and over, rewriting the
path/image-loading boilerplate each time, gets old fast. DatasetBench keeps
that logic in one place and turns each processing step into a small,
independently runnable plugin you can drop in and out of the system.

## Core ideas

- **Single language.** Everything is Python — UI, dataset handling, and
  plugins — to keep the system simple and easy to extend.
- **Modular by design.** Every operation (cut, threshold, future ones) is
  a standalone plugin file. Plugins can also be copied out and run on their
  own, independent of the app.
- **Non-destructive by default.** Original datasets are never overwritten
  unless explicitly directed to via "Save As."

## Supported dataset structures

| Type | Structure |
|---|---|
| `SINGLE_IMAGE` | A single image file |
| `CLASSIFICATION` | `dataset_folder/class_x/.../image...` |
| `SEGMENTATION` | `dataset_folder/{img,mask}_folders/.../image...` |

## Supported formats

jpg, jpeg, png, tiff, fits (format conversion between them is planned, not
yet implemented).

## How it works (short version)

1. Open a file or folder — a `Dataset` object is created and a tab opens.
2. Click an image to load it into a temporary preview workspace.
3. Apply operations (starting with **Cut**) — each one updates the
   preview and appends to an ordered operation queue for that tab.
4. **Reset** reverts the preview to the original loaded image and clears
   the queue.
5. **Apply to Dataset** replays the full queue across every image in the
   dataset, writing results to the dataset's save location.
6. **Save As** sets/updates where results are written. Skipping Save As
   between operations chains them into one output dataset; using it
   between operations produces separate output datasets.

Full design details, data model, and plugin contract are documented in
[`software_design_document.md`](./software_design_document.md).

## Status

Early design/prototyping stage. Current focus: core app shell (PyQt),
dataset model, plugin loader, and a working `Cut` plugin end to end.
Thresholding and format conversion are planned next.

## Stack

- Python 3.x
- PyQt / PySide (UI)
- NumPy (image arrays, pixel access)
- Pillow / tifffile / astropy.io.fits (image I/O, format-dependent)
