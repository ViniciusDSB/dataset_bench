"""Stable load/save interface, dispatching by file extension.

Format-specific logic (jpg/png via Pillow, tiff via tifffile, fits via
astropy, and conversion between them) is intentionally deferred — this
module gives plugins and the UI a fixed interface to call now, so nothing
downstream needs to change once the real per-format logic is filled in.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def load_image(path: Path) -> np.ndarray:
    """Load an image file into a numpy array, dispatching by extension."""
    suffix = path.suffix.lower()

    if suffix in (".jpg", ".jpeg", ".png"):
        return _load_with_pillow(path)
    elif suffix in (".tif", ".tiff"):
        return _load_with_tifffile(path)
    elif suffix == ".fits":
        return _load_with_astropy(path)
    else:
        raise ValueError(f"Unsupported image format: {suffix}")


def save_image(path: Path, data: np.ndarray) -> None:
    """Save a numpy array to disk, dispatching by extension."""
    suffix = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)

    if suffix in (".jpg", ".jpeg", ".png"):
        _save_with_pillow(path, data)
    elif suffix in (".tif", ".tiff"):
        _save_with_tifffile(path, data)
    elif suffix == ".fits":
        _save_with_astropy(path, data)
    else:
        raise ValueError(f"Unsupported image format: {suffix}")


# --- format-specific backends -------------------------------------------
# Filled in incrementally as existing scripts get adapted in.

def _load_with_pillow(path: Path) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as img:
        return np.array(img)


def _save_with_pillow(path: Path, data: np.ndarray) -> None:
    from PIL import Image

    Image.fromarray(data).save(path)


def _load_with_tifffile(path: Path) -> np.ndarray:
    import tifffile

    return tifffile.imread(path)


def _save_with_tifffile(path: Path, data: np.ndarray) -> None:
    import tifffile

    tifffile.imwrite(path, data)


def _load_with_astropy(path: Path) -> np.ndarray:
    from astropy.io import fits

    with fits.open(path) as hdul:
        return np.array(hdul[0].data)


def _save_with_astropy(path: Path, data: np.ndarray) -> None:
    from astropy.io import fits

    hdu = fits.PrimaryHDU(data)
    hdu.writeto(path, overwrite=True)
