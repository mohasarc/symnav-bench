from __future__ import annotations

import csv
from pathlib import Path

from symnav_bench.report.cell_set import CellSet
from symnav_bench.report.charts import render_all
from symnav_bench.report.comparison import ArmComparison


def write_report(comparisons: list[ArmComparison], cells: CellSet, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    chart_paths = render_all(comparisons, out_dir)
    _write_markdown(comparisons, cells, chart_paths, out_dir / "report.md", out_dir)
    _write_csv(comparisons, out_dir / "comparisons.csv")
    _write_cells_csv(cells, out_dir / "cells.csv")


def _write_markdown(
    comparisons: list[ArmComparison],
    cells: CellSet,
    chart_paths: list[Path],
    path: Path,
    out_dir: Path,
) -> None:
    lines = ["# symnav bench report", "", "Costs are `cost_usd_imputed` from Pier output.", ""]
    for warning in cells.warnings:
        lines.append(f"- Warning: {warning}")
    for comparison in comparisons:
        lines.extend(
            [
                f"## {comparison.left.label} vs {comparison.right.label}",
                "",
                "| metric | left | right |",
                "| --- | ---: | ---: |",
                f"| mean f2p | {comparison.effectiveness.left_mean_f2p:.3f} | {comparison.effectiveness.right_mean_f2p:.3f} |",
                f"| solved rate | {comparison.effectiveness.left_solved_rate:.3f} | {comparison.effectiveness.right_solved_rate:.3f} |",
                f"| paired tasks | {len(comparison.paired_tasks)} | {len(comparison.paired_tasks)} |",
                f"| matched solved tasks | {len(comparison.matched_tasks)} | {len(comparison.matched_tasks)} |",
                f"| matched cost_usd_imputed | {_fmt(comparison.efficiency.left_cost)} | {_fmt(comparison.efficiency.right_cost)} |",
                f"| matched tokens | {_fmt(comparison.efficiency.left_tokens)} | {_fmt(comparison.efficiency.right_tokens)} |",
                f"| matched steps | {_fmt(comparison.efficiency.left_steps)} | {_fmt(comparison.efficiency.right_steps)} |",
                "",
                "Matched-set efficiency only includes tasks solved by both arms.",
                "",
            ]
        )
        if comparison.holes:
            lines.append("Holes:")
            lines.extend(f"- {hole}" for hole in comparison.holes)
            lines.append("")
        if comparison.agent_version_mismatch:
            lines.append("Agent versions differ across compared arms.")
            lines.append("")
    for chart in chart_paths:
        lines.append(f"![{chart.stem}]({chart.relative_to(out_dir)})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csv(comparisons: list[ArmComparison], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "left",
                "right",
                "left_mean_f2p",
                "right_mean_f2p",
                "paired_tasks",
                "matched_tasks",
                "left_cost_usd_imputed",
                "right_cost_usd_imputed",
            ],
        )
        writer.writeheader()
        for comparison in comparisons:
            writer.writerow(
                {
                    "left": comparison.left.label,
                    "right": comparison.right.label,
                    "left_mean_f2p": comparison.effectiveness.left_mean_f2p,
                    "right_mean_f2p": comparison.effectiveness.right_mean_f2p,
                    "paired_tasks": " ".join(comparison.paired_tasks),
                    "matched_tasks": " ".join(comparison.matched_tasks),
                    "left_cost_usd_imputed": comparison.efficiency.left_cost,
                    "right_cost_usd_imputed": comparison.efficiency.right_cost,
                }
            )


def _write_cells_csv(cells: CellSet, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["dirname", "status", "solved", "f2p", "cost_usd_imputed"])
        writer.writeheader()
        for cell in cells.cells:
            writer.writerow(
                {
                    "dirname": cell.identity.dirname(),
                    "status": cell.status,
                    "solved": cell.solved,
                    "f2p": cell.rewards.get("f2p"),
                    "cost_usd_imputed": cell.usage.get("cost_usd_imputed"),
                }
            )


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"
