from __future__ import annotations

from dataclasses import dataclass
from random import Random
from statistics import mean
from typing import Mapping

from symnav_bench.report.statistics import ConditionComparison
from symnav_bench.report.statistics import Estimate
from symnav_bench.study import SymnavRevision


@dataclass(frozen=True)
class VersionComparison:
    left_study_id: str
    right_study_id: str
    left_revision: SymnavRevision
    right_revision: SymnavRevision
    uplift_difference: Estimate


def compare_study_versions(
    left: ConditionComparison,
    right: ConditionComparison,
    *,
    seed: int,
) -> VersionComparison:
    _validate_version_pair(left, right)
    left_by_task = {task.task: task.delta for task in left.task_deltas}
    right_by_task = {task.task: task.delta for task in right.task_deltas}
    differences = [
        right_by_task[task] - left_by_task[task]
        for task in left_by_task
    ]
    estimate = _bootstrap_mean(differences, seed)
    assert left.study_id is not None
    assert right.study_id is not None
    assert left.symnav_revision is not None
    assert right.symnav_revision is not None
    return VersionComparison(
        left_study_id=left.study_id,
        right_study_id=right.study_id,
        left_revision=left.symnav_revision,
        right_revision=right.symnav_revision,
        uplift_difference=estimate,
    )


def order_symnav_revisions(
    revisions: tuple[SymnavRevision, ...],
    *,
    first_parent_positions: Mapping[str, int],
) -> tuple[SymnavRevision, ...]:
    def order_key(revision: SymnavRevision) -> tuple[int, int]:
        if revision.kind == "main":
            position = first_parent_positions.get(revision.sha)
            if position is not None:
                return (0, position)
            return (0, len(first_parent_positions) + revision.evaluation_sequence)
        return (1, revision.evaluation_sequence)

    return tuple(sorted(revisions, key=order_key))


def _validate_version_pair(
    left: ConditionComparison,
    right: ConditionComparison,
) -> None:
    if (
        left.study_id is None
        or right.study_id is None
        or left.symnav_revision is None
        or right.symnav_revision is None
        or left.suite_fingerprint is None
        or right.suite_fingerprint is None
    ):
        raise ValueError("version comparisons require study, revision, and suite metadata")
    if left.uplift is None or right.uplift is None:
        raise ValueError("version comparisons require complete condition comparisons")
    if left.suite_fingerprint != right.suite_fingerprint:
        raise ValueError("version comparison suite fingerprints must match")
    left_configuration = _configuration_identity(left)
    right_configuration = _configuration_identity(right)
    if left_configuration != right_configuration:
        raise ValueError("version comparison configuration must match")
    left_tasks = tuple(task.task for task in left.task_deltas)
    right_tasks = tuple(task.task for task in right.task_deltas)
    if left_tasks != right_tasks:
        raise ValueError("version comparison task sets must match")


def _configuration_identity(comparison: ConditionComparison) -> tuple[str, ...]:
    key = comparison.treatment.key
    return (
        key.agent,
        key.model,
        key.effort,
        key.agent_version,
        key.condition,
    )


def _bootstrap_mean(values: list[float], seed: int) -> Estimate:
    random = Random(seed)
    bootstrap = sorted(
        mean(random.choices(values, k=len(values))) for _ in range(10_000)
    )
    return Estimate(
        value=mean(values),
        lower_95=_percentile(bootstrap, 0.025),
        upper_95=_percentile(bootstrap, 0.975),
    )


def _percentile(values: list[float], quantile: float) -> float:
    position = (len(values) - 1) * quantile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(values) - 1)
    fraction = position - lower_index
    return values[lower_index] + (values[upper_index] - values[lower_index]) * fraction
