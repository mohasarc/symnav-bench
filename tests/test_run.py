from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from symnav_bench.run.auth import validate_auth
from symnav_bench.run.config import RunConfig
from symnav_bench.run.job_config import build_job_yaml
from symnav_bench.run.limits import next_backoff, parse_limit_reset
from symnav_bench.run.runner import CellRunner
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
    yaml = build_job_yaml(AgentSpec("codex", "m", "e"), Condition("symnav", "c" * 40), "task", tmp_path)
    assert "SymnavCodex" in yaml
    assert "symnav_sha" in yaml


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


def _harness():
    from symnav_bench.cells.normalize import HarnessMeta

    return HarnessMeta("image", "pier", "deep", None)
