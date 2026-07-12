from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean, median
from typing import Any, cast

from symnav_bench.batch_plan import TrialSlot, plan_trial_slots, slot_id
from symnav_bench.cells.attempt import AttemptRecord
from symnav_bench.cells.attempt import SlotResult
from symnav_bench.cells.cell import Cell
from symnav_bench.study import StudyManifest
from symnav_bench.suite import SuiteManifest


@dataclass(frozen=True)
class ConfigurationKey:
    agent: str
    model: str
    effort: str
    agent_version: str
    condition: str
    bundle_hash: str | None


@dataclass(frozen=True)
class Coverage:
    planned_slots: int
    scored_slots: int
    retryable_attempts: int
    unresolved_slot_ids: tuple[str, ...]
    complete_tasks: int
    total_tasks: int
    provisional: bool
    pilot: bool


@dataclass(frozen=True)
class AdoptionSummary:
    used_symnav_rate: float
    read_symnav_skill_rate: float
    mean_symnav_calls: float
    mean_symnav_calls_per_agent_step: float
    mean_symnav_failures: float
    mean_symnav_timeouts: float
    mean_first_symnav_step: float | None
    mean_search_calls: float
    mean_read_calls: float
    mean_patch_calls: float
    mean_command_counts: dict[str, float]


@dataclass(frozen=True)
class TaskMetrics:
    task: str
    scored_trials: int
    pass_fraction: float | None
    mean_f2p: float | None
    mean_p2p: float | None
    mean_partial: float | None
    mean_cost: float | None
    median_cost: float | None
    mean_output_tokens: float | None
    mean_steps: float | None
    mean_duration_seconds: float | None
    adoption: AdoptionSummary | None


@dataclass(frozen=True)
class ConfigurationMetrics:
    key: ConfigurationKey
    coverage: Coverage
    tasks: tuple[TaskMetrics, ...]
    performance_score: float | None
    repetition_scores: tuple[float, ...]
    mean_f2p: float | None
    mean_p2p: float | None
    mean_partial: float | None
    total_cost: float | None
    cost_per_success: float | None
    adoption: AdoptionSummary | None


@dataclass(frozen=True)
class StudyDataset:
    manifest: StudyManifest
    suite: SuiteManifest
    slots: tuple[SlotResult, ...]
    warnings: tuple[str, ...]
    source_dir: Path | None = None

    @classmethod
    def load(cls, study_dir: Path) -> StudyDataset:
        manifest_path = study_dir / "manifest.yml"
        if not manifest_path.exists():
            manifest_path = study_dir / "study.yaml"
        manifest = StudyManifest.load(manifest_path)
        suite = _load_suite_manifest(study_dir / "suite.json")
        planned_slots = plan_trial_slots(manifest, suite)
        attempts_by_slot: dict[str, list[AttemptRecord]] = {
            slot.slot_id: [] for slot in planned_slots
        }
        warnings: list[str] = []
        expected_bundle_hashes: dict[tuple[str, str], str | None] = {}
        attempt_paths = {
            *study_dir.glob("**/attempt.json"),
            *study_dir.glob("attempts/*/*.json"),
        }
        for path in sorted(attempt_paths):
            raw = _load_mapping(path)
            semantic_slot = _planned_semantic_slot(planned_slots, raw)
            if semantic_slot is None:
                warnings.append(f"{path}: incompatible slot identity")
                continue
            reason = _compatibility_mismatch(
                manifest,
                suite,
                semantic_slot,
                raw,
                expected_bundle_hashes,
            )
            if reason is not None:
                warnings.append(f"{path}: incompatible {reason}")
                continue
            try:
                attempt = AttemptRecord.load(path)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                warnings.append(f"{path}: invalid attempt record: {error}")
                continue
            attempts_by_slot[semantic_slot.slot_id].append(attempt)
        results = tuple(
            _select_slot(slot, attempts_by_slot[slot.slot_id], warnings)
            for slot in planned_slots
        )
        return cls(
            manifest=manifest,
            suite=suite,
            slots=results,
            warnings=tuple(warnings),
            source_dir=study_dir,
        )

    def configurations(self) -> dict[ConfigurationKey, tuple[SlotResult, ...]]:
        groups: dict[ConfigurationKey, tuple[SlotResult, ...]] = {}
        for configuration in self.manifest.configurations:
            for condition in self.manifest.protocol.conditions:
                matching = tuple(
                    result
                    for result in self.slots
                    if result.slot.configuration_id == configuration.id
                    and result.slot.condition == condition
                )
                bundle_hashes = {
                    attempt.harness.bundle_hash
                    for result in matching
                    for attempt in result.attempts
                }
                bundle_hash = next(iter(bundle_hashes), None)
                key = ConfigurationKey(
                    agent=configuration.spec.agent,
                    model=configuration.spec.model,
                    effort=configuration.spec.effort,
                    agent_version=configuration.agent_version,
                    condition=condition,
                    bundle_hash=bundle_hash,
                )
                groups[key] = matching
        return groups


