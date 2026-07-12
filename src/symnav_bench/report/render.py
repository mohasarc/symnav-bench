from __future__ import annotations

import csv
from pathlib import Path

from symnav_bench.report.dashboard_payload import build_dashboard_payload
from symnav_bench.report.dashboard_writer import StaticDashboardWriter
from symnav_bench.report.exports import AnalysisExportWriter
from symnav_bench.report.report_inputs import load_report_inputs
from symnav_bench.report.statistics import ConditionComparison
from symnav_bench.report.statistics import compare_condition_to_stock
from symnav_bench.report.study_dataset import (
    ConfigurationMetrics,
    LegacyDataset,
    StudyDataset,
    compute_configuration_metrics,
)
from symnav_bench.report.versions import VersionComparison
from symnav_bench.report.versions import compare_study_versions


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
    inputs = load_report_inputs(dataset)
    versions = _version_comparisons(
        dataset,
        comparisons,
        inputs.compatible_studies,
    )
    payload = build_dashboard_payload(
        dataset,
        metrics,
        comparisons,
        versions,
        inputs.official_reference,
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


def _version_comparisons(
    dataset: StudyDataset,
    current: tuple[ConditionComparison, ...],
    compatible_studies: tuple[StudyDataset, ...],
) -> tuple[VersionComparison, ...]:
    versions: list[VersionComparison] = []
    for compatible in compatible_studies:
        metrics = [
            compute_configuration_metrics(compatible, key)
            for key in compatible.configurations()
        ]
        previous = _condition_comparisons(compatible, metrics)
        for left in previous:
            right = next(
                (
                    item
                    for item in current
                    if _comparison_identity(item) == _comparison_identity(left)
                ),
                None,
            )
            if left.uplift is None or right is None or right.uplift is None:
                continue
            versions.append(
                compare_study_versions(
                    left,
                    right,
                    seed=dataset.manifest.protocol.randomization_seed,
                )
            )
    return tuple(versions)


def _comparison_identity(comparison: ConditionComparison) -> tuple[str, ...]:
    key = comparison.treatment.key
    return (
        key.agent,
        key.model,
        key.effort,
        key.agent_version,
        key.condition,
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
