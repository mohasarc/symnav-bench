from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from symnav_bench.report.chart_data import SeriesData, efficiency_distributions, paired_f2p_series, progression_series, substitution_series
from symnav_bench.report.comparison import ArmComparison


def render_all(comparisons: list[ArmComparison], out_dir: Path) -> list[Path]:
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, comparison in enumerate(comparisons):
        paths.append(_render_bar(paired_f2p_series(comparison), charts_dir / f"paired-f2p-{index}.png"))
        paths.append(_render_bar(efficiency_distributions(comparison), charts_dir / f"efficiency-{index}.png"))
        paths.append(_render_bar(substitution_series(comparison), charts_dir / f"substitution-{index}.png"))
    if comparisons:
        paths.append(_render_line(progression_series(comparisons), charts_dir / "progression.png"))
    return paths


def _render_bar(data: SeriesData, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    xs = list(range(len(data.labels)))
    ax.bar([x - 0.2 for x in xs], data.left, width=0.4, label=data.left_label)
    ax.bar([x + 0.2 for x in xs], data.right, width=0.4, label=data.right_label)
    ax.set_title(data.title)
    ax.set_xticks(xs, data.labels, rotation=30, ha="right")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _render_line(data: SeriesData, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    xs = list(range(len(data.labels)))
    ax.plot(xs, data.left, marker="o", label=data.left_label)
    ax.plot(xs, data.right, marker="o", label=data.right_label)
    ax.set_title(data.title)
    ax.set_xticks(xs, data.labels, rotation=30, ha="right")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
