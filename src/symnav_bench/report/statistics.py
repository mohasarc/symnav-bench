from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from symnav_bench.report.study_dataset import ConfigurationMetrics


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


def compare_condition_to_stock(
    stock: ConfigurationMetrics,
    treatment: ConfigurationMetrics,
    *,
    bootstrap_samples: int = 10_000,
    randomization_samples: int = 100_000,
    seed: int,
    practical_threshold: float = 0.05,
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
        Estimate(value=point, lower_95=point, upper_95=point)
        if complete and point is not None
        else None
    )
    return ConditionComparison(
        configuration_id=_comparison_id(treatment),
        stock=stock,
        treatment=treatment,
        task_deltas=task_deltas,
        uplift=uplift,
        randomization_p_value=None,
        demonstrated_improvement=False,
        material_improvement=False,
        wins=sum(task.delta > 0 for task in task_deltas),
        ties=sum(task.delta == 0 for task in task_deltas),
        losses=sum(task.delta < 0 for task in task_deltas),
        primary=treatment.key.condition == "symnav",
    )


def _validate_pair(
    stock: ConfigurationMetrics,
    treatment: ConfigurationMetrics,
) -> None:
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
