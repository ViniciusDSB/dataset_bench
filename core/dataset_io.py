"""Read-helpers per dataset structure.

These are plain file-pairing generators, no processing logic. Plugins can
call into these to avoid reimplementing the same folder-walking pattern
three times each; using them is a convenience, not a requirement of the
Plugin contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".fits"}


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def iter_single(path: Path) -> Iterator[Path]:
    """A single image file."""
    if not _is_image(path):
        raise ValueError(f"Not a recognized image file: {path}")
    yield path


def iter_classification(root: Path) -> Iterator[tuple[Path, str]]:
    """dataset_folder/class_x/.../image...

    Yields (image_path, class_name) pairs.
    """
    for class_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for img_path in sorted(class_dir.rglob("*")):
            if _is_image(img_path):
                yield img_path, class_dir.name


def iter_segmentation(
    root: Path, img_dirname: str = "img", mask_dirname: str = "mask"
) -> Iterator[tuple[Path, Path | None]]:
    """dataset_folder/{img,mask}_folders/.../image...

    Yields (image_path, mask_path_or_None) pairs, matched by filename.
    """
    img_dir = root / img_dirname
    mask_dir = root / mask_dirname
    if not img_dir.is_dir():
        raise FileNotFoundError(f"Expected image folder not found: {img_dir}")

    mask_by_stem = {}
    if mask_dir.is_dir():
        for mask_path in mask_dir.rglob("*"):
            if _is_image(mask_path):
                mask_by_stem[mask_path.stem] = mask_path

    for img_path in sorted(img_dir.rglob("*")):
        if _is_image(img_path):
            yield img_path, mask_by_stem.get(img_path.stem)
