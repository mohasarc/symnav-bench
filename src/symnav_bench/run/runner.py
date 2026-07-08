from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep as real_sleep
from typing import Callable

from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.cell import Cell
from symnav_bench.cells.normalize import HarnessMeta, normalize_trial
from symnav_bench.run.config import RunConfig
from symnav_bench.run.job_config import build_job_yaml
from symnav_bench.run.limits import find_limit_marker, next_backoff, parse_limit_reset


PierRun = Callable[[Path, Path], None]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


class CellRunner:
    def __init__(
        self,
        config: RunConfig,
        harness: HarnessMeta,
        pier: PierRun,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self.config = config
        self.harness = harness
        self.pier = pier
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleep = sleeper or real_sleep

    @classmethod
    def from_environment(
        cls,
        config: RunConfig,
        pier: PierRun,
        image_version: str,
        deep_swe_ref: str,
        symnav_ref: str | None,
    ) -> "CellRunner":
        return cls(
            config=config,
            harness=HarnessMeta(
                image_version=image_version,
                pier_version=_pier_version(),
                deep_swe_ref=deep_swe_ref,
                symnav_ref=symnav_ref,
            ),
            pier=pier,
        )

    def run_all(self) -> list[Cell]:
        return [self.run_cell(cell) for cell in self.config.cells()]

    def run_cell(self, identity: CellIdentity) -> Cell:
        waits: list[timedelta] = []
        total_wait = timedelta()
        while True:
            jobs_dir = Path(tempfile.mkdtemp(prefix="symnav-bench-jobs-"))
            job_yaml = jobs_dir / "job.yaml"
            condition = next(c for c in self.config.conditions if c.label == identity.condition_label)
            job_yaml.write_text(
                build_job_yaml(identity.spec, condition, identity.task, self.config.tasks_dir),
                encoding="utf-8",
            )
            try:
                self.pier(job_yaml, jobs_dir)
            except Exception as error:
                marker = find_limit_marker(jobs_dir)
                if marker:
                    wait = self._limit_wait(marker, waits)
                    if total_wait + wait > self.config.max_limit_wait:
                        return normalize_trial(jobs_dir, identity, self.harness, "limited", marker[:500], self.config.results_dir)
                    waits.append(wait)
                    total_wait += wait
                    self.sleep(wait.total_seconds())
                    shutil.rmtree(jobs_dir, ignore_errors=True)
                    continue
                return normalize_trial(jobs_dir, identity, self.harness, "error", str(error), self.config.results_dir)
            return normalize_trial(jobs_dir, identity, self.harness, "completed", None, self.config.results_dir)

    def _limit_wait(self, marker: str, waits: list[timedelta]) -> timedelta:
        reset = parse_limit_reset(marker, self.clock())
        if reset is not None:
            return reset - self.clock().astimezone(UTC) + timedelta(minutes=1)
        return next_backoff(waits)


def subprocess_pier_run(job_yaml: Path, jobs_dir: Path) -> None:
    subprocess.run(["pier", "run", "--config", str(job_yaml), "--out", str(jobs_dir)], check=True)


def _pier_version() -> str:
    try:
        import datacurve_pier
    except Exception:
        return "unknown"
    return str(getattr(datacurve_pier, "__version__", "unknown"))
