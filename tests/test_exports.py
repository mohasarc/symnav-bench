from __future__ import annotations

import csv
import json
from pathlib import Path

import pyarrow.parquet as parquet

from symnav_bench.report.dashboard_payload import DashboardPayload
from symnav_bench.report.exports import AnalysisExportWriter


def test_json_csv_and_parquet_export_same_canonical_rows(tmp_path: Path) -> None:
    payload = fixture_payload()
    writer = AnalysisExportWriter()

    writer.write_json(payload, tmp_path / "analysis.json")
    csv_paths = writer.write_csv(payload, tmp_path / "csv")
    parquet_paths = writer.write_parquet(payload, tmp_path / "parquet")

    exported = json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))
    assert exported["schema_version"] == 1
    assert exported["study"]["id"] == "study"
    assert exported["tasks"] == list(payload.tasks)

    assert [path.name for path in csv_paths] == [
        "attempts.csv",
        "comparisons.csv",
        "configurations.csv",
        "official_references.csv",
        "tasks.csv",
        "versions.csv",
    ]
    assert [path.name for path in parquet_paths] == [
        "attempts.parquet",
        "comparisons.parquet",
        "configurations.parquet",
        "official_references.parquet",
        "tasks.parquet",
        "versions.parquet",
    ]
    for table in (
        "attempts",
        "comparisons",
        "configurations",
        "official_references",
        "tasks",
        "versions",
    ):
        expected = list(getattr(payload, table))
        with (tmp_path / "csv" / f"{table}.csv").open(encoding="utf-8") as stream:
            csv_rows = [json.loads(row["row_json"]) for row in csv.DictReader(stream)]
        parquet_rows = [
            json.loads(value)
            for value in parquet.read_table(
                tmp_path / "parquet" / f"{table}.parquet"
            )["row_json"].to_pylist()
        ]
        assert csv_rows == expected
        assert parquet_rows == expected


def fixture_payload() -> DashboardPayload:
    return DashboardPayload(
        schema_version=1,
        study={"id": "study"},
        coverage={"planned_slots": 8, "scored_slots": 7},
        configurations=(
            {
                "id": "codex-terra",
                "condition": "stock",
                "metrics": {"performance_score": 0.5},
            },
        ),
        comparisons=(
            {
                "configuration_id": "codex-terra:symnav",
                "uplift": {"value": 0.25, "lower_95": 0.0, "upper_95": 0.5},
            },
        ),
        tasks=(
            {
                "configuration_id": "codex-terra",
                "condition": "stock",
                "task": "task-a",
                "metrics": {"performance_score": 0.5},
            },
        ),
        versions=(),
        official_references=(),
        attempts=(
            {
                "attempt_id": "attempt-1",
                "outcome": "passed",
                "usage": {"cost_usd_imputed": 1.25},
            },
        ),
        warnings=("one warning",),
    )
