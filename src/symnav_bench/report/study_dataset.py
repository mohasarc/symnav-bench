from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
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

    @classmethod
    def load(cls, study_dir: Path) -> StudyDataset:
        manifest = StudyManifest.load(study_dir / "study.yaml")
        suite = _load_suite_manifest(study_dir / "suite.json")
        planned_slots = plan_trial_slots(manifest, suite)
        attempts_by_slot: dict[str, list[AttemptRecord]] = {
            slot.slot_id: [] for slot in planned_slots
        }
        warnings: list[str] = []
        expected_bundle_hashes: dict[tuple[str, str], str | None] = {}
        for path in sorted(study_dir.glob("**/attempt.json")):
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
    raise NotImplementedError


@dataclass(frozen=True)
class LegacyDataset:
    cells: tuple[Cell, ...]
    warnings: tuple[str, ...]


def import_legacy_cells(cells_dir: Path) -> LegacyDataset:
    raise NotImplementedError


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
