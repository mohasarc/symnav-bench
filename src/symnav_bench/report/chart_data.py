from __future__ import annotations

from dataclasses import dataclass

from symnav_bench.report.comparison import ArmComparison


@dataclass(frozen=True)
class SeriesData:
    title: str
    labels: list[str]
    left: list[float]
    right: list[float]
    left_label: str
    right_label: str


def paired_f2p_series(comparison: ArmComparison) -> SeriesData:
    labels = sorted({cell.identity.task for cell in comparison.left_cells + comparison.right_cells})
    return SeriesData(
        title="Per-task f2p",
        labels=labels,
        left=[_task_f2p(comparison.left_cells, task) for task in labels],
        right=[_task_f2p(comparison.right_cells, task) for task in labels],
        left_label=comparison.left.condition_label,
        right_label=comparison.right.condition_label,
    )


def efficiency_distributions(comparison: ArmComparison) -> SeriesData:
    return SeriesData(
        title="Matched solved efficiency",
        labels=["cost_usd_imputed", "tokens", "steps"],
        left=[
            comparison.efficiency.left_cost or 0.0,
            comparison.efficiency.left_tokens or 0.0,
            comparison.efficiency.left_steps or 0.0,
        ],
        right=[
            comparison.efficiency.right_cost or 0.0,
            comparison.efficiency.right_tokens or 0.0,
            comparison.efficiency.right_steps or 0.0,
        ],
        left_label=comparison.left.condition_label,
        right_label=comparison.right.condition_label,
    )


def substitution_series(comparison: ArmComparison) -> SeriesData:
    labels = ["symnav", "search", "read", "other", "timeouts"]
    return SeriesData(
        title="Command adoption",
        labels=labels,
        left=[_command_count(comparison.left_cells, label) for label in labels],
        right=[_command_count(comparison.right_cells, label) for label in labels],
        left_label=comparison.left.condition_label,
        right_label=comparison.right.condition_label,
    )


def progression_series(comparisons: list[ArmComparison]) -> SeriesData:
    labels = [comparison.right.condition_label for comparison in comparisons]
    return SeriesData(
        title="Symnav progression",
        labels=labels,
        left=[comparison.effectiveness.left_mean_f2p for comparison in comparisons],
        right=[comparison.effectiveness.right_mean_f2p for comparison in comparisons],
        left_label="baseline",
        right_label="symnav",
    )


def _task_f2p(cells, task: str) -> float:
    values = [float(cell.rewards.get("f2p", 0.0)) for cell in cells if cell.identity.task == task]
    return sum(values) / len(values) if values else 0.0


def _command_count(cells, label: str) -> float:
    total = 0
    for cell in cells:
        if label == "symnav":
            total += sum(cell.command_counts.get("symnav", {}).values())
        else:
            total += int(cell.command_counts.get(label, 0))
    return float(total)
