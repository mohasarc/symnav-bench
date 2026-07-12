from __future__ import annotations

import pytest

from symnav_bench.report.statistics import compare_condition_to_stock
from symnav_bench.report.study_dataset import ConfigurationKey
from symnav_bench.report.study_dataset import ConfigurationMetrics
from symnav_bench.report.study_dataset import Coverage
from symnav_bench.report.study_dataset import TaskMetrics
from symnav_bench.report.versions import compare_study_versions
from symnav_bench.report.versions import order_symnav_revisions
from symnav_bench.study import SymnavRevision


def test_compares_version_specific_uplifts_without_pooling_trials() -> None:
    left = version_comparison(
        "study-a",
        revision("a", "main", 1),
        stock={"alpha": 0.75, "beta": 0.75},
        treatment={"alpha": 1.0, "beta": 1.0},
    )
    right = version_comparison(
        "study-b",
        revision("b", "pull_request", 2),
        stock={"alpha": 0.0, "beta": 0.0},
        treatment={"alpha": 0.5, "beta": 0.5},
    )

    result = compare_study_versions(left, right, seed=3)

    assert result.left_study_id == "study-a"
    assert result.right_study_id == "study-b"
    assert result.uplift_difference.value == 0.25
    assert result.uplift_difference.lower_95 == 0.25
    assert result.uplift_difference.upper_95 == 0.25


def test_rejects_suite_mismatch_instead_of_pooling_compatible_rows() -> None:
    left = version_comparison(
        "study-a",
        revision("a", "main", 1),
        stock={"alpha": 0.0},
        treatment={"alpha": 0.25},
        suite_fingerprint="suite-a",
    )
    right = version_comparison(
        "study-b",
        revision("b", "pull_request", 2),
        stock={"alpha": 0.0},
        treatment={"alpha": 0.5},
        suite_fingerprint="suite-b",
    )

    with pytest.raises(ValueError, match="suite"):
        compare_study_versions(left, right, seed=3)


def test_rejects_task_or_configuration_mismatch() -> None:
    left = version_comparison(
        "study-a",
        revision("a", "main", 1),
        stock={"alpha": 0.0},
        treatment={"alpha": 0.25},
    )
    task_mismatch = version_comparison(
        "study-b",
        revision("b", "pull_request", 2),
        stock={"beta": 0.0},
        treatment={"beta": 0.5},
    )
    configuration_mismatch = version_comparison(
        "study-c",
        revision("c", "pull_request", 3),
        stock={"alpha": 0.0},
        treatment={"alpha": 0.5},
        model="other",
    )

    with pytest.raises(ValueError, match="task"):
        compare_study_versions(left, task_mismatch, seed=3)
    with pytest.raises(ValueError, match="configuration"):
        compare_study_versions(left, configuration_mismatch, seed=3)


def test_orders_main_by_first_parent_and_previews_by_evaluation_sequence() -> None:
    main_later = revision("b", "main", 50)
    preview_later = revision("d", "pull_request", 40)
    preview_earlier = revision("c", "pull_request", 30)
    main_earlier = revision("a", "main", 60)

    ordered = order_symnav_revisions(
        (main_later, preview_later, preview_earlier, main_earlier),
        first_parent_positions={main_earlier.sha: 4, main_later.sha: 9},
    )

    assert ordered == (main_earlier, main_later, preview_earlier, preview_later)
    assert preview_earlier in ordered
    assert preview_later in ordered


def version_comparison(
    study_id: str,
    symnav_revision: SymnavRevision,
    *,
    stock: dict[str, float],
    treatment: dict[str, float],
    suite_fingerprint: str = "suite",
    model: str = "terra",
):
    return compare_condition_to_stock(
        metrics("stock", stock, model=model),
        metrics("symnav", treatment, model=model),
        study_id=study_id,
        symnav_revision=symnav_revision,
        suite_fingerprint=suite_fingerprint,
        seed=17,
    )


def revision(suffix: str, kind: str, sequence: int) -> SymnavRevision:
    return SymnavRevision(
        sha=suffix * 40,
        kind=kind,
        evaluation_sequence=sequence,
        base_ref="main",
        base_sha="0" * 40,
        pull_request=None if kind == "main" else sequence,
    )


def metrics(
    condition: str,
    task_scores: dict[str, float],
    *,
    model: str,
) -> ConfigurationMetrics:
    tasks = tuple(task_metrics(task, score) for task, score in task_scores.items())
    return ConfigurationMetrics(
        key=ConfigurationKey(
            agent="codex",
            model=model,
            effort="medium",
            agent_version="0.31.0",
            condition=condition,
            bundle_hash=None if condition == "stock" else "bundle",
        ),
        coverage=Coverage(
            planned_slots=len(tasks) * 4,
            scored_slots=len(tasks) * 4,
            retryable_attempts=0,
            unresolved_slot_ids=(),
            complete_tasks=len(tasks),
            total_tasks=len(tasks),
            provisional=False,
            pilot=False,
        ),
        tasks=tasks,
        performance_score=sum(task_scores.values()) / len(task_scores),
        repetition_scores=(0.0, 0.0, 0.0, 0.0),
        mean_f2p=None,
        mean_p2p=None,
        mean_partial=None,
        total_cost=None,
        cost_per_success=None,
        adoption=None,
    )


def task_metrics(task: str, score: float) -> TaskMetrics:
    return TaskMetrics(
        task=task,
        scored_trials=4,
        pass_fraction=score,
        mean_f2p=None,
        mean_p2p=None,
        mean_partial=None,
        mean_cost=None,
        median_cost=None,
        mean_output_tokens=None,
        mean_steps=None,
        mean_duration_seconds=None,
        adoption=None,
    )
