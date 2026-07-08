from __future__ import annotations

import json

from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.cell import Cell
from symnav_bench.cells.normalize import HarnessMeta, normalize_trial
from symnav_bench.run_spec import AgentSpec


def test_normalize_trial_writes_cell_and_commands(tmp_path) -> None:
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "result.json").write_text(
        json.dumps(
            {
                "agent_result": {
                    "n_input_tokens": 1,
                    "n_cache_tokens": 2,
                    "n_output_tokens": 3,
                    "cost_usd": 0.4,
                    "peak_context_tokens": 5,
                    "n_agent_steps": 6,
                },
                "verifier_result": {"rewards": {"f2p": 1.0, "p2p": 0.5}},
                "agent_info": {"version": "v1"},
                "phase_timings": {"agent": 10},
            }
        ),
        encoding="utf-8",
    )
    (trial / "agent" / "trajectory.json").write_text(
        json.dumps({"steps": [{"tool_calls": [{"function_name": "exec_command", "arguments": {"cmd": "rg Foo"}}]}]}),
        encoding="utf-8",
    )
    identity = CellIdentity(AgentSpec("codex", "m", "e"), "stock", "task", 0)
    cell = normalize_trial(
        trial,
        identity,
        HarnessMeta("image", "pier", "deep", None),
        "completed",
        None,
        tmp_path / "out",
    )
    assert cell.solved is True
    assert cell.usage["cost_usd_imputed"] == 0.4
    assert cell.command_counts["search"] == 1
    loaded = Cell.load(tmp_path / "out" / identity.dirname() / "cell.json")
    assert loaded.identity == identity


def test_missing_trial_becomes_error(tmp_path) -> None:
    identity = CellIdentity(AgentSpec("codex", "m", "e"), "stock", "task", 0)
    cell = normalize_trial(None, identity, HarnessMeta("image", "pier", "deep", None), "completed", None, tmp_path)
    assert cell.status == "error"
    assert cell.error == "missing or empty trial result"
