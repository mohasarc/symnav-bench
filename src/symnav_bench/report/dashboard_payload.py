from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from symnav_bench.cells.attempt import AttemptRecord
from symnav_bench.report.official_reference import OfficialReferenceSnapshot
from symnav_bench.report.statistics import ConditionComparison
from symnav_bench.report.study_dataset import ConfigurationMetrics
from symnav_bench.report.study_dataset import StudyDataset
from symnav_bench.report.study_dataset import TaskMetrics
from symnav_bench.report.versions import VersionComparison


@dataclass(frozen=True)
class ArtifactPointer:
    archive_url: str | None
    archive_sha256: str | None
    archive_path: str | None
    direct_urls: dict[str, str]


@dataclass(frozen=True)
class DashboardPayload:
    schema_version: int
    study: dict[str, Any]
    coverage: dict[str, Any]
    configurations: tuple[dict[str, Any], ...]
    comparisons: tuple[dict[str, Any], ...]
    tasks: tuple[dict[str, Any], ...]
    versions: tuple[dict[str, Any], ...]
    official_references: tuple[dict[str, Any], ...]
    attempts: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]


def build_dashboard_payload(
    dataset: StudyDataset,
    metrics: Sequence[ConfigurationMetrics],
    comparisons: Sequence[ConditionComparison],
    versions: Sequence[VersionComparison],
    official: OfficialReferenceSnapshot | None,
) -> DashboardPayload:
    configuration_ids = _configuration_ids(dataset)
    attempts = tuple(
        _attempt_mapping(result.scored_attempt, result.slot.configuration_id)
        for result in dataset.slots
        if result.scored_attempt is not None
    )
    retries = tuple(
        _attempt_mapping(attempt, result.slot.configuration_id)
        for result in dataset.slots
        for attempt in result.attempts
        if attempt is not result.scored_attempt
    )
    return DashboardPayload(
        schema_version=1,
        study=_study_mapping(dataset),
        coverage=_study_coverage(metrics, len(dataset.suite.tasks)),
        configurations=tuple(
            _configuration_mapping(item, configuration_ids[_identity(item)])
            for item in metrics
        ),
        comparisons=tuple(
            _comparison_mapping(item, configuration_ids[_identity(item.treatment)])
            for item in comparisons
        ),
        tasks=tuple(
            _task_mapping(
                task,
                item,
                configuration_ids[_identity(item)],
                dataset,
            )
            for item in metrics
            for task in item.tasks
        ),
        versions=tuple(asdict(item) for item in versions),
        official_references=_official_mappings(official),
        attempts=attempts + retries,
        warnings=dataset.warnings,
    )


def _study_mapping(dataset: StudyDataset) -> dict[str, Any]:
    benchmark = dataset.manifest.protocol.benchmark
    study = {
        "id": dataset.manifest.id,
        "protocol_fingerprint": dataset.manifest.protocol_fingerprint(),
        "suite_fingerprint": dataset.suite.fingerprint,
        "deep_swe_sha": benchmark.source_revision,
        "symnav_revision": asdict(dataset.manifest.protocol.symnav),
        "repetitions": dataset.manifest.protocol.repetitions,
        "conditions": list(dataset.manifest.protocol.conditions),
        "scoring_policy": dataset.manifest.protocol.scoring_policy,
        "practical_uplift_points": dataset.manifest.protocol.practical_uplift_points,
    }
    if benchmark.name != "deepswe":
        study["benchmark"] = benchmark.name
        study["benchmark_source_revision"] = benchmark.source_revision
    return study


def _configuration_ids(dataset: StudyDataset) -> dict[tuple[str, ...], str]:
    return {
        (
            configuration.spec.agent,
            configuration.spec.model,
            configuration.spec.effort,
            configuration.agent_version,
        ): configuration.id
        for configuration in dataset.manifest.configurations
    }


def _identity(metrics: ConfigurationMetrics) -> tuple[str, ...]:
    return (
        metrics.key.agent,
        metrics.key.model,
        metrics.key.effort,
        metrics.key.agent_version,
    )


def _configuration_mapping(
    metrics: ConfigurationMetrics,
    configuration_id: str,
) -> dict[str, Any]:
    key = metrics.key
    return {
        "id": configuration_id,
        "configuration_key": ":".join(_identity(metrics)),
        "label": f"{key.agent} · {key.model} · {key.effort} · {key.condition}",
        "agent": key.agent,
        "model": key.model,
        "effort": key.effort,
        "agent_version": key.agent_version,
        "condition": key.condition,
        "bundle_hash": key.bundle_hash,
        "full_symnav": key.condition == "symnav",
        "coverage": asdict(metrics.coverage),
        "metrics": {
            "performance_score": metrics.performance_score,
            "repetition_scores": list(metrics.repetition_scores),
            "f2p": metrics.mean_f2p,
            "p2p": metrics.mean_p2p,
            "partial": metrics.mean_partial,
            "cost": metrics.total_cost,
            "cost_per_success": metrics.cost_per_success,
        },
        "adoption": asdict(metrics.adoption) if metrics.adoption is not None else None,
    }


