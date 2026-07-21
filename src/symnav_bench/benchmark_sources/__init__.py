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


def benchmark_task_source(
    selection: BenchmarkSelection, suite: SuiteManifest | None = None
) -> BenchmarkTaskSource:
    from symnav_bench.benchmark_sources.deepswe_source import DeepsweTaskSource
    from symnav_bench.benchmark_sources.multi_swe_bench_source import (
        MultiSweBenchTaskSource,
    )
    from symnav_bench.benchmark_sources.swe_polybench_source import (
        SwePolybenchTaskSource,
    )

    if selection.name == "deepswe":
        return DeepsweTaskSource(selection)
    if selection.name == "swe-polybench":
        return SwePolybenchTaskSource(selection, suite=suite)
    if selection.name == "multi-swe-bench":
        return MultiSweBenchTaskSource(selection, suite=suite)
    raise ValueError(f"no task source registered for benchmark {selection.name!r}")
