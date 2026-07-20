from __future__ import annotations

import hashlib
import json
import random
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
    if study.protocol.benchmark.source_revision != suite.deep_swe_sha:
        raise ValueError("suite DeepSWE sha does not match study protocol")
    return [
        TrialSlot(
            study_id=study.id,
            configuration_id=configuration.id,
            condition=condition,
            task=task.slug,
            repetition=repetition,
            slot_id=slot_id(
                study.id,
                configuration.id,
                condition,
                task.slug,
                repetition,
            ),
        )
        for configuration in study.configurations
        for task in sorted(suite.tasks, key=lambda entry: entry.slug)
        for repetition in range(1, study.protocol.repetitions + 1)
        for condition in study.protocol.conditions
    ]


def plan_balanced_batches(
    slots: Sequence[TrialSlot],
    *,
    randomization_seed: int,
    max_cells: int = 256,
) -> list[BatchPlan]:
    if not slots:
        return []
    if max_cells <= 0:
        raise ValueError("max_cells must be positive")
    study_ids = {slot.study_id for slot in slots}
    configuration_ids = {slot.configuration_id for slot in slots}
    if len(study_ids) != 1 or len(configuration_ids) != 1:
        raise ValueError("batch planning requires one study and one configuration")
    blocks = group_complete_blocks(slots)
    block_size = len(blocks[0])
    max_blocks = max_cells // block_size
    if max_blocks == 0:
        raise ValueError("max_cells cannot fit one complete condition block")
    shuffled_blocks = list(blocks)
    random.Random(randomization_seed).shuffle(shuffled_blocks)
    batch_count = (len(shuffled_blocks) + max_blocks - 1) // max_blocks
    smaller_batch_size, larger_batch_count = divmod(len(shuffled_blocks), batch_count)
    study_id = slots[0].study_id
    configuration_id = slots[0].configuration_id
    batches: list[BatchPlan] = []
    block_offset = 0
    for index in range(batch_count):
        block_count = smaller_batch_size + (1 if index < larger_batch_count else 0)
        batch_blocks = shuffled_blocks[block_offset : block_offset + block_count]
        block_offset += block_count
        batch_slots = tuple(slot for block in batch_blocks for slot in block)
        batches.append(
            BatchPlan(
                study_id=study_id,
                configuration_id=configuration_id,
                batch_id=f"{study_id}-{configuration_id}-batch-{index + 1:03d}",
                index=index,
                slots=batch_slots,
            )
        )
    return batches


def slot_id(
    study_id: str,
    configuration_id: str,
    condition: ConditionName,
    task: str,
    repetition: int,
) -> str:
    identity = {
        "study_id": study_id,
        "configuration_id": configuration_id,
        "condition": condition,
        "task": task,
        "repetition": repetition,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def group_complete_blocks(slots: Sequence[TrialSlot]) -> list[tuple[TrialSlot, ...]]:
    grouped: dict[tuple[str, int], list[TrialSlot]] = {}
    condition_order: list[ConditionName] = []
    for slot in slots:
        key = (slot.task, slot.repetition)
        grouped.setdefault(key, []).append(slot)
        if slot.condition not in condition_order:
            condition_order.append(slot.condition)
    condition_positions = {
        condition: position for position, condition in enumerate(condition_order)
    }
    expected_conditions = set(condition_order)
    blocks: list[tuple[TrialSlot, ...]] = []
    for key in sorted(grouped):
        block = grouped[key]
        actual_conditions = [slot.condition for slot in block]
        if len(actual_conditions) != len(set(actual_conditions)):
            raise ValueError(f"duplicate condition in trial block {key}")
        if set(actual_conditions) != expected_conditions:
            raise ValueError(f"incomplete condition block {key}")
        blocks.append(
            tuple(sorted(block, key=lambda slot: condition_positions[slot.condition]))
        )
    return blocks
