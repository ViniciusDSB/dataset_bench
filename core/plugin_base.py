"""Plugin contract + auto-discovery.

Every processing operation (Cut, Threshold, future ones) is a standalone
file under plugins/, importable and runnable on its own, that implements
the `Plugin` interface below so DatasetBench can discover and call it
automatically.
"""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.dataset import DatasetType


@dataclass
class ProcessResult:
    output_path: Path
    # Small bag for anything a plugin wants to report back to the UI
    # (e.g. resulting shape) without changing the method signature later.
    info: dict[str, Any] | None = None


class Plugin(ABC):
    """Base class every plugin must subclass exactly once per file."""

    name: str
    applies_to: list[DatasetType]

    @abstractmethod
    def run(
        self,
        input_path: Path,
        output_path: Path,
        dataset_type: DatasetType,
    ) -> ProcessResult:
        """Read from input_path according to dataset_type, apply the
        operation, write the result to output_path.

        Used identically whether called once on a temp preview image or
        iterated by the dataset loader across a full dataset -- the plugin
        itself branches its reading/iteration logic on dataset_type, there
        is no external shared iterator dispatching on its behalf.

        If the plugin needs any parameters from the user, it asks for them
        itself via `datasetbenchlib.dialog` (write()/request()) at the top
        of this method, before branching on dataset_type -- DatasetBench
        replays those same answers automatically when this plugin gets
        applied across a whole dataset, so it's only ever prompted once.
        """
        raise NotImplementedError

    def supports(self, dataset_type: DatasetType) -> bool:
        return dataset_type in self.applies_to


class PluginRegistry:
    """Scans plugins/ on startup and registers any Plugin subclass found."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def discover(self, package_name: str = "plugins") -> None:
        package = importlib.import_module(package_name)
        for _, module_name, _ in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{package_name}.{module_name}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Plugin)
                    and attr is not Plugin
                ):
                    instance = attr()
                    self._plugins[instance.name] = instance

    def get(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    def all(self) -> list[Plugin]:
        return list(self._plugins.values())

    def for_dataset_type(self, dataset_type: DatasetType) -> list[Plugin]:
        return [p for p in self._plugins.values() if p.supports(dataset_type)]
