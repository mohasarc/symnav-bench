from __future__ import annotations

import json

import pytest

from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.cell import Cell
from symnav_bench.report.cell_set import ArmKey, CellSet
from symnav_bench.report.comparison import compare, planned_comparisons
from symnav_bench.report.render import write_report
from symnav_bench.run_spec import AgentSpec


def test_cell_set_loads_by_cell_json_and_groups_arms(tmp_path) -> None:
    cell = _cell("stock", "task", True)
    path = tmp_path / "weird-dir"
    path.mkdir()
    (path / "cell.json").write_text(json.dumps(cell.to_json()), encoding="utf-8")
    loaded = CellSet.load(tmp_path)
    assert len(loaded.cells) == 1
    assert list(loaded.arms())[0].condition_label == "stock"


def test_legacy_cell_loader_rejects_unknown_schema(tmp_path) -> None:
    cell = _cell("stock", "task", True)
    data = cell.to_json()
    data["schema_version"] = 999
    path = tmp_path / "cell.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported legacy cell schema version 999"):
        Cell.load(path)


def test_cell_set_warns_when_f2p_solved_but_p2p_regresses(tmp_path) -> None:
    cell = _cell("stock", "task", True)
    cell.rewards["p2p"] = 0.5
    path = tmp_path / cell.identity.dirname()
    path.mkdir()
    (path / "cell.json").write_text(json.dumps(cell.to_json()), encoding="utf-8")
    loaded = CellSet.load(tmp_path)
    assert loaded.warnings == (
        f"{cell.identity.dirname()} has f2p=1.0 but p2p=0.5",
    )


def test_compare_uses_matched_solved_set() -> None:
    left = ArmKey("codex", "m", "e", "stock")
    right = ArmKey("codex", "m", "e", "symnav@abc")
    cells = CellSet(
        [
            _cell("stock", "a", True, cost=2, steps=10),
            _cell("stock", "b", False, cost=9, steps=99),
            _cell("symnav@abc", "a", True, cost=1, steps=5),
        ]
    )
    result = compare(cells, left, right)
    assert result.paired_tasks == ["a"]
    assert result.matched_tasks == ["a"]
    assert result.efficiency.left_cost == 2
    assert result.efficiency.right_steps == 5
    assert result.holes == ["missing arm for b"]


def test_planned_comparisons_include_command_specific_symnav_arms() -> None:
    cells = CellSet(
        [
            _cell("stock", "a", False),
            _cell("symnav-overview@abc", "a", True),
            _cell("symnav-context@abc", "a", True),
        ]
    )
    labels = [comparison.right.condition_label for comparison in planned_comparisons(cells)]
    assert labels == ["symnav-overview@abc", "symnav-context@abc"]


def test_report_writes_markdown_csvs_and_charts(tmp_path) -> None:
    cells = CellSet([_cell("stock", "a", True), _cell("symnav@abc", "a", True)])
    comparison = compare(cells, ArmKey("codex", "m", "e", "stock"), ArmKey("codex", "m", "e", "symnav@abc"))
    write_report([comparison], cells, tmp_path / "report")
    assert "Matched-set efficiency" in (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert (tmp_path / "report" / "comparisons.csv").exists()
    assert any((tmp_path / "report" / "charts").glob("*.png"))


def _cell(condition: str, task: str, solved: bool, cost: float = 1, steps: int = 1) -> Cell:
    return Cell(
        identity=CellIdentity(AgentSpec("codex", "m", "e"), condition, task, 0),
        status="completed",
        error=None,
        solved=solved,
        rewards={"f2p": 1.0 if solved else 0.0},
        usage={"cost_usd_imputed": cost, "n_agent_steps": steps, "n_input_tokens": 1, "n_output_tokens": 1},
        timing={},
        agent_version="v1",
        harness={},
        command_counts={"symnav": {"resolve": 1}, "search": 1, "read": 1, "other": 1, "timeouts": 0},
    )
