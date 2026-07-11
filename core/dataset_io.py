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


def iter_images(root: Path) -> Iterator[Path]:
    """Every recognized image file under root, at any depth, regardless of
    any class/img/mask folder convention. Used for plain FOLDER datasets
    and by any plugin that doesn't care about dataset structure."""
    if root.is_file():
        if _is_image(root):
            yield root
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and _is_image(p):
            yield p


def iter_classification(root: Path) -> Iterator[tuple[Path, str]]:
    """dataset_folder/class_x/.../image...

    Yields (image_path, class_name) pairs.
    """
    class_dirs = [p for p in sorted(root.iterdir()) if p.is_dir()]
    if not class_dirs:
        raise FileNotFoundError(
            f"No class subfolders found under: {root}\n"
            "This looks like a flat folder of images -- open it as "
            "'Folder' instead of 'Classification Dataset'."
        )

    for class_dir in class_dirs:
        for img_path in sorted(class_dir.rglob("*")):
            if _is_image(img_path):
                yield img_path, class_dir.name


IMG_DIR_ALIASES = {"img", "imgs", "image", "images"}
MASK_DIR_ALIASES = {"mask", "masks"}


def iter_segmentation(root: Path) -> Iterator[tuple[Path, Path | None]]:
    """dataset_folder/.../{img,mask}/image...

    img/mask folder pairs are searched recursively (real datasets often
    nest them per-class: dataset_folder/class_x/{img,mask}/image...), and
    folder names are matched against common aliases (img/imgs/image/images,
    mask/masks) case-insensitively, not just the exact names "img"/"mask".

    Yields (image_path, mask_path_or_None) pairs, matched by filename stem,
    for every img/mask pair found anywhere under root.
    """
    img_dirs = [
        d for d in sorted(root.rglob("*"))
        if d.is_dir() and d.name.lower() in IMG_DIR_ALIASES
    ]
    if not img_dirs:
        aliases = "/".join(sorted(IMG_DIR_ALIASES))
        raise FileNotFoundError(
            f"No image folder ({aliases}) found anywhere under: {root}"
        )

    for img_dir in img_dirs:
        mask_dir = next(
            (
                d for d in img_dir.parent.iterdir()
                if d.is_dir() and d.name.lower() in MASK_DIR_ALIASES
            ),
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
