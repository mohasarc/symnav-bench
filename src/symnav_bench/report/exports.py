from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyarrow as arrow
import pyarrow.parquet as parquet

from symnav_bench.report.dashboard_payload import DashboardPayload


EXPORT_TABLES = (
    "attempts",
    "comparisons",
    "configurations",
    "official_references",
    "tasks",
    "versions",
)


class AnalysisExportWriter:
    def write_json(self, payload: DashboardPayload, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def write_csv(self, payload: DashboardPayload, out_dir: Path) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for table_name, rows in self._tables(payload):
            path = out_dir / f"{table_name}.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["row_json"])
                writer.writeheader()
                writer.writerows(
                    {"row_json": _canonical_json(row)} for row in rows
                )
            paths.append(path)
        return paths

    def write_parquet(self, payload: DashboardPayload, out_dir: Path) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for table_name, rows in self._tables(payload):
            path = out_dir / f"{table_name}.parquet"
            parquet.write_table(
                arrow.table(
                    {"row_json": [_canonical_json(row) for row in rows]},
                    schema=arrow.schema([("row_json", arrow.string())]),
                ),
                path,
                compression="zstd",
            )
            paths.append(path)
        return paths

    def _tables(
        self,
        payload: DashboardPayload,
    ) -> tuple[tuple[str, tuple[dict[str, Any], ...]], ...]:
        return tuple(
            (
                table_name,
                _attempt_provenance_rows(payload)
                if table_name == "attempts"
                else getattr(payload, table_name),
            )
            for table_name in EXPORT_TABLES
        )


def _attempt_provenance_rows(payload: DashboardPayload) -> tuple[dict[str, Any], ...]:
    benchmark = payload.study.get("benchmark", "deepswe")
    tier_by_task = {
        task_row.get("task"): task_row.get("tier")
        for task_row in payload.tasks
    }
    return tuple(
        {
            **row,
            "benchmark": benchmark,
            "tier": tier_by_task.get(row.get("task")),
        }
        for row in payload.attempts
    )


def _canonical_json(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"))
