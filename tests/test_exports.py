from __future__ import annotations

import csv
import json
from dataclasses import replace
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
        if table == "attempts":
            expected = [{**row, "benchmark": "deepswe", "tier": None} for row in expected]
        csv_rows = read_csv_rows(tmp_path / "csv" / f"{table}.csv")
        parquet_rows = read_parquet_rows(tmp_path / "parquet" / f"{table}.parquet")
        assert csv_rows == expected
        assert parquet_rows == expected


def test_attempt_exports_join_benchmark_and_task_tier(tmp_path: Path) -> None:
    payload = replace(
        fixture_payload(),
        study={
            "id": "study",
            "benchmark": "swe-polybench",
            "benchmark_source_revision": "a" * 40,
        },
        tasks=(
            {
                "configuration_id": "codex-terra",
                "condition": "stock",
                "task": "task-a",
                "tier": "high",
                "metrics": {"performance_score": 0.5},
            },
        ),
        attempts=(
            {"attempt_id": "attempt-1", "task": "task-a", "outcome": "passed"},
            {"attempt_id": "attempt-2", "task": "task-b", "outcome": "failed"},
        ),
    )
    writer = AnalysisExportWriter()

    writer.write_json(payload, tmp_path / "analysis.json")
    writer.write_csv(payload, tmp_path / "csv")
    writer.write_parquet(payload, tmp_path / "parquet")

    expected = [
        {
            "attempt_id": "attempt-1",
            "task": "task-a",
            "outcome": "passed",
            "benchmark": "swe-polybench",
            "tier": "high",
        },
        {
            "attempt_id": "attempt-2",
            "task": "task-b",
            "outcome": "failed",
            "benchmark": "swe-polybench",
            "tier": None,
        },
    ]
    assert read_csv_rows(tmp_path / "csv" / "attempts.csv") == expected
    assert read_parquet_rows(tmp_path / "parquet" / "attempts.parquet") == expected
    exported = json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))
    assert exported["attempts"] == list(payload.attempts)


def read_csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(row["row_json"]) for row in csv.DictReader(stream)]


def read_parquet_rows(path: Path) -> list[dict]:
    return [
        json.loads(value)
        for value in parquet.read_table(path)["row_json"].to_pylist()
    ]


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
