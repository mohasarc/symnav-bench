from __future__ import annotations

import json
from pathlib import Path

import pytest

from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.cell import Cell
from symnav_bench.report.render import write_report
from symnav_bench.report.study_dataset import import_legacy_cells
from symnav_bench.run_spec import AgentSpec


def test_legacy_cell_loader_rejects_unknown_schema(tmp_path: Path) -> None:
    cell = legacy_cell(True)
    data = cell.to_json()
    data["schema_version"] = 999
    path = tmp_path / "cell.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported legacy cell schema version 999"):
        Cell.load(path)


def test_legacy_import_derives_binary_result_and_marks_missing_metadata() -> None:
    cells_dir = Path(__file__).parent / "fixtures" / "legacy"

    legacy = import_legacy_cells(cells_dir)

    assert len(legacy.cells) == 1
    assert legacy.cells[0].solved is False
    assert any("missing metadata" in warning for warning in legacy.warnings)


def test_legacy_import_stays_outside_study_configuration_groups(
    tmp_path: Path,
) -> None:
    cell = legacy_cell(True)
    path = tmp_path / cell.identity.dirname()
    path.mkdir()
    (path / "cell.json").write_text(json.dumps(cell.to_json()), encoding="utf-8")

    legacy = import_legacy_cells(tmp_path)

    assert type(legacy).__name__ == "LegacyDataset"
    assert not hasattr(legacy, "configurations")


def test_legacy_report_is_labeled_and_has_no_study_statistics(tmp_path: Path) -> None:
    cell = legacy_cell(True)
    cells_dir = tmp_path / "cells" / cell.identity.dirname()
    cells_dir.mkdir(parents=True)
    (cells_dir / "cell.json").write_text(
        json.dumps(cell.to_json()),
        encoding="utf-8",
    )

    write_report(import_legacy_cells(tmp_path / "cells"), tmp_path / "report")

    markdown = (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert "## Legacy" in markdown
    assert "excluded from study statistics" in markdown
    assert "performance score" not in markdown
    assert (tmp_path / "report" / "legacy-cells.csv").exists()


def legacy_cell(solved: bool) -> Cell:
    return Cell(
        identity=CellIdentity(AgentSpec("codex", "model", "medium"), "stock", "task", 0),
        status="completed",
        error=None,
        solved=solved,
        rewards={"f2p": 1.0 if solved else 0.0},
        usage={"cost_usd_imputed": 1.0},
        timing={},
        agent_version=None,
        harness={},
        command_counts={},
    )
