from __future__ import annotations

import csv
from pathlib import Path

from symnav_bench.report.dashboard_payload import build_dashboard_payload
from symnav_bench.report.dashboard_writer import StaticDashboardWriter
from symnav_bench.report.exports import AnalysisExportWriter
from symnav_bench.report.statistics import ConditionComparison
from symnav_bench.report.statistics import compare_condition_to_stock
from symnav_bench.report.study_dataset import (
    ConfigurationMetrics,
    LegacyDataset,
    StudyDataset,
    compute_configuration_metrics,
)


def write_report(dataset: StudyDataset | LegacyDataset, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(dataset, LegacyDataset):
        _write_legacy_report(dataset, out_dir)
        return
    metrics = [
        compute_configuration_metrics(dataset, key)
        for key in dataset.configurations()
    ]
    comparisons = _condition_comparisons(dataset, metrics)
    payload = build_dashboard_payload(
        dataset,
        metrics,
        comparisons,
        (),
        None,
    )
    StaticDashboardWriter().write(payload, out_dir)
    exports = AnalysisExportWriter()
    exports.write_json(payload, out_dir / "analysis-v1.json")
    exports.write_csv(payload, out_dir / "exports" / "csv")
    exports.write_parquet(payload, out_dir / "exports" / "parquet")


def _condition_comparisons(
    dataset: StudyDataset,
    metrics: list[ConfigurationMetrics],
) -> tuple[ConditionComparison, ...]:
    comparisons: list[ConditionComparison] = []
    for configuration in dataset.manifest.configurations:
        matching = [
            item
            for item in metrics
            if item.key.agent == configuration.spec.agent
            and item.key.model == configuration.spec.model
            and item.key.effort == configuration.spec.effort
            and item.key.agent_version == configuration.agent_version
        ]
        stock = next((item for item in matching if item.key.condition == "stock"), None)
        if stock is None:
            continue
        for treatment in matching:
            if treatment.key.condition == "stock":
                continue
            practical_threshold = dataset.manifest.protocol.practical_uplift_points
            if practical_threshold > 1:
                practical_threshold /= 100
            comparisons.append(
                compare_condition_to_stock(
                    stock,
                    treatment,
                    seed=dataset.manifest.protocol.randomization_seed,
                    practical_threshold=practical_threshold,
                    study_id=dataset.manifest.id,
                    symnav_revision=dataset.manifest.protocol.symnav,
                    suite_fingerprint=dataset.suite.fingerprint,
                )
            )
    return tuple(comparisons)


def _write_study_markdown(
    dataset: StudyDataset,
    metrics: list[ConfigurationMetrics],
    path: Path,
) -> None:
    lines = [
        "# symnav bench report",
        "",
        f"Study: `{dataset.manifest.id}`",
        "",
        "Costs are `cost_usd_imputed` from Pier output.",
        "",
    ]
    lines.extend(f"- Warning: {warning}" for warning in dataset.warnings)
    if dataset.warnings:
        lines.append("")
    for item in metrics:
        lines.extend(
            [
                f"## {_configuration_label(item)}",
                "",
                f"Coverage: {item.coverage.scored_slots}/{item.coverage.planned_slots} scored slots; "
                f"{item.coverage.complete_tasks}/{item.coverage.total_tasks} complete tasks.",
                "",
                f"Status: {_coverage_status(item)}.",
                "",
                "| metric | value |",
                "| --- | ---: |",
                f"| performance score | {_format(item.performance_score)} |",
                f"| mean f2p | {_format(item.mean_f2p)} |",
                f"| mean p2p | {_format(item.mean_p2p)} |",
                f"| mean partial | {_format(item.mean_partial)} |",
                f"| total cost | {_format(item.total_cost)} |",
                f"| cost per success | {_format(item.cost_per_success)} |",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_configurations_csv(
    metrics: list[ConfigurationMetrics],
    path: Path,
) -> None:
    fieldnames = [
        "configuration",
        "condition",
        "bundle_hash",
        "planned_slots",
        "scored_slots",
        "complete_tasks",
        "total_tasks",
        "provisional",
        "pilot",
        "performance_score",
        "mean_f2p",
        "mean_p2p",
        "mean_partial",
        "total_cost",
        "cost_per_success",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for item in metrics:
            writer.writerow(
                {
                    "configuration": f"{item.key.agent}:{item.key.model}:{item.key.effort}:{item.key.agent_version}",
                    "condition": item.key.condition,
                    "bundle_hash": item.key.bundle_hash,
                    "planned_slots": item.coverage.planned_slots,
                    "scored_slots": item.coverage.scored_slots,
                    "complete_tasks": item.coverage.complete_tasks,
                    "total_tasks": item.coverage.total_tasks,
                    "provisional": item.coverage.provisional,
                    "pilot": item.coverage.pilot,
                    "performance_score": item.performance_score,
                    "mean_f2p": item.mean_f2p,
                    "mean_p2p": item.mean_p2p,
                    "mean_partial": item.mean_partial,
                    "total_cost": item.total_cost,
                    "cost_per_success": item.cost_per_success,
                }
            )


def _write_tasks_csv(metrics: list[ConfigurationMetrics], path: Path) -> None:
    fieldnames = [
        "configuration",
        "condition",
        "task",
        "scored_trials",
        "pass_fraction",
        "mean_f2p",
        "mean_p2p",
        "mean_partial",
        "mean_cost",
        "median_cost",
        "mean_output_tokens",
        "mean_steps",
        "mean_duration_seconds",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for item in metrics:
            for task in item.tasks:
                writer.writerow(
                    {
                        "configuration": f"{item.key.agent}:{item.key.model}:{item.key.effort}:{item.key.agent_version}",
                        "condition": item.key.condition,
                        "task": task.task,
                        "scored_trials": task.scored_trials,
                        "pass_fraction": task.pass_fraction,
                        "mean_f2p": task.mean_f2p,
                        "mean_p2p": task.mean_p2p,
                        "mean_partial": task.mean_partial,
                        "mean_cost": task.mean_cost,
                        "median_cost": task.median_cost,
                        "mean_output_tokens": task.mean_output_tokens,
                        "mean_steps": task.mean_steps,
                        "mean_duration_seconds": task.mean_duration_seconds,
                    }
                )


def _write_legacy_report(dataset: LegacyDataset, out_dir: Path) -> None:
    lines = [
        "# symnav bench report",
        "",
        "## Legacy",
        "",
        "Legacy cells are visible for audit and excluded from study statistics.",
        "",
    ]
    lines.extend(f"- Warning: {warning}" for warning in dataset.warnings)
    (out_dir / "report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    with (out_dir / "legacy-cells.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["cell", "status", "solved", "f2p", "cost_usd_imputed"],
        )
        writer.writeheader()
        for cell in dataset.cells:
            writer.writerow(
                {
                    "cell": cell.identity.dirname(),
                    "status": cell.status,
                    "solved": cell.solved,
                    "f2p": cell.rewards.get("f2p"),
                    "cost_usd_imputed": cell.usage.get("cost_usd_imputed"),
                }
            )


def _configuration_label(item: ConfigurationMetrics) -> str:
    return (
        f"{item.key.agent}:{item.key.model}:{item.key.effort}:"
        f"{item.key.agent_version}:{item.key.condition}"
    )


def _coverage_status(item: ConfigurationMetrics) -> str:
    if item.coverage.pilot:
        return "pilot"
    if item.coverage.provisional:
        return "provisional"
    return "complete"


def _format(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"
