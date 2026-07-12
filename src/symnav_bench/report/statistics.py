from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import product
from random import Random
from statistics import mean

from symnav_bench.report.study_dataset import ConfigurationMetrics
from symnav_bench.study import SymnavRevision


@dataclass(frozen=True)
class Estimate:
    value: float
    lower_95: float
    upper_95: float


@dataclass(frozen=True)
class TaskDelta:
    task: str
    stock: float
    treatment: float
    delta: float


@dataclass(frozen=True)
class ConditionComparison:
    configuration_id: str
    stock: ConfigurationMetrics
    treatment: ConfigurationMetrics
    task_deltas: tuple[TaskDelta, ...]
    uplift: Estimate | None
    randomization_p_value: float | None
    demonstrated_improvement: bool
    material_improvement: bool
    wins: int
    ties: int
    losses: int
    primary: bool
    study_id: str | None
    symnav_revision: SymnavRevision | None
    suite_fingerprint: str | None


def compare_condition_to_stock(
    stock: ConfigurationMetrics,
    treatment: ConfigurationMetrics,
    *,
    bootstrap_samples: int = 10_000,
    randomization_samples: int = 100_000,
    seed: int,
    practical_threshold: float = 0.05,
    study_id: str | None = None,
    symnav_revision: SymnavRevision | None = None,
    suite_fingerprint: str | None = None,
) -> ConditionComparison:
    _validate_pair(stock, treatment)
    stock_tasks = {task.task: task for task in stock.tasks}
    treatment_tasks = {task.task: task for task in treatment.tasks}
    if stock_tasks.keys() != treatment_tasks.keys():
        raise ValueError("stock and treatment task sets must match")
    task_deltas = tuple(
        TaskDelta(
            task=task,
            stock=stock_score,
            treatment=treatment_score,
            delta=treatment_score - stock_score,
        )
        for task in stock_tasks
        if (stock_score := stock_tasks[task].pass_fraction) is not None
        and (treatment_score := treatment_tasks[task].pass_fraction) is not None
    )
    complete = _complete(stock) and _complete(treatment)
    point = mean(task.delta for task in task_deltas) if task_deltas else None
    uplift = (
        _cluster_bootstrap(task_deltas, point, bootstrap_samples, seed)
        if complete and point is not None
        else None
    )
    randomization_p_value = (
        _paired_randomization(task_deltas, randomization_samples, seed)
        if uplift is not None
        else None
    )
    demonstrated_improvement = uplift is not None and uplift.lower_95 > 0
    return ConditionComparison(
        configuration_id=_comparison_id(treatment),
        stock=stock,
        treatment=treatment,
        task_deltas=task_deltas,
        uplift=uplift,
        randomization_p_value=randomization_p_value,
        demonstrated_improvement=demonstrated_improvement,
        material_improvement=(
            demonstrated_improvement and uplift.value >= practical_threshold
        ),
        wins=sum(task.delta > 0 for task in task_deltas),
        ties=sum(task.delta == 0 for task in task_deltas),
        losses=sum(task.delta < 0 for task in task_deltas),
        primary=treatment.key.condition == "symnav",
        study_id=study_id,
        symnav_revision=symnav_revision,
        suite_fingerprint=suite_fingerprint,
    )


def _validate_pair(
    stock: ConfigurationMetrics,
    treatment: ConfigurationMetrics,
) -> None:
    if not isinstance(stock, ConfigurationMetrics) or not isinstance(
        treatment, ConfigurationMetrics
    ):
        raise TypeError("external references cannot be used as stock or treatment")
    if stock.key.condition != "stock":
        raise ValueError("baseline must be stock")
    stock_configuration = (
        stock.key.agent,
        stock.key.model,
        stock.key.effort,
        stock.key.agent_version,
    )
    treatment_configuration = (
        treatment.key.agent,
        treatment.key.model,
        treatment.key.effort,
        treatment.key.agent_version,
    )
    if stock_configuration != treatment_configuration:
        raise ValueError("stock and treatment configuration must match")
    if treatment.key.condition == "stock":
        raise ValueError("treatment must not be stock")


def _complete(metrics: ConfigurationMetrics) -> bool:
    return (
        not metrics.coverage.provisional
        and metrics.coverage.complete_tasks == metrics.coverage.total_tasks
        and all(task.pass_fraction is not None for task in metrics.tasks)
    )


def _comparison_id(metrics: ConfigurationMetrics) -> str:
    key = metrics.key
    return ":".join(
        (key.agent, key.model, key.effort, key.agent_version, key.condition)
    )


def _cluster_bootstrap(
    task_deltas: tuple[TaskDelta, ...],
    point: float,
    samples: int,
    seed: int,
) -> Estimate:
    if samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    values = [task.delta for task in task_deltas]
    random = Random(seed)
    bootstrap = sorted(
        mean(random.choices(values, k=len(values))) for _ in range(samples)
    )
    return Estimate(
        value=point,
        lower_95=_percentile(bootstrap, 0.025),
        upper_95=_percentile(bootstrap, 0.975),
    )


def _percentile(values: list[float], quantile: float) -> float:
    position = (len(values) - 1) * quantile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(values) - 1)
    fraction = position - lower_index
    return values[lower_index] + (values[upper_index] - values[lower_index]) * fraction


def _paired_randomization(
    task_deltas: tuple[TaskDelta, ...],
    samples: int,
    seed: int,
) -> float:
    if samples <= 0:
        raise ValueError("randomization_samples must be positive")
    values = [task.delta for task in task_deltas]
    exact_permutations = 2 ** len(values)
    if exact_permutations <= samples:
        randomized = (
            mean(sign * value for sign, value in zip(signs, values, strict=True))
            for signs in product((-1, 1), repeat=len(values))
        )
        return _extreme_fraction(randomized, exact_permutations, values)
    random = Random(seed)
    randomized = (
        mean(random.choice((-1, 1)) * value for value in values)
        for _ in range(samples)
    )
    extreme = _extreme_count(randomized, values)
    return (extreme + 1) / (samples + 1)


def _extreme_fraction(
    randomized: Iterable[float],
    count: int,
    values: list[float],
) -> float:
    return _extreme_count(randomized, values) / count


def _extreme_count(randomized: Iterable[float], values: list[float]) -> int:
    observed = abs(mean(values))
    tolerance = 1e-12
    return sum(abs(value) + tolerance >= observed for value in randomized)
