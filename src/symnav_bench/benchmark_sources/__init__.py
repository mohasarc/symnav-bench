from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from symnav_bench.study import BenchmarkSelection
from symnav_bench.suite import SuiteManifest


class BenchmarkTaskSource(ABC):
    def __init__(self, selection: BenchmarkSelection) -> None:
        self.selection = selection

    @abstractmethod
    def resolve(self) -> SuiteManifest: ...

    @abstractmethod
    def ensure_tasks_dir(self, slugs: Sequence[str], workdir: Path) -> Path: ...
