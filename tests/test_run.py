from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import yaml
from pathlib import PurePosixPath
from types import SimpleNamespace

from symnav_bench.agent_integrations import AgentIntegrationBundle, IntegrationFile
from symnav_bench.run.auth import validate_auth
from symnav_bench.cli import run_exit_code
from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.attempt import AttemptDisposition
from symnav_bench.run.config import RunConfig
from symnav_bench.run.job_config import HarnessIdentity, build_job_yaml
from symnav_bench.run.limits import next_backoff, parse_limit_reset
from symnav_bench.run.runner import CellRunner, StudyRunContext, build_pier_run_command, find_trial_dir
from symnav_bench.run.symnav_ref import resolve_symnav_ref
from symnav_bench.run_spec import AgentSpec, Condition
from symnav_bench.study import AgentConfiguration
from symnav_bench.suite import TaskManifestEntry


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


def test_job_config_pins_agent_timeout_bundle_and_task_identity(tmp_path) -> None:
    bundle = _integration_bundle(tmp_path)
    configuration = AgentConfiguration(
        id="codex-terra-medium",
        spec=AgentSpec("codex", "gpt-5.6-terra", "medium"),
        agent_version="0.31.0",
    )
    task = TaskManifestEntry("task", "typescript", "f" * 64)

    config = yaml.safe_load(
        build_job_yaml(
            configuration,
            Condition("symnav", "c" * 40),
            task,
            tmp_path,
            bundle,
            9_000,
        )
    )

    assert config["agents"][0]["override_timeout_sec"] == 9_000
    assert config["agents"][0]["kwargs"]["version"] == "0.31.0"
    assert config["agents"][0]["kwargs"]["symnav_sha"] == "c" * 40
    assert config["agents"][0]["kwargs"]["integration_bundle"]["id"] == "full"
    assert config["symnav_bench"] == {
        "agent": "codex",
        "agent_version": "0.31.0",
        "bundle_hash": "bundle-hash",
        "bundle_id": "full",
        "effort": "medium",
        "model": "gpt-5.6-terra",
        "symnav_sha": "c" * 40,
        "task_checksum": "f" * 64,
    }


def test_harness_identity_serializes_every_pinned_runtime_input() -> None:
    identity = HarnessIdentity(
        image_reference="ghcr.io/mohasarc/symnav-bench@sha256:image",
        image_digest="sha256:image",
        symnav_bench_sha="a" * 40,
        pier_version="0.3.0",
        deep_swe_sha="b" * 40,
        symnav_sha="c" * 40,
        agent_name="codex",
        agent_version="0.31.0",
        bundle_id="full",
        bundle_hash="d" * 64,
        task_checksum="e" * 64,
        prompt_rule_hash="f" * 64,
        requested_model="gpt-5.6-terra",
        requested_effort="medium",
    )

    assert identity.to_json() == {
        "image_reference": "ghcr.io/mohasarc/symnav-bench@sha256:image",
        "image_digest": "sha256:image",
        "symnav_bench_sha": "a" * 40,
        "pier_version": "0.3.0",
        "deep_swe_sha": "b" * 40,
        "symnav_sha": "c" * 40,
        "agent_name": "codex",
        "agent_version": "0.31.0",
        "bundle_id": "full",
        "bundle_hash": "d" * 64,
        "task_checksum": "e" * 64,
        "prompt_rule_hash": "f" * 64,
        "requested_model": "gpt-5.6-terra",
        "requested_effort": "medium",
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
    attempts = runner.run_all()
    assert [attempt.disposition.outcome for attempt in attempts] == ["retryable_error", "passed"]


def test_study_runner_pins_bundle_task_and_agent_identity(tmp_path) -> None:
    task = TaskManifestEntry("task", "typescript", "f" * 64)
    configuration = AgentConfiguration("codex-terra-medium", AgentSpec("codex", "terra", "medium"), "0.31.0")
    context = StudyRunContext(configuration, {"task": task}, _integration_bundle(tmp_path), 9000, "a" * 40)
    config = RunConfig(
        specs=[configuration.spec], conditions=[Condition("symnav", "b" * 40)], tasks=["task"],
        reps=1, rep_start=0, parallel=1, timeout_multiplier=None,
        max_limit_wait=timedelta(minutes=1), results_dir=tmp_path / "results", tasks_dir=tmp_path,
    )
    captured = []

    def pier(job_yaml, jobs_dir):
        captured.append(yaml.safe_load(job_yaml.read_text()))
        (jobs_dir / "agent").mkdir()
        (jobs_dir / "agent/trajectory.json").write_text('{"steps":[]}', encoding="utf-8")
        (jobs_dir / "result.json").write_text(
            '{"agent_info":{"version":"0.31.0"},"verifier_result":{"rewards":{"f2p":1.0}}}',
            encoding="utf-8",
        )

    attempt = CellRunner(config, _harness(), pier, study_context=context).run_all()[0]

    assert captured[0]["agents"][0]["kwargs"]["integration_bundle"]["content_hash"] == "bundle-hash"
    assert captured[0]["agents"][0]["kwargs"]["version"] == "0.31.0"
    assert captured[0]["agents"][0]["override_timeout_sec"] == 9000
    assert attempt.harness.task_checksum == "f" * 64
    assert attempt.harness.bundle_hash == "bundle-hash"
    assert attempt.harness.deep_swe_sha == "a" * 40


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
    attempts = runner.run_all()
    assert [attempt.disposition.outcome for attempt in attempts] == ["failed"]
    assert attempts[0].rewards == {"f2p": 0.0}
    assert attempts[0].exception == {
        "exception_type": "RuntimeError",
        "message": "agent failed",
    }


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


def test_run_exit_code_fails_only_for_retryable_attempts() -> None:
    passed = _attempt_with_outcome("passed")
    failed = _attempt_with_outcome("failed")
    retryable = _attempt_with_outcome("retryable_error")

    assert run_exit_code([passed, failed]) == 0
    assert run_exit_code([passed, retryable]) == 1


def _attempt_with_outcome(outcome):
    disposition = AttemptDisposition(
        outcome=outcome,
        scored_failure_reason="verifier" if outcome == "failed" else None,
        retry_reason="quota" if outcome == "retryable_error" else None,
        detail=None,
    )
    return SimpleNamespace(disposition=disposition)


def _harness():
    from symnav_bench.cells.normalize import HarnessMeta

    return HarnessMeta("image", "pier", "deep", None)


def _integration_bundle(tmp_path):
    def integration_file(name, destination, content):
        source = tmp_path / name
        source.write_text(content, encoding="utf-8")
        return IntegrationFile(source, PurePosixPath(destination), name)

    shared = integration_file("shared", "/app/AGENTS.md", "shared")
    skill = integration_file("skill", "/app/.agents/skills/symnav/SKILL.md", "skill")
    rules = integration_file("rules", "/app/AGENTS.md", "rules")
    settings = integration_file("settings", "/app/.claude/settings.json", "{}")
    hook = integration_file("hook", "/tmp/symnav-bench/symnav-nudge.js", "hook")
    return AgentIntegrationBundle(
        id="full",
        shared_rules=shared,
        skill_directory=tmp_path,
        skill_files=(skill,),
        rules=rules,
        allowed_commands=("overview", "resolve", "def", "refs", "context", "graph"),
        claude_settings=settings,
        claude_hook=hook,
        content_hash="bundle-hash",
    )
