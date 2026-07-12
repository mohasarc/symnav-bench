from __future__ import annotations

import pytest

from symnav_bench.report.statistics import Estimate
from symnav_bench.report.statistics import compare_condition_to_stock
from symnav_bench.report.study_dataset import ConfigurationKey
from symnav_bench.report.study_dataset import ConfigurationMetrics
from symnav_bench.report.study_dataset import Coverage
from symnav_bench.report.study_dataset import TaskMetrics


def test_computes_task_paired_uplift() -> None:
    stock = metrics("stock", {"alpha": 0.25, "beta": 0.5})
    treatment = metrics("symnav", {"alpha": 0.75, "beta": 0.5})

    comparison = compare_condition_to_stock(stock, treatment, seed=7)

    assert [(task.task, task.stock, task.treatment, task.delta) for task in comparison.task_deltas] == [
        ("alpha", 0.25, 0.75, 0.5),
        ("beta", 0.5, 0.5, 0.0),
    ]
    assert comparison.uplift is not None
    assert comparison.uplift.value == 0.25
    assert (comparison.wins, comparison.ties, comparison.losses) == (1, 1, 0)


def test_cluster_bootstrap_resamples_whole_task_deltas() -> None:
    stock = metrics("stock", {"alpha": 0.0, "beta": 0.0, "gamma": 0.0})
    treatment = metrics("symnav", {"alpha": 0.0, "beta": 0.25, "gamma": 0.5})

    comparison = compare_condition_to_stock(
        stock,
        treatment,
        bootstrap_samples=1_000,
        seed=19,
    )

    assert comparison.uplift == Estimate(
        value=0.25,
        lower_95=pytest.approx(1 / 12),
        upper_95=pytest.approx(5 / 12),
    )


def test_paired_randomization_uses_hand_checkable_exact_distribution() -> None:
    stock = metrics("stock", {"alpha": 0.0, "beta": 0.0})
    treatment = metrics("symnav", {"alpha": 0.25, "beta": 0.25})

    comparison = compare_condition_to_stock(
        stock,
        treatment,
        randomization_samples=100,
        seed=3,
    )

    assert comparison.randomization_p_value == 0.5


def test_success_flags_require_positive_interval_and_five_point_effect() -> None:
    stock = metrics("stock", {"alpha": 0.0, "beta": 0.0, "gamma": 0.0})
    small = metrics("symnav", {"alpha": 0.04, "beta": 0.04, "gamma": 0.04})
    material = metrics("symnav", {"alpha": 0.25, "beta": 0.25, "gamma": 0.25})

    small_comparison = compare_condition_to_stock(stock, small, seed=1)
    material_comparison = compare_condition_to_stock(stock, material, seed=1)

    assert small_comparison.demonstrated_improvement is True
    assert small_comparison.material_improvement is False
    assert material_comparison.demonstrated_improvement is True
    assert material_comparison.material_improvement is True


def test_incomplete_primary_matrix_has_no_confirmatory_result() -> None:
    stock = metrics("stock", {"alpha": 1.0, "beta": 0.0}, complete=False)
    treatment = metrics("symnav", {"alpha": 1.0, "beta": 1.0})

    comparison = compare_condition_to_stock(stock, treatment, seed=4)

    assert comparison.uplift is None
    assert comparison.randomization_p_value is None
    assert comparison.demonstrated_improvement is False
    assert comparison.material_improvement is False


def test_preserves_four_deepswe_repetition_scores() -> None:
    stock = metrics(
        "stock",
        {"alpha": 0.5, "beta": 0.5},
        repetition_scores=(1.0, 0.5, 0.5, 0.0),
    )
    treatment = metrics(
        "symnav",
        {"alpha": 0.75, "beta": 0.75},
        repetition_scores=(1.0, 1.0, 0.5, 0.5),
    )

    comparison = compare_condition_to_stock(stock, treatment, seed=8)

    assert comparison.stock.performance_score == 0.5
    assert comparison.stock.repetition_scores == (1.0, 0.5, 0.5, 0.0)
    assert comparison.treatment.performance_score == 0.75
    assert comparison.treatment.repetition_scores == (1.0, 1.0, 0.5, 0.5)


def test_variant_uses_same_stock_without_replacing_primary_comparison() -> None:
    stock = metrics("stock", {"alpha": 0.25, "beta": 0.5})
    primary = metrics("symnav", {"alpha": 0.75, "beta": 0.75})
    variant = metrics("overview-refs", {"alpha": 0.5, "beta": 0.5})

    primary_comparison = compare_condition_to_stock(stock, primary, seed=9)
    variant_comparison = compare_condition_to_stock(stock, variant, seed=9)

    assert primary_comparison.primary is True
    assert primary_comparison.configuration_id.endswith(":symnav")
    assert variant_comparison.primary is False
    assert variant_comparison.configuration_id.endswith(":overview-refs")
    assert primary_comparison.stock is variant_comparison.stock


def test_rejects_non_stock_baseline_and_incompatible_configuration() -> None:
    stock = metrics("stock", {"alpha": 0.0})
    wrong_baseline = metrics("overview", {"alpha": 0.0})
    wrong_model = metrics("symnav", {"alpha": 1.0}, model="other")

    with pytest.raises(ValueError, match="baseline must be stock"):
        compare_condition_to_stock(wrong_baseline, stock, seed=1)
    with pytest.raises(ValueError, match="configuration"):
        compare_condition_to_stock(stock, wrong_model, seed=1)


def metrics(
    condition: str,
    task_scores: dict[str, float],
    *,
    complete: bool = True,
    model: str = "terra",
    repetition_scores: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0),
) -> ConfigurationMetrics:
    tasks = tuple(task_metrics(task, score) for task, score in task_scores.items())
    complete_tasks = len(tasks) if complete else len(tasks) - 1
    return ConfigurationMetrics(
        key=ConfigurationKey(
            agent="codex",
            model=model,
            effort="medium",
            agent_version="0.31.0",
            condition=condition,
            bundle_hash=None if condition == "stock" else condition,
        ),
        coverage=Coverage(
            planned_slots=len(tasks) * 4,
            scored_slots=(len(tasks) * 4 if complete else len(tasks) * 4 - 1),
            retryable_attempts=0,
            unresolved_slot_ids=() if complete else ("missing",),
            complete_tasks=complete_tasks,
            total_tasks=len(tasks),
            provisional=not complete,
            pilot=not complete,
        ),
        tasks=tasks,
        performance_score=sum(task_scores.values()) / len(task_scores),
        repetition_scores=repetition_scores,
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