def compute_configuration_metrics(
    dataset: StudyDataset,
    key: ConfigurationKey,
) -> ConfigurationMetrics:
    grouped = dataset.configurations()
    if key not in grouped:
        raise KeyError(f"unknown configuration key {key}")
    results = grouped[key]
    configuration_id = _configuration_id(dataset, key)
    complete_tasks = _complete_tasks(dataset, configuration_id)
    task_metrics = tuple(
        _effectiveness_task_metrics(task.slug, results)
        for task in dataset.suite.tasks
    )
    completed_metrics = [
        task for task in task_metrics if task.task in complete_tasks
    ]
    unresolved = tuple(
        result.slot.slot_id for result in results if result.scored_attempt is None
    )
    scored_slots = sum(result.scored_attempt is not None for result in results)
    retryable_attempts = sum(
        attempt.disposition.outcome == "retryable_error"
        for result in results
        for attempt in result.attempts
    )
    total_tasks = len(dataset.suite.tasks)
    coverage = Coverage(
        planned_slots=len(results),
        scored_slots=scored_slots,
        retryable_attempts=retryable_attempts,
        unresolved_slot_ids=unresolved,
        complete_tasks=len(complete_tasks),
        total_tasks=total_tasks,
        provisional=len(complete_tasks) != total_tasks,
        pilot=scored_slots > 0 and len(complete_tasks) != total_tasks,
    )
    repetitions = dataset.manifest.protocol.repetitions
    repetition_scores = tuple(
        _repetition_score(results, complete_tasks, repetition)
        for repetition in range(1, repetitions + 1)
    ) if complete_tasks else ()
    scored_attempts = [
        result.scored_attempt
        for result in results
        if result.scored_attempt is not None
    ]
    costs = _usage_values(scored_attempts, "cost_usd_imputed")
    successes = sum(
        attempt.disposition.outcome == "passed" for attempt in scored_attempts
    )
    total_cost = sum(costs) if costs else None
    return ConfigurationMetrics(
        key=key,
        coverage=coverage,
        tasks=task_metrics,
        performance_score=_mean_optional(
            [task.pass_fraction for task in completed_metrics]
        ),
        repetition_scores=repetition_scores,
        mean_f2p=_mean_optional([task.mean_f2p for task in completed_metrics]),
        mean_p2p=_mean_optional([task.mean_p2p for task in completed_metrics]),
        mean_partial=_mean_optional(
            [task.mean_partial for task in completed_metrics]
        ),
        total_cost=total_cost,
        cost_per_success=(
            total_cost / successes
            if total_cost is not None and successes > 0
            else None
        ),
        adoption=_macro_adoption(
            [task.adoption for task in task_metrics if task.adoption is not None]
        ),
    )


@dataclass(frozen=True)
class LegacyDataset:
    cells: tuple[Cell, ...]
    warnings: tuple[str, ...]


