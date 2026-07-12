from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from symnav_bench.batch_plan import BatchPlan
from symnav_bench.batch_plan import plan_balanced_batches, plan_trial_slots
from symnav_bench.report.study_dataset import StudyDataset
from symnav_bench.study import StudyManifest
from symnav_bench.suite import SuiteManifest


RunMode = Literal["run-next", "run-all", "resume"]


@dataclass(frozen=True)
class BatchSelection:
    study_id: str
    configuration_id: str
    mode: RunMode
    batches: tuple[BatchPlan, ...]


def select_batches(
    study: StudyManifest,
    suite: SuiteManifest,
    existing: StudyDataset | None,
    *,
    configuration_id: str,
    mode: RunMode,
) -> BatchSelection:
    if configuration_id not in {item.id for item in study.configurations}:
        raise ValueError(f"unknown configuration {configuration_id!r}")
    configuration_slots = [
        slot
        for slot in plan_trial_slots(study, suite)
        if slot.configuration_id == configuration_id
    ]
    completed = (
        {
            result.slot.slot_id
            for result in existing.slots
            if result.scored_attempt is not None
        }
        if existing is not None
        else set()
    )
    pending_slots = [slot for slot in configuration_slots if slot.slot_id not in completed]
    try:
        pending = tuple(
            plan_balanced_batches(
                pending_slots,
                randomization_seed=study.protocol.randomization_seed,
            )
        )
    except ValueError:
        planned = plan_balanced_batches(
            configuration_slots,
            randomization_seed=study.protocol.randomization_seed,
        )
        pending = tuple(
            BatchPlan(
                study_id=batch.study_id,
                configuration_id=batch.configuration_id,
                batch_id=batch.batch_id,
                index=batch.index,
                slots=tuple(slot for slot in batch.slots if slot.slot_id not in completed),
            )
            for batch in planned
            if any(slot.slot_id not in completed for slot in batch.slots)
        )
    selected = pending[:1] if mode == "run-next" else pending
    return BatchSelection(study.id, configuration_id, mode, selected)
