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