def import_legacy_cells(cells_dir: Path) -> LegacyDataset:
    cells: list[Cell] = []
    warnings: list[str] = []
    for path in sorted(cells_dir.glob("*/cell.json")):
        cell = Cell.load(path)
        solved = _legacy_binary_reward(cell) == 1.0
        normalized = replace(cell, solved=solved)
        cells.append(normalized)
        missing = _missing_legacy_metadata(normalized)
        if missing:
            warnings.append(
                f"{normalized.identity.dirname()} missing metadata: {', '.join(missing)}"
            )
    return LegacyDataset(cells=tuple(cells), warnings=tuple(warnings))


def _load_suite_manifest(path: Path) -> SuiteManifest:
    raw = _load_mapping(path)
    task_values = raw.get("tasks")
    if not isinstance(task_values, list):
        raise ValueError("suite tasks must be a list")
    from symnav_bench.suite import TaskManifestEntry

    tasks = tuple(
        TaskManifestEntry(
            slug=str(_mapping(task).get("slug")),
            language=str(_mapping(task).get("language")),
            checksum=str(_mapping(task).get("checksum")),
        )
        for task in task_values
    )
    return SuiteManifest(
        deep_swe_sha=str(raw["deep_swe_sha"]),
        tasks=tasks,
        fingerprint=str(raw["fingerprint"]),
    )


def _planned_semantic_slot(
    planned_slots: list[TrialSlot],
    raw: dict[str, Any],
) -> TrialSlot | None:
    raw_slot = _mapping(raw.get("slot"))
    for planned in planned_slots:
        if (
            raw_slot.get("configuration_id") == planned.configuration_id
            and raw_slot.get("condition") == planned.condition
            and raw_slot.get("task") == planned.task
            and raw_slot.get("repetition") == planned.repetition
        ):
            return planned
    return None


def _compatibility_mismatch(
    manifest: StudyManifest,
    suite: SuiteManifest,
    planned: TrialSlot,
    raw: dict[str, Any],
    expected_bundle_hashes: dict[tuple[str, str], str | None],
) -> str | None:
    raw_slot = _mapping(raw.get("slot"))
    identity = _mapping(raw.get("identity"))
    harness = _mapping(raw.get("harness"))
    configuration = next(
        item for item in manifest.configurations if item.id == planned.configuration_id
    )
    task = next(item for item in suite.tasks if item.slug == planned.task)
    if raw_slot.get("study_id") != manifest.id:
        return "study ID"
    if raw.get("protocol_fingerprint") != manifest.protocol_fingerprint():
        return "protocol fingerprint"
    if (
        harness.get("deep_swe_sha") != manifest.protocol.deep_swe_sha
        or (
            planned.condition != "stock"
            and harness.get("symnav_sha") != manifest.protocol.symnav.sha
        )
    ):
        return "protocol fingerprint"
    if raw.get("suite_fingerprint") != suite.fingerprint:
        return "suite fingerprint"
    if harness.get("task_checksum") != task.checksum:
        return "task checksum"
    if (
        raw_slot.get("configuration_id") != configuration.id
        or harness.get("agent_name") != configuration.spec.agent
        or harness.get("requested_model") != configuration.spec.model
        or harness.get("requested_effort") != configuration.spec.effort
    ):
        return "configuration"
    bundle_hash = harness.get("bundle_hash")
    if planned.condition == "stock":
        if bundle_hash is not None:
            return "condition bundle hash"
    elif not isinstance(bundle_hash, str) or not bundle_hash:
        return "condition bundle hash"
    bundle_key = (configuration.id, planned.condition)
    if bundle_key in expected_bundle_hashes:
        if expected_bundle_hashes[bundle_key] != bundle_hash:
            return "condition bundle hash"
    else:
        expected_bundle_hashes[bundle_key] = cast(str | None, bundle_hash)
    if (
        raw.get("agent_version") != configuration.agent_version
        or harness.get("agent_version") != configuration.agent_version
    ):
        return "agent version"
    expected_slot_id = slot_id(
        manifest.id,
        configuration.id,
        planned.condition,
        planned.task,
        planned.repetition,
    )
    if (
        planned.slot_id != expected_slot_id
        or raw_slot.get("slot_id") != expected_slot_id
        or identity.get("slot_id") != expected_slot_id
    ):
        return "slot identity"
    return None


