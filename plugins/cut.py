"""Cut plugin: crops an image to [y_i:y_f, x_i:x_f].

Standalone and runnable on its own — this file has no dependency on the
rest of the app beyond `core`, so it can be copied out and reused
independently if needed.
"""

from __future__ import annotations

from pathlib import Path

from core.dataset import DatasetType
from core.dataset_io import iter_classification, iter_segmentation, iter_single
from core.image_io import load_image, save_image
from core.plugin_base import Plugin, ProcessResult


class CutPlugin(Plugin):
    name = "Cut"
    applies_to = [
        DatasetType.SINGLE_IMAGE,
        DatasetType.CLASSIFICATION,
        DatasetType.SEGMENTATION,
    ]

    def parameters(self) -> dict[str, tuple]:
        return {
            "x_i": ("int", 0),
            "x_f": ("int", 0),
            "y_i": ("int", 0),
            "y_f": ("int", 0),
        }

    def run(
        self,
        input_path: Path,
        output_path: Path,
        dataset_type: DatasetType,
        x_i: int,
        x_f: int,
        y_i: int,
        y_f: int,
    ) -> ProcessResult:
        if dataset_type == DatasetType.SINGLE_IMAGE:
            self._cut_single(input_path, output_path, x_i, x_f, y_i, y_f)

        elif dataset_type == DatasetType.CLASSIFICATION:
            for img_path, class_name in iter_classification(input_path):
                rel_out = output_path / class_name / img_path.name
                self._cut_single(img_path, rel_out, x_i, x_f, y_i, y_f)

        elif dataset_type == DatasetType.SEGMENTATION:
            for img_path, mask_path in iter_segmentation(input_path):
                rel_out_img = output_path / "img" / img_path.name
                self._cut_single(img_path, rel_out_img, x_i, x_f, y_i, y_f)
                if mask_path is not None:
                    rel_out_mask = output_path / "mask" / mask_path.name
                    self._cut_single(mask_path, rel_out_mask, x_i, x_f, y_i, y_f)

        else:
            raise ValueError(f"Unsupported dataset_type: {dataset_type}")

        return ProcessResult(output_path=output_path)

    @staticmethod
    def _cut_single(
        src: Path, dst: Path, x_i: int, x_f: int, y_i: int, y_f: int
    ) -> None:
        img = load_image(src)
        cropped = img[y_i:y_f, x_i:x_f]
        save_image(dst, cropped)


if __name__ == "__main__":
    # Standalone usage example:
    #   python plugins/cut.py input.tiff output.tiff 264 1720 264 1720
    import sys

    plugin = CutPlugin()
    plugin.run(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        DatasetType.SINGLE_IMAGE,
        x_i=int(sys.argv[3]),
        x_f=int(sys.argv[4]),
        y_i=int(sys.argv[5]),
        y_f=int(sys.argv[6]),
    )
    print(f"Saved cropped image to {sys.argv[2]}")
