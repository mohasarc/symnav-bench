from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from symnav_bench.study import ConditionName, StudyManifest
from symnav_bench.suite import SuiteManifest


@dataclass(frozen=True)
class TrialSlot:
    study_id: str
    configuration_id: str
    condition: ConditionName
    task: str
    repetition: int
    slot_id: str


@dataclass(frozen=True)
class BatchPlan:
    study_id: str
    configuration_id: str
    batch_id: str
    index: int
    slots: tuple[TrialSlot, ...]


def plan_trial_slots(study: StudyManifest, suite: SuiteManifest) -> list[TrialSlot]:
    raise NotImplementedError


def plan_balanced_batches(
    slots: Sequence[TrialSlot],
    *,
    randomization_seed: int,
    max_cells: int = 256,
) -> list[BatchPlan]:
    raise NotImplementedError