def _task_mapping(
    task: TaskMetrics,
    metrics: ConfigurationMetrics,
    configuration_id: str,
    dataset: StudyDataset,
) -> dict[str, Any]:
    matching = [
        result
        for result in dataset.slots
        if result.slot.configuration_id == configuration_id
        and result.slot.condition == metrics.key.condition
        and result.slot.task == task.task
    ]
    trials = [
        {
            "repetition": result.slot.repetition,
            "outcome": (
                result.scored_attempt.disposition.outcome
                if result.scored_attempt is not None
                else None
            ),
            "attempt_id": (
                result.scored_attempt.identity.attempt_id
                if result.scored_attempt is not None
                else None
            ),
        }
        for result in matching
    ]
    failure_counts: dict[str, int] = {}
    for result in matching:
        if result.scored_attempt is None:
            continue
        reason = (
            result.scored_attempt.disposition.scored_failure_reason
            or result.scored_attempt.disposition.retry_reason
        )
        if reason is not None:
            failure_counts[reason] = failure_counts.get(reason, 0) + 1
    row: dict[str, Any] = {
        "configuration_id": configuration_id,
        "configuration_key": ":".join(_identity(metrics)),
        "condition": metrics.key.condition,
        "full_symnav": metrics.key.condition == "symnav",
        "task": task.task,
        "complete": task.scored_trials == dataset.manifest.protocol.repetitions,
        "metrics": {
            "performance_score": task.pass_fraction,
            "f2p": task.mean_f2p,
            "p2p": task.mean_p2p,
            "partial": task.mean_partial,
            "cost": task.mean_cost,
            "median_cost": task.median_cost,
            "output_tokens": task.mean_output_tokens,
            "steps": task.mean_steps,
            "duration": task.mean_duration_seconds,
            "failures": sum(failure_counts.values()),
        },
        "trials": trials,
        "failure_counts": failure_counts,
        "adoption": asdict(task.adoption) if task.adoption is not None else None,
    }
    if task.tier is not None:
        row["tier"] = task.tier
    return row


def _comparison_mapping(
    comparison: ConditionComparison,
    base_configuration_id: str,
) -> dict[str, Any]:
    return {
        "configuration_id": comparison.configuration_id,
        "base_configuration_id": base_configuration_id,
        "condition": comparison.treatment.key.condition,
        "primary": comparison.primary,
        "uplift": asdict(comparison.uplift) if comparison.uplift is not None else None,
        "randomization_p_value": comparison.randomization_p_value,
        "demonstrated_improvement": comparison.demonstrated_improvement,
        "material_improvement": comparison.material_improvement,
        "wins": comparison.wins,
        "ties": comparison.ties,
        "losses": comparison.losses,
        "task_deltas": [asdict(item) for item in comparison.task_deltas],
        "f2p_uplift": asdict(comparison.f2p_uplift) if comparison.f2p_uplift is not None else None,
        "f2p_task_deltas": [asdict(item) for item in comparison.f2p_task_deltas],
        "study_id": comparison.study_id,
        "symnav_revision": (
            asdict(comparison.symnav_revision)
            if comparison.symnav_revision is not None
            else None
        ),
        "suite_fingerprint": comparison.suite_fingerprint,
    }


def _attempt_mapping(attempt: AttemptRecord, configuration_id: str) -> dict[str, Any]:
    pointer = _artifact_pointer(attempt)
    return {
        "configuration_id": configuration_id,
        "condition": attempt.slot.condition,
        "task": attempt.slot.task,
        "repetition": attempt.slot.repetition,
        "slot_id": attempt.slot.slot_id,
        "attempt_id": attempt.identity.attempt_id,
        "written_at": attempt.written_at,
        "outcome": attempt.disposition.outcome,
        "scored_failure_reason": attempt.disposition.scored_failure_reason,
        "retry_reason": attempt.disposition.retry_reason,
        "detail": attempt.disposition.detail,
        "rewards": attempt.rewards,
        "usage": attempt.usage,
        "timing": attempt.timing,
        "adoption": asdict(attempt.adoption),
        "artifacts": asdict(pointer),
    }


def _artifact_pointer(attempt: AttemptRecord) -> ArtifactPointer:
    direct_urls = {
        name.removesuffix("_url"): value
        for name, value in attempt.usage.items()
        if name.endswith("_url") and isinstance(value, str)
    }
    artifact = attempt.artifact
    return ArtifactPointer(
        archive_url=(
            artifact.archive
            if artifact is not None
            else _optional_string(attempt.usage.get("archive_url"))
        ),
        archive_sha256=(
            artifact.sha256
            if artifact is not None
            else _optional_string(attempt.usage.get("archive_sha256"))
        ),
        archive_path=(
            artifact.internal_path
            if artifact is not None
            else _optional_string(attempt.usage.get("archive_path"))
        ),
        direct_urls=direct_urls,
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _official_mappings(
    official: OfficialReferenceSnapshot | None,
) -> tuple[dict[str, Any], ...]:
    if official is None:
        return ()
    return tuple(
        {
            "model": item.model,
            "effort": item.effort,
            "task_scores": item.task_scores,
            "performance_score": item.performance_score,
            "repetition_scores": item.repetition_scores,
            "source_kind": item.source_kind,
            "harness": official.harness,
            "source_url": official.source_url,
            "source_sha256": official.source_sha256,
            "fetched_at": official.fetched_at,
        }
        for item in official.configurations
    )


def _study_coverage(
    metrics: Sequence[ConfigurationMetrics],
    total_tasks: int,
) -> dict[str, Any]:
    complete_tasks = min(
        (item.coverage.complete_tasks for item in metrics),
        default=0,
    )
    return {
        "planned_slots": sum(item.coverage.planned_slots for item in metrics),
        "scored_slots": sum(item.coverage.scored_slots for item in metrics),
        "complete_tasks": complete_tasks,
        "total_tasks": total_tasks,
        "provisional": any(item.coverage.provisional for item in metrics),
        "pilot": any(item.coverage.pilot for item in metrics),
    }
