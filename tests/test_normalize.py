from __future__ import annotations

import json
from pathlib import Path

from symnav_bench.batch_plan import TrialSlot
from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.attempt import AttemptIdentity, AttemptRecord
from symnav_bench.cells.cell import Cell
from symnav_bench.cells.normalize import HarnessMeta, normalize_attempt, normalize_trial
from symnav_bench.run.job_config import HarnessIdentity
from symnav_bench.run_spec import AgentSpec


TRAJECTORY_FIXTURES = Path(__file__).parent / "fixtures" / "trajectories"


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
        json.dumps(
            {
                "steps": [
                    {"tool_calls": [{"function_name": "exec_command", "arguments": {"cmd": "rg Foo"}}]},
                    {
                        "tool_calls": [
                            {
                                "function_name": "exec_command",
                                "arguments": {"cmd": "sed -n '1,80p' /app/.agents/skills/symnav/SKILL.md"},
                            }
                        ]
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (trial / "agent" / "codex.txt").write_text("agent stderr", encoding="utf-8")
    (trial / "agent" / "sessions" / "sessions").mkdir(parents=True)
    (trial / "agent" / "sessions" / "sessions" / "ignored.jsonl").write_text("large", encoding="utf-8")
    (trial / "exception.txt").write_text("NonZeroAgentExitCodeError", encoding="utf-8")
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
    assert cell.command_counts["symnav_skill_reads"] == 1
    loaded = Cell.load(tmp_path / "out" / identity.dirname() / "cell.json")
    assert loaded.identity == identity
    raw_dir = tmp_path / "out" / identity.dirname() / "raw"
    assert (raw_dir / "result.json").is_file()
    assert (raw_dir / "exception.txt").read_text(encoding="utf-8") == "NonZeroAgentExitCodeError"
    assert (raw_dir / "agent" / "codex.txt").read_text(encoding="utf-8") == "agent stderr"
    assert not (raw_dir / "agent" / "sessions").exists()


def test_normalize_trial_writes_workspace_git_artifacts(tmp_path) -> None:
    trial = tmp_path / "trial"
    workspace = trial / "workspace"
    (trial / "agent").mkdir(parents=True)
    workspace.mkdir(parents=True)
    (workspace / ".git").mkdir()
    (workspace / "changed.ts").write_text("new", encoding="utf-8")
    (trial / "result.json").write_text(
        json.dumps({"verifier_result": {"rewards": {"f2p": 0.0}}}),
        encoding="utf-8",
    )
    (trial / "agent" / "trajectory.json").write_text('{"steps":[]}', encoding="utf-8")
    identity = CellIdentity(AgentSpec("codex", "m", "e"), "stock", "task", 0)

    normalize_trial(
        trial,
        identity,
        HarnessMeta("image", "pier", "deep", None),
        "completed",
        None,
        tmp_path / "out",
    )

    workspace_artifacts = tmp_path / "out" / identity.dirname() / "raw" / "workspace" / "workspace"
    assert (workspace_artifacts / "status-short.txt").is_file()
    assert (workspace_artifacts / "diff.patch").is_file()
    assert (workspace_artifacts / "diff-cached.patch").is_file()
    assert (workspace_artifacts / "diff-stat.txt").is_file()


def test_normalize_trial_counts_claude_symnav_skill_tool(tmp_path) -> None:
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "result.json").write_text(
        json.dumps({"verifier_result": {"rewards": {"f2p": 0.0}}}),
        encoding="utf-8",
    )
    (trial / "agent" / "trajectory.json").write_text(
        json.dumps({"steps": [{"tool_calls": [{"function_name": "Skill", "arguments": {"skill": "symnav"}}]}]}),
        encoding="utf-8",
    )
    identity = CellIdentity(AgentSpec("claude", "m", "e"), "symnav@abc", "task", 0)

    cell = normalize_trial(
        trial,
        identity,
        HarnessMeta("image", "pier", "deep", "abc"),
        "completed",
        None,
        tmp_path / "out",
    )

    assert cell.command_counts["symnav_skill_reads"] == 1


def test_normalize_trial_copies_captured_workspace_artifacts(tmp_path) -> None:
    trial = tmp_path / "trial"
    captured = trial / "agent" / "workspace" / "app"
    captured.mkdir(parents=True)
    (captured / "status-short.txt").write_text(" M src/a.ts\n", encoding="utf-8")
    (trial / "result.json").write_text(
        json.dumps({"verifier_result": {"rewards": {"f2p": 0.0}}}),
        encoding="utf-8",
    )
    (trial / "agent" / "trajectory.json").write_text('{"steps":[]}', encoding="utf-8")
    identity = CellIdentity(AgentSpec("codex", "m", "e"), "stock", "task", 0)

    normalize_trial(
        trial,
        identity,
        HarnessMeta("image", "pier", "deep", None),
        "completed",
        None,
        tmp_path / "out",
    )

    workspace_artifacts = tmp_path / "out" / identity.dirname() / "raw" / "workspace" / "app"
    assert (workspace_artifacts / "status-short.txt").read_text(encoding="utf-8") == " M src/a.ts\n"


def test_missing_trial_becomes_error(tmp_path) -> None:
    identity = CellIdentity(AgentSpec("codex", "m", "e"), "stock", "task", 0)
    cell = normalize_trial(None, identity, HarnessMeta("image", "pier", "deep", None), "completed", None, tmp_path)
    assert cell.status == "error"
    assert cell.error == "missing or empty trial result"


def test_normalize_attempt_appends_unique_attempts_and_preserves_raw_files(tmp_path) -> None:
    slot = TrialSlot("study", "configuration", "stock", "task", 1, "slot-1")
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "result.json").write_text(
        json.dumps({"verifier_result": {"rewards": {"f2p": 1.0, "p2p": 1.0}}}),
        encoding="utf-8",
    )
    (trial / "trial.log").write_text("first", encoding="utf-8")
    first_identity = AttemptIdentity(slot.slot_id, "attempt-1", "123", 2, "run-stock")

    first = normalize_attempt(trial, slot, first_identity, _harness_identity(), None, tmp_path / "out")
    (trial / "trial.log").write_text("second", encoding="utf-8")
    second_identity = AttemptIdentity(slot.slot_id, "attempt-2", "124", 1, "run-stock")
    second = normalize_attempt(trial, slot, second_identity, _harness_identity(), None, tmp_path / "out")

    first_dir = tmp_path / "out" / slot.slot_id / "attempts" / "attempt-1"
    second_dir = tmp_path / "out" / slot.slot_id / "attempts" / "attempt-2"
    assert AttemptRecord.load(first_dir / "attempt.json") == first
    assert AttemptRecord.load(second_dir / "attempt.json") == second
    assert (first_dir / "raw" / "trial.log").read_text(encoding="utf-8") == "first"
    assert (second_dir / "raw" / "trial.log").read_text(encoding="utf-8") == "second"
    assert first.identity.github_run_id == "123"
    assert first.identity.github_run_attempt == 2
    assert first.identity.github_job == "run-stock"
    assert first.adoption.used_symnav is False
    tool_events = first_dir / "tool-events.jsonl"
    assert tool_events.is_file()
    assert not (first_dir / "commands.jsonl").exists()


def test_normalize_attempt_refuses_to_replace_an_existing_attempt(tmp_path) -> None:
    slot = TrialSlot("study", "configuration", "stock", "task", 1, "slot-1")
    identity = AttemptIdentity(slot.slot_id, "attempt-1", None, None, None)

    normalize_attempt(None, slot, identity, _harness_identity(), RuntimeError("first"), tmp_path)

    try:
        normalize_attempt(None, slot, identity, _harness_identity(), RuntimeError("second"), tmp_path)
    except FileExistsError:
        pass
    else:
        raise AssertionError("duplicate attempt ID replaced immutable attempt")


def test_normalize_attempt_reprocesses_nested_terra_trajectory(tmp_path) -> None:
    slot = TrialSlot("study", "configuration", "symnav", "task", 1, "slot-terra")
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "result.json").write_text(
        json.dumps(
            {
                "agent_result": {"n_agent_steps": 10},
                "verifier_result": {"rewards": {"f2p": 1.0}},
            }
        ),
        encoding="utf-8",
    )
    (trial / "agent" / "trajectory.json").write_text(
        (TRAJECTORY_FIXTURES / "terra_nested_exec.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    identity = AttemptIdentity(slot.slot_id, "attempt-terra", None, None, None)

    attempt = normalize_attempt(trial, slot, identity, _harness_identity(), None, tmp_path / "out")

    assert attempt.adoption.symnav_calls == 1
    assert attempt.adoption.search_calls == 1
    assert attempt.adoption.read_calls == 1
    event_rows = [
        json.loads(line)
        for line in (
            tmp_path / "out" / slot.slot_id / "attempts" / identity.attempt_id / "tool-events.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert event_rows[0]["schema_version"] == 1
    assert event_rows[0]["outer_tool"] == "exec"


def _harness_identity() -> HarnessIdentity:
    return HarnessIdentity(
        image_reference="image",
        image_digest="sha256:image",
        symnav_bench_sha="a" * 40,
        pier_version="0.3.0",
        deep_swe_sha="b" * 40,
        symnav_sha=None,
        agent_name="codex",
        agent_version="0.31.0",
        bundle_id=None,
        bundle_hash=None,
        task_checksum="c" * 64,
        prompt_rule_hash="d" * 64,
        requested_model="model",
        requested_effort="medium",
    )
