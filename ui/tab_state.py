"""Per-tab state: temp workspace (loaded.tiff / processed.tiff) and the
ordered queue of operations applied so far in this session."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# Project's tmp/ folder (ui/tab_state.py -> project root -> tmp)
PROJECT_TMP_DIR = Path(__file__).resolve().parent.parent / "tmp"


@dataclass
class QueuedOp:
    plugin_name: str
    params: dict


@dataclass
class TabState:
    dataset_uid: str
    image_path: Path         # the specific image file this tab is previewing
    tmp_dir: Path
    queue: list[QueuedOp] = field(default_factory=list)

    @property
    def loaded_path(self) -> Path:
        return self.tmp_dir / f"loaded{self.image_path.suffix}"

    @property
    def processed_path(self) -> Path:
        return self.tmp_dir / f"processed{self.image_path.suffix}"

    @classmethod
    def create(cls, dataset_uid: str, image_path: Path) -> "TabState":
        tab_id = str(uuid.uuid4())[:8]
        tmp_dir = PROJECT_TMP_DIR / tab_id
        tmp_dir.mkdir(parents=True, exist_ok=True)

        state = cls(dataset_uid=dataset_uid, image_path=image_path, tmp_dir=tmp_dir)
        shutil.copy(image_path, state.loaded_path)
        shutil.copy(image_path, state.processed_path)
        return state

    def reset(self) -> None:
        """Revert processed.tiff to loaded.tiff and clear the queue."""
        shutil.copy(self.loaded_path, self.processed_path)
        self.queue.clear()

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
