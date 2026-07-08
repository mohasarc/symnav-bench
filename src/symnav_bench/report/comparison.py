from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from symnav_bench.cells.cell import Cell
from symnav_bench.report.cell_set import ArmKey, CellSet


@dataclass(frozen=True)
class EffectivenessStats:
    left_mean_f2p: float
    right_mean_f2p: float
    left_solved_rate: float
    right_solved_rate: float
    task_wins: dict[str, str]


@dataclass(frozen=True)
class EfficiencyStats:
    left_cost: float | None
    right_cost: float | None
    left_steps: float | None
    right_steps: float | None
    left_tokens: float | None
    right_tokens: float | None


@dataclass(frozen=True)
class ArmComparison:
    left: ArmKey
    right: ArmKey
    effectiveness: EffectivenessStats
    matched_tasks: list[str]
    efficiency: EfficiencyStats
    holes: list[str]
    agent_version_mismatch: bool
    left_cells: list[Cell]
    right_cells: list[Cell]


def planned_comparisons(cells: CellSet, compare_labels: list[str] | None = None) -> list[ArmComparison]:
    arms = cells.arms()
    comparisons: list[ArmComparison] = []
    if compare_labels:
        selected = [key for key in arms if key.condition_label in compare_labels]
        for index, left in enumerate(selected):
            for right in selected[index + 1 :]:
                if _same_agent(left, right):
                    comparisons.append(compare(cells, left, right))
        return comparisons
    for stock in [key for key in arms if key.condition_label == "stock"]:
        for symnav in [key for key in arms if key.condition_label.startswith("symnav@") and _same_agent(stock, key)]:
            comparisons.append(compare(cells, stock, symnav))
    return comparisons


def compare(cells: CellSet, left: ArmKey, right: ArmKey) -> ArmComparison:
    arms = cells.arms()
    left_cells = arms.get(left, [])
    right_cells = arms.get(right, [])
    matched_tasks = _matched_tasks(left_cells, right_cells)
    return ArmComparison(
        left=left,
        right=right,
        effectiveness=_effectiveness(left_cells, right_cells),
        matched_tasks=matched_tasks,
        efficiency=_efficiency(left_cells, right_cells, matched_tasks),
        holes=_holes(left_cells, right_cells),
        agent_version_mismatch=_agent_versions(left_cells) != _agent_versions(right_cells),
        left_cells=left_cells,
        right_cells=right_cells,
    )


def _same_agent(left: ArmKey, right: ArmKey) -> bool:
    return (left.agent, left.model, left.effort) == (right.agent, right.model, right.effort)


def _matched_tasks(left: list[Cell], right: list[Cell]) -> list[str]:
    left_solved = {cell.identity.task for cell in left if cell.solved}
    right_solved = {cell.identity.task for cell in right if cell.solved}
    return sorted(left_solved & right_solved)


def _effectiveness(left: list[Cell], right: list[Cell]) -> EffectivenessStats:
    tasks = sorted({cell.identity.task for cell in left + right})
    wins: dict[str, str] = {}
    for task in tasks:
        left_score = _task_mean(left, task, "f2p")
        right_score = _task_mean(right, task, "f2p")
        wins[task] = "tie" if left_score == right_score else ("left" if left_score > right_score else "right")
    return EffectivenessStats(
        left_mean_f2p=_mean_reward(left, "f2p"),
        right_mean_f2p=_mean_reward(right, "f2p"),
        left_solved_rate=_solved_rate(left),
        right_solved_rate=_solved_rate(right),
        task_wins=wins,
    )


def _efficiency(left: list[Cell], right: list[Cell], tasks: list[str]) -> EfficiencyStats:
    left_matched = [cell for cell in left if cell.identity.task in tasks and cell.solved]
    right_matched = [cell for cell in right if cell.identity.task in tasks and cell.solved]
    return EfficiencyStats(
        left_cost=_mean_usage(left_matched, "cost_usd_imputed"),
        right_cost=_mean_usage(right_matched, "cost_usd_imputed"),
        left_steps=_mean_usage(left_matched, "n_agent_steps"),
        right_steps=_mean_usage(right_matched, "n_agent_steps"),
        left_tokens=_mean_tokens(left_matched),
        right_tokens=_mean_tokens(right_matched),
    )


def _holes(left: list[Cell], right: list[Cell]) -> list[str]:
    holes: list[str] = []
    left_tasks = {cell.identity.task for cell in left}
    right_tasks = {cell.identity.task for cell in right}
    for task in sorted(left_tasks ^ right_tasks):
        holes.append(f"missing arm for {task}")
    for cell in left + right:
        if cell.status != "completed":
            holes.append(f"{cell.identity.dirname()} status={cell.status}")
    return holes


def _agent_versions(cells: list[Cell]) -> set[str | None]:
    return {cell.agent_version for cell in cells}


def _mean_reward(cells: list[Cell], key: str) -> float:
    values = [_float(cell.rewards.get(key)) for cell in cells]
    return mean(values) if values else 0.0


def _task_mean(cells: list[Cell], task: str, key: str) -> float:
    values = [_float(cell.rewards.get(key)) for cell in cells if cell.identity.task == task]
    return mean(values) if values else 0.0


def _solved_rate(cells: list[Cell]) -> float:
    return mean([1.0 if cell.solved else 0.0 for cell in cells]) if cells else 0.0


def _mean_usage(cells: list[Cell], key: str) -> float | None:
    values = [_float(cell.usage.get(key)) for cell in cells if cell.usage.get(key) is not None]
    return mean(values) if values else None


def _mean_tokens(cells: list[Cell]) -> float | None:
    values = [
        _float(cell.usage.get("n_input_tokens")) + _float(cell.usage.get("n_output_tokens"))
        for cell in cells
        if cell.usage.get("n_input_tokens") is not None and cell.usage.get("n_output_tokens") is not None
    ]
    return mean(values) if values else None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
