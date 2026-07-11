"""Cut plugin: crops an image to [y_i:y_f, x_i:x_f].

Standalone and runnable on its own — this file has no dependency on the
rest of the app beyond `core` and `datasetbenchlib` (whose dialog.request()
falls back to console prompts outside the app), so it can be copied out
and reused independently if needed.
"""

from __future__ import annotations

from pathlib import Path

from core.dataset import DatasetType
from core.dataset_io import iter_classification, iter_images, iter_segmentation
from core.image_io import load_image, save_image
from core.plugin_base import Plugin, ProcessResult
from datasetbenchlib import dialog


class CutPlugin(Plugin):
    name = "Cut"
    applies_to = [
        DatasetType.SINGLE_IMAGE,
        DatasetType.CLASSIFICATION,
        DatasetType.SEGMENTATION,
        DatasetType.FOLDER,
    ]

    def run(
        self,
        input_path: Path,
        output_path: Path,
        dataset_type: DatasetType,
    ) -> ProcessResult:
        # Ask for parameters up front, before branching on dataset_type --
        # this keeps the call count/order to dialog.request() identical on
        # every run(), which is what lets DatasetBench replay the same
        # answers across a whole dataset without re-prompting per file.
        dialog.write("Please enter the cut coordinates.")
        values = dialog.request({"x_i": 0, "x_f": 100, "y_i": 0, "y_f": 100})
        x_i, x_f, y_i, y_f = values["x_i"], values["x_f"], values["y_i"], values["y_f"]

        if dataset_type == DatasetType.SINGLE_IMAGE:
            self._cut_single(input_path, output_path, x_i, x_f, y_i, y_f)

        elif dataset_type == DatasetType.CLASSIFICATION:
            for img_path, _class_name in iter_classification(input_path):
                rel_path = img_path.relative_to(input_path)
                self._cut_single(img_path, output_path / rel_path, x_i, x_f, y_i, y_f)

        elif dataset_type == DatasetType.SEGMENTATION:
            for img_path, mask_path in iter_segmentation(input_path):
                rel_img = img_path.relative_to(input_path)
                self._cut_single(img_path, output_path / rel_img, x_i, x_f, y_i, y_f)
                if mask_path is not None:
                    rel_mask = mask_path.relative_to(input_path)
                    self._cut_single(mask_path, output_path / rel_mask, x_i, x_f, y_i, y_f)

        elif dataset_type == DatasetType.FOLDER:
            for img_path in iter_images(input_path):
                rel_path = img_path.relative_to(input_path)
                self._cut_single(img_path, output_path / rel_path, x_i, x_f, y_i, y_f)

        else:
            raise ValueError(f"Unsupported dataset_type: {dataset_type}")

        return ProcessResult(output_path=output_path)

    @staticmethod
    def _cut_single(
        src: Path, dst: Path, x_i: int, x_f: int, y_i: int, y_f: int
    ) -> None:
        img = load_image(src)
        cropped = img[y_i:y_f, x_i:x_f]
        if cropped.size == 0:
            raise ValueError(
                f"Cut range produces an empty image (x: {x_i}-{x_f}, "
                f"y: {y_i}-{y_f}). Make sure x_f > x_i and y_f > y_i."
            )
        save_image(dst, cropped)


if __name__ == "__main__":
    # Standalone usage example:
    #   python plugins/cut.py input.tiff output.tiff
    # (prompts for x_i/x_f/y_i/y_f on the console, since no app session
    # is bound -- see datasetbenchlib/dialog.py's console fallback)
    import sys

    plugin = CutPlugin()
    plugin.run(Path(sys.argv[1]), Path(sys.argv[2]), DatasetType.SINGLE_IMAGE)
    print(f"Saved cropped image to {sys.argv[2]}")
