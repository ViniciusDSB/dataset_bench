"""Core data model: DatasetType constants and the Dataset object."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


class DatasetType(IntEnum):
    """The three ways DatasetBench knows how to read a dataset."""

    SINGLE_IMAGE = 0     # a single image file
    CLASSIFICATION = 1   # dataset_folder/class_x/.../image...
    SEGMENTATION = 2     # dataset_folder/{img,mask}_folders/.../image...


@dataclass
class Dataset:
    """Represents one opened file or folder.

    `path` always points to where the system currently READS from.
    `save_path` is where results are currently WRITTEN to; it stays None
    until the user explicitly does a "Save As". After a successful save,
    `path` is updated to `save_path` so later operations chain onto the
    latest result instead of the original.
    """

    path: Path
    type: DatasetType
    save_path: Path | None = None
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    # Cached dataset info (e.g. file listing) + per-plugin remembered
    # params, keyed by plugin name, e.g. metadata["Cut"] = {"x_i": 264, ...}
    metadata: dict = field(default_factory=dict)
    # Captured once, never mutated. default_save_path() is always derived
    # from this, not from `path` -- otherwise saving twice in a row would
    # append "_processed" onto an already-"_processed" name each time.
    original_path: Path = field(init=False, default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.original_path is None:
            self.original_path = self.path

    def default_save_path(self) -> Path:
        """Sibling location next to the original, used whenever the user
        saves without ever clicking Save As. A single image gets a sibling
        FILE (keeps the extension); a folder dataset gets a sibling FOLDER.
        Always derived from the original path, so repeated saves resolve
        to the same location and overwrite rather than stacking suffixes."""
        base = self.original_path
        if self.type == DatasetType.SINGLE_IMAGE:
            return base.parent / f"{base.stem}_processed{base.suffix}"
        return base.parent / f"{base.stem}_processed"

    def resolve_save_path(self) -> Path:
        if self.save_path is None:
            return self.default_save_path()

        if self.type == DatasetType.SINGLE_IMAGE:
            # save_path is a folder chosen via Save As; the caller appends
            # the filename itself.
            return self.save_path

        # Folder dataset: save_path is a parent location the user picked
        # (e.g. Downloads). Nest a subfolder named after the original
        # dataset inside it, so class/img-mask structure doesn't get
        # dumped directly into that folder.
        return self.save_path / f"{self.original_path.name}_processed"


class DatasetManager:
    """Single source of truth for all open datasets, keyed by uid so
    deleting/reordering never invalidates other references (unlike using
    array position as an id)."""

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}

    def add(self, dataset: Dataset) -> Dataset:
        self._datasets[dataset.uid] = dataset
        return dataset

    def get(self, uid: str) -> Dataset | None:
        return self._datasets.get(uid)

    def remove(self, uid: str) -> None:
        self._datasets.pop(uid, None)

    def all(self) -> list[Dataset]:
        return list(self._datasets.values())
