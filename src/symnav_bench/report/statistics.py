from __future__ import annotations

from dataclasses import dataclass

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
    raise NotImplementedError
