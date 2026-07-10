from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import yaml

from symnav_bench.run.auth import validate_auth
from symnav_bench.cli import run_exit_code
from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.cell import Cell
from symnav_bench.run.config import RunConfig
from symnav_bench.run.job_config import build_job_yaml
from symnav_bench.run.limits import next_backoff, parse_limit_reset
from symnav_bench.run.runner import CellRunner, build_pier_run_command, find_trial_dir
from symnav_bench.run.symnav_ref import resolve_symnav_ref
from symnav_bench.run_spec import AgentSpec, Condition


def test_matrix_expansion(tmp_path) -> None:
    config = RunConfig(
        specs=[AgentSpec("codex", "m1", "e"), AgentSpec("claude", "m2", "e")],
        conditions=[Condition("stock"), Condition("symnav", "a" * 40)],
        tasks=["t1", "t2"],
        reps=2,
        rep_start=0,
        parallel=1,
        timeout_multiplier=None,
        max_limit_wait=timedelta(minutes=1),
        results_dir=tmp_path,
        tasks_dir=tmp_path,
    )
    assert len(config.cells()) == 16


def test_auth_validation() -> None:
    with pytest.raises(RuntimeError, match="CODEX_AUTH_JSON_B64"):
        validate_auth([AgentSpec("codex", "m", "e")], {})
    validate_auth([AgentSpec("claude", "m", "e")], {"ANTHROPIC_API_KEY": "x"})


def test_ref_resolution() -> None:
    assert resolve_symnav_ref("a" * 40) == "a" * 40
    assert resolve_symnav_ref("main", lambda ref: "b" * 40 + "\trefs/heads/main") == "b" * 40


def test_limit_backoff_and_reset() -> None:
    now = datetime(2026, 1, 1, 15, 0, tzinfo=UTC)
    assert parse_limit_reset("try again at 3:45 PM UTC", now) == datetime(2026, 1, 1, 15, 45, tzinfo=UTC)
    assert next_backoff([]) == timedelta(minutes=5)
    assert next_backoff([timedelta(minutes=5), timedelta(minutes=10), timedelta(minutes=20)]) == timedelta(minutes=20)


def test_job_config_names_agent_arm(tmp_path) -> None:
    config = yaml.safe_load(
        build_job_yaml(
            AgentSpec("codex", "m", "e"),
            Condition("symnav", "c" * 40),
            "task",
            tmp_path,
        )
    )
    assert config["agents"] == [
        {
            "env": {"CODEX_FORCE_AUTH_JSON": "true"},
            "import_path": "symnav_bench.agents.codex:SymnavCodex",
            "kwargs": {"reasoning_effort": "e", "symnav_sha": "c" * 40},
            "model_name": "m",
        }
    ]
    assert config["tasks"] == [{"path": str(tmp_path / "task")}]


def test_job_config_threads_symnav_skill_variant(tmp_path) -> None:
    config = yaml.safe_load(
        build_job_yaml(
            AgentSpec("codex", "m", "e"),
            Condition("symnav", "c" * 40, "overview"),
            "task",
            tmp_path,
        )
    )
    assert config["agents"][0]["kwargs"] == {
        "reasoning_effort": "e",
        "symnav_sha": "c" * 40,
        "symnav_skill_variant": "overview",
    }


def test_runner_continues_after_error(tmp_path) -> None:
    config = RunConfig(
        specs=[AgentSpec("codex", "m", "e")],
        conditions=[Condition("stock")],
        tasks=["t1", "t2"],
        reps=1,
        rep_start=0,
        parallel=1,
        timeout_multiplier=None,
        max_limit_wait=timedelta(minutes=1),
        results_dir=tmp_path / "results",
        tasks_dir=tmp_path,
    )
    calls = []

    def pier(job_yaml, jobs_dir):
        calls.append(job_yaml)
        if len(calls) == 1:
            raise RuntimeError("boom")
        (jobs_dir / "result.json").write_text('{"verifier_result":{"rewards":{"f2p":1.0}}}', encoding="utf-8")
        (jobs_dir / "agent").mkdir()
        (jobs_dir / "agent" / "trajectory.json").write_text('{"steps":[]}', encoding="utf-8")

    runner = CellRunner(config, harness=_harness(), pier=pier, sleeper=lambda seconds: None)
    cells = runner.run_all()
    assert [cell.status for cell in cells] == ["error", "completed"]


def test_runner_normalizes_pier_trial_result_after_agent_failure(tmp_path) -> None:
    config = RunConfig(
        specs=[AgentSpec("codex", "m", "e")],
        conditions=[Condition("stock")],
        tasks=["t1"],
        reps=1,
        rep_start=0,
        parallel=1,
        timeout_multiplier=None,
        max_limit_wait=timedelta(minutes=1),
        results_dir=tmp_path / "results",
        tasks_dir=tmp_path,
    )

    def pier(job_yaml, jobs_dir):
        trial_dir = jobs_dir / "job" / "trial"
        trial_dir.mkdir(parents=True)
        (trial_dir / "agent").mkdir()
        (trial_dir / "verifier").mkdir()
        (trial_dir / "result.json").write_text(
            '{"verifier_result":{"rewards":{"f2p":0.0}}}',
            encoding="utf-8",
        )
        raise RuntimeError("agent failed")

    runner = CellRunner(
        config,
        harness=_harness(),
        pier=pier,
        sleeper=lambda seconds: None,
    )
    cells = runner.run_all()
    assert [cell.status for cell in cells] == ["completed"]
    assert cells[0].rewards == {"f2p": 0.0}


def test_pier_run_command_uses_current_cli_output_flag(tmp_path) -> None:
    command = build_pier_run_command(tmp_path / "job.yaml", tmp_path / "jobs")
    assert command == [
        "pier",
        "run",
        "--config",
        str(tmp_path / "job.yaml"),
        "--jobs-dir",
        str(tmp_path / "jobs"),
        "--yes",
    ]


def test_find_trial_dir_ignores_job_result(tmp_path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "result.json").write_text("{}", encoding="utf-8")
    trial_dir = job_dir / "trial"
    (trial_dir / "agent").mkdir(parents=True)
    (trial_dir / "result.json").write_text("{}", encoding="utf-8")
    assert find_trial_dir(tmp_path) == trial_dir


def test_run_exit_code_fails_when_a_cell_errors() -> None:
    assert run_exit_code([_cell("completed")]) == 0
    assert run_exit_code([_cell("completed"), _cell("error")]) == 1


def _cell(status):
    return Cell(
        identity=CellIdentity(AgentSpec("codex", "m", "e"), "stock", "task", 0),
        status=status,
        error=None,
        solved=False,
        rewards={},
        usage={},
        timing={},
        agent_version=None,
        harness={},
        command_counts={},
    )


def _harness():
    from symnav_bench.cells.normalize import HarnessMeta

    return HarnessMeta("image", "pier", "deep", None)
