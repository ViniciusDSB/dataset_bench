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

IMG_DIR_ALIASES = {"img", "imgs", "image", "images"}
MASK_DIR_ALIASES = {"mask", "masks"}

def iter_segmentation(root: Path, img_dirname: str | None = None, mask_dirname: str | None = None):
    img_dirs = [
        d for d in sorted(root.rglob("*"))
        if d.is_dir() and d.name.lower() in IMG_DIR_ALIASES
    ]
    if not img_dirs:
        raise FileNotFoundError(f"No image folder (img/imgs/images) found under: {root}")

    for img_dir in img_dirs:
        mask_dir = next(
            (d for d in img_dir.parent.iterdir()
             if d.is_dir() and d.name.lower() in MASK_DIR_ALIASES),
            None,
        )
        mask_by_stem = {}
        if mask_dir is not None:
            for mask_path in mask_dir.rglob("*"):
                if _is_image(mask_path):
                    mask_by_stem[mask_path.stem] = mask_path

        for img_path in sorted(img_dir.rglob("*")):
            if _is_image(img_path):
                yield img_path, mask_by_stem.get(img_path.stem)