def _select_slot(
    slot: TrialSlot,
    attempts: list[AttemptRecord],
    warnings: list[str],
) -> SlotResult:
    from symnav_bench.cells.attempt import select_slot_result

    result = select_slot_result(slot, attempts)
    warnings.extend(result.warnings)
    return result


def _load_mapping(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return cast(dict[str, Any], value)


def _mapping(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _configuration_id(dataset: StudyDataset, key: ConfigurationKey) -> str:
    for configuration in dataset.manifest.configurations:
        if (
            configuration.spec.agent == key.agent
            and configuration.spec.model == key.model
            and configuration.spec.effort == key.effort
            and configuration.agent_version == key.agent_version
        ):
            return configuration.id
    raise KeyError(f"configuration metadata not found for {key}")


def _complete_tasks(dataset: StudyDataset, configuration_id: str) -> set[str]:
    repetitions = dataset.manifest.protocol.repetitions
    conditions = dataset.manifest.protocol.conditions
    complete: set[str] = set()
    for task in dataset.suite.tasks:
        matching = [
            result
            for result in dataset.slots
            if result.slot.configuration_id == configuration_id
            and result.slot.task == task.slug
        ]
        complete_conditions = {
            condition
            for condition in conditions
            if sum(
                result.scored_attempt is not None
                for result in matching
                if result.slot.condition == condition
            )
            == repetitions
        }
        if complete_conditions == set(conditions):
            complete.add(task.slug)
    return complete


def _effectiveness_task_metrics(
    task: str,
    results: tuple[SlotResult, ...],
) -> TaskMetrics:
    attempts = [
        result.scored_attempt
        for result in results
        if result.slot.task == task and result.scored_attempt is not None
    ]
    costs = _usage_values(attempts, "cost_usd_imputed")
    return TaskMetrics(
        task=task,
        scored_trials=len(attempts),
        pass_fraction=(
            mean(attempt.disposition.outcome == "passed" for attempt in attempts)
            if attempts
            else None
        ),
        mean_f2p=_mean_reward(attempts, "f2p"),
        mean_p2p=_mean_reward(attempts, "p2p"),
        mean_partial=_mean_reward(attempts, "partial"),
        mean_cost=mean(costs) if costs else None,
        median_cost=median(costs) if costs else None,
        mean_output_tokens=_mean_optional(
            [_number(attempt.usage.get("n_output_tokens")) for attempt in attempts]
        ),
        mean_steps=_mean_optional(
            [_number(attempt.usage.get("n_agent_steps")) for attempt in attempts]
        ),
        mean_duration_seconds=_mean_optional(
            [_duration_seconds(attempt) for attempt in attempts]
        ),
        adoption=_task_adoption(attempts),
    )


def _repetition_score(
    results: tuple[SlotResult, ...],
    complete_tasks: set[str],
    repetition: int,
) -> float:
    outcomes = [
        result.scored_attempt.disposition.outcome == "passed"
        for result in results
        if result.slot.task in complete_tasks
        and result.slot.repetition == repetition
        and result.scored_attempt is not None
    ]
    return mean(outcomes)


def _mean_reward(attempts: list[AttemptRecord], key: str) -> float | None:
    return _mean_optional([_number(attempt.rewards.get(key)) for attempt in attempts])


def _mean_optional(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return mean(present) if present else None


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _usage_values(attempts: list[AttemptRecord], key: str) -> list[float]:
    return [
        value
        for attempt in attempts
        if (value := _number(attempt.usage.get(key))) is not None
    ]


def _duration_seconds(attempt: AttemptRecord) -> float | None:
    direct = _number(attempt.timing.get("duration_seconds"))
    if direct is not None:
        return direct
    total = _number(attempt.timing.get("total_seconds"))
    if total is not None:
        return total
    values = [
        value
        for name, raw in attempt.timing.items()
        if name.endswith("_seconds") and (value := _number(raw)) is not None
    ]
    return sum(values) if values else None


def _task_adoption(attempts: list[AttemptRecord]) -> AdoptionSummary | None:
    if not attempts:
        return None
    command_names = sorted(
        {
            command
            for attempt in attempts
            for command in attempt.adoption.command_counts
        }
    )
    return AdoptionSummary(
        used_symnav_rate=mean(attempt.adoption.used_symnav for attempt in attempts),
        read_symnav_skill_rate=mean(
            attempt.adoption.read_symnav_skill for attempt in attempts
        ),
        mean_symnav_calls=mean(attempt.adoption.symnav_calls for attempt in attempts),
        mean_symnav_calls_per_agent_step=mean(
            attempt.adoption.symnav_calls_per_agent_step for attempt in attempts
        ),
        mean_symnav_failures=mean(
            attempt.adoption.symnav_failures for attempt in attempts
        ),
        mean_symnav_timeouts=mean(
            attempt.adoption.symnav_timeouts for attempt in attempts
        ),
        mean_first_symnav_step=_mean_optional(
            [
                _number(attempt.adoption.first_symnav_step)
                for attempt in attempts
            ]
        ),
        mean_search_calls=mean(
            attempt.adoption.search_calls for attempt in attempts
        ),
        mean_read_calls=mean(attempt.adoption.read_calls for attempt in attempts),
        mean_patch_calls=mean(attempt.adoption.patch_calls for attempt in attempts),
        mean_command_counts={
            command: mean(
                attempt.adoption.command_counts.get(command, 0)
                for attempt in attempts
            )
            for command in command_names
        },
    )


def _macro_adoption(summaries: list[AdoptionSummary]) -> AdoptionSummary | None:
    if not summaries:
        return None
    command_names = sorted(
        {
            command
            for summary in summaries
            for command in summary.mean_command_counts
        }
    )
    return AdoptionSummary(
        used_symnav_rate=mean(summary.used_symnav_rate for summary in summaries),
        read_symnav_skill_rate=mean(
            summary.read_symnav_skill_rate for summary in summaries
        ),
        mean_symnav_calls=mean(summary.mean_symnav_calls for summary in summaries),
        mean_symnav_calls_per_agent_step=mean(
            summary.mean_symnav_calls_per_agent_step for summary in summaries
        ),
        mean_symnav_failures=mean(
            summary.mean_symnav_failures for summary in summaries
        ),
        mean_symnav_timeouts=mean(
            summary.mean_symnav_timeouts for summary in summaries
        ),
        mean_first_symnav_step=_mean_optional(
            [summary.mean_first_symnav_step for summary in summaries]
        ),
        mean_search_calls=mean(summary.mean_search_calls for summary in summaries),
        mean_read_calls=mean(summary.mean_read_calls for summary in summaries),
        mean_patch_calls=mean(summary.mean_patch_calls for summary in summaries),
        mean_command_counts={
            command: mean(
                summary.mean_command_counts.get(command, 0.0)
                for summary in summaries
            )
            for command in command_names
        },
    )


def _legacy_binary_reward(cell: Cell) -> float | None:
    reward = _number(cell.rewards.get("reward"))
    if reward is not None:
        return reward
    return _number(cell.rewards.get("f2p"))


def _missing_legacy_metadata(cell: Cell) -> list[str]:
    missing: list[str] = []
    if cell.agent_version is None:
        missing.append("agent_version")
    if not cell.harness:
        missing.append("harness")
    if cell.written_at is None:
        missing.append("written_at")
    return missing
