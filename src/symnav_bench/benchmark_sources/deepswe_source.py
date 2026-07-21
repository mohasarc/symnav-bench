from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from symnav_bench.benchmark_sources import BenchmarkTaskSource
from symnav_bench.deepswe import (
    DEFAULT_DEEPSWE_REPO,
    GitRunner,
    default_deepswe_root,
    ensure_deepswe_tasks,
)
from symnav_bench.study import BenchmarkSelection
from symnav_bench.suite import SuiteManifest, build_suite_manifest


class DeepsweTaskSource(BenchmarkTaskSource):
    def __init__(
        self,
        selection: BenchmarkSelection,
        repo: str = DEFAULT_DEEPSWE_REPO,
        runner: GitRunner | None = None,
    ) -> None:
        super().__init__(selection)
        self.repo = repo
        self.runner = runner

    def resolve(self) -> SuiteManifest:
        tasks_dir = self.ensure_tasks_dir((), default_deepswe_root())
        return build_suite_manifest(tasks_dir, self.selection.source_revision)

    def ensure_tasks_dir(self, slugs: Sequence[str], workdir: Path) -> Path:
        return ensure_deepswe_tasks(
            self.selection.source_revision,
            root=workdir,
            repo=self.repo,
            runner=self.runner,
        )
