from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from symnav_bench.cell_identity import CellIdentity
from symnav_bench.run_spec import AgentSpec, Condition


@dataclass(frozen=True)
class RunConfig:
    specs: list[AgentSpec]
    conditions: list[Condition]
    tasks: list[str]
    reps: int
    rep_start: int
    parallel: int
    timeout_multiplier: float | None
    max_limit_wait: timedelta
    results_dir: Path
    tasks_dir: Path

    def cells(self) -> list[CellIdentity]:
        return [
            CellIdentity(spec=spec, condition_label=condition.label, task=task, rep=rep)
            for spec in self.specs
            for condition in self.conditions
            for task in self.tasks
            for rep in range(self.rep_start, self.rep_start + self.reps)
        ]
