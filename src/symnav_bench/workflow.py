from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from symnav_bench.batch_plan import BatchPlan


RunMode = Literal["run-next", "run-all", "resume"]


@dataclass(frozen=True)
class BatchSelection:
    study_id: str
    configuration_id: str
    mode: RunMode
    batches: tuple[BatchPlan, ...]
