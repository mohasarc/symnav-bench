from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import yaml
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import symnav_bench.cli as cli
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
from symnav_bench.study import AgentConfiguration, BenchmarkSelection
from symnav_bench.suite import SuiteManifest, TaskManifestEntry


STUDY_FIXTURES = Path(__file__).parent / "fixtures" / "studies"
POLYBENCH_REVISION = "1234567890abcdef1234567890abcdef12345678"


def test_cli_has_package_version_fallback() -> None:
    assert cli.__version__ == "0.1.0"


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


def test_harness_identity_serializes_benchmark_provenance_for_non_deepswe() -> None:
    identity = HarnessIdentity(
        image_reference="image",
        image_digest="sha256:image",
        symnav_bench_sha="a" * 40,
        pier_version="0.3.0",
        deep_swe_sha=POLYBENCH_REVISION,
        symnav_sha=None,
        agent_name="codex",
        agent_version="0.31.0",
        bundle_id=None,
        bundle_hash=None,
        task_checksum="e" * 64,
        prompt_rule_hash="f" * 64,
        requested_model="gpt-5.6-terra",
        requested_effort="medium",
        benchmark="swe-polybench",
        benchmark_source_revision=POLYBENCH_REVISION,
        task_fit_tier="high",
    )

    serialized = identity.to_json()

    assert serialized["benchmark"] == "swe-polybench"
    assert serialized["benchmark_source_revision"] == POLYBENCH_REVISION
    assert serialized["task_fit_tier"] == "high"
    assert serialized["deep_swe_sha"] == POLYBENCH_REVISION


def test_harness_identity_keeps_null_tier_for_multi_swe_bench() -> None:
    identity = HarnessIdentity(
        image_reference="image",
        image_digest="sha256:image",
        symnav_bench_sha="a" * 40,
        pier_version="0.3.0",
        deep_swe_sha="3" * 40,
        symnav_sha=None,
        agent_name="codex",
        agent_version="0.31.0",
        bundle_id=None,
        bundle_hash=None,
        task_checksum="e" * 64,
        prompt_rule_hash="f" * 64,
        requested_model="gpt-5.6-terra",
        requested_effort="medium",
        benchmark="multi-swe-bench",
        benchmark_source_revision="3" * 40,
    )

    serialized = identity.to_json()

    assert serialized["benchmark"] == "multi-swe-bench"
    assert "task_fit_tier" in serialized
    assert serialized["task_fit_tier"] is None


def test_study_runner_records_benchmark_provenance_in_attempt(tmp_path) -> None:
    task = TaskManifestEntry("microsoft__vscode-12345", "typescript", "f" * 64, tier="high")
    suite = SuiteManifest("swe-polybench", POLYBENCH_REVISION, (task,), "e" * 64)
    selection = BenchmarkSelection("swe-polybench", POLYBENCH_REVISION, ("high",))
    configuration = AgentConfiguration(
        "codex-terra-medium", AgentSpec("codex", "terra", "medium"), "0.31.0"
    )
    context = StudyRunContext(
        configuration, suite, _integration_bundle(tmp_path), 9000, selection
    )
    config = RunConfig(
        specs=[configuration.spec], conditions=[Condition("stock")],
        tasks=["microsoft__vscode-12345"], reps=1, rep_start=0, parallel=1,
        timeout_multiplier=None, max_limit_wait=timedelta(minutes=1),
        results_dir=tmp_path / "results", tasks_dir=tmp_path,
    )

    def materializer(benchmark, declared_suite, slugs, target):
        materialized = tmp_path / "materialized"
        materialized.mkdir(exist_ok=True)
        return materialized

    def pier(job_yaml, jobs_dir):
        (jobs_dir / "agent").mkdir()
        (jobs_dir / "agent/trajectory.json").write_text('{"steps":[]}', encoding="utf-8")
        (jobs_dir / "result.json").write_text(
            '{"verifier_result":{"rewards":{"f2p":1.0}}}', encoding="utf-8"
        )

    runner = CellRunner(
        config, _harness(), pier, study_context=context, materializer=materializer
    )
    attempt = runner.run_all()[0]

    assert attempt.harness.benchmark == "swe-polybench"
    assert attempt.harness.benchmark_source_revision == POLYBENCH_REVISION
    assert attempt.harness.task_fit_tier == "high"
    written = json.loads(
        next((tmp_path / "results").glob("*/attempts/*/attempt.json")).read_text(
            encoding="utf-8"
        )
    )
    assert written["harness"]["benchmark"] == "swe-polybench"
    assert written["harness"]["benchmark_source_revision"] == POLYBENCH_REVISION
    assert written["harness"]["task_fit_tier"] == "high"
    assert written["harness"]["deep_swe_sha"] == POLYBENCH_REVISION


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
    suite = SuiteManifest("deepswe", "a" * 40, (task,), "e" * 64)
    configuration = AgentConfiguration("codex-terra-medium", AgentSpec("codex", "terra", "medium"), "0.31.0")
    context = StudyRunContext(
        configuration,
        suite,
        _integration_bundle(tmp_path),
        9000,
        BenchmarkSelection("deepswe", "a" * 40, None),
    )
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


def test_study_run_context_from_environment_exposes_v2_benchmark_selection(
    tmp_path, monkeypatch
) -> None:
    checkout = _write_symnav_checkout(tmp_path)
    monkeypatch.setenv(
        "SYMNAV_BENCH_STUDY_MANIFEST", str(STUDY_FIXTURES / "swe-polybench-v2-manifest.yml")
    )
    monkeypatch.setenv(
        "SYMNAV_BENCH_SUITE_MANIFEST", str(STUDY_FIXTURES / "swe-polybench-v2-suite.json")
    )
    monkeypatch.setenv("SYMNAV_BENCH_SYMNAV_CHECKOUT", str(checkout))
    monkeypatch.setenv("SYMNAV_BENCH_CONFIGURATION_ID", "codex-gpt-5.6-terra-medium")

    context = StudyRunContext.from_environment()

    assert context is not None
    assert context.benchmark == BenchmarkSelection(
        name="swe-polybench",
        source_revision=POLYBENCH_REVISION,
        tiers=("high", "mid"),
    )
    assert context.suite.benchmark == "swe-polybench"
    assert context.tasks["microsoft__vscode-12345"].tier == "high"
    assert context.configuration.id == "codex-gpt-5.6-terra-medium"
    assert context.wall_clock_seconds == 9000


def test_study_runner_materializes_non_deepswe_tasks_before_pier(tmp_path) -> None:
    task = TaskManifestEntry("microsoft__vscode-12345", "typescript", "f" * 64, tier="high")
    suite = SuiteManifest("swe-polybench", POLYBENCH_REVISION, (task,), "e" * 64)
    selection = BenchmarkSelection("swe-polybench", POLYBENCH_REVISION, ("high",))
    configuration = AgentConfiguration(
        "codex-terra-medium", AgentSpec("codex", "terra", "medium"), "0.31.0"
    )
    context = StudyRunContext(
        configuration, suite, _integration_bundle(tmp_path), 9000, selection
    )
    workdir = tmp_path / "tasks-workdir"
    workdir.mkdir()
    materialized_dir = tmp_path / "materialized"
    materializer_calls = []

    def materializer(benchmark, declared_suite, slugs, target):
        materializer_calls.append((benchmark, declared_suite, tuple(slugs), target))
        materialized_dir.mkdir(exist_ok=True)
        return materialized_dir

    config = RunConfig(
        specs=[configuration.spec], conditions=[Condition("stock")],
        tasks=["microsoft__vscode-12345"], reps=1, rep_start=0, parallel=1,
        timeout_multiplier=None, max_limit_wait=timedelta(minutes=1),
        results_dir=tmp_path / "results", tasks_dir=workdir,
    )
    captured = []

    def pier(job_yaml, jobs_dir):
        captured.append(yaml.safe_load(job_yaml.read_text()))
        (jobs_dir / "agent").mkdir()
        (jobs_dir / "agent/trajectory.json").write_text('{"steps":[]}', encoding="utf-8")
        (jobs_dir / "result.json").write_text(
            '{"verifier_result":{"rewards":{"f2p":1.0}}}', encoding="utf-8"
        )

    runner = CellRunner(
        config, _harness(), pier, study_context=context, materializer=materializer
    )
    attempt = runner.run_all()[0]

    assert materializer_calls == [
        (selection, suite, ("microsoft__vscode-12345",), workdir)
    ]
    assert captured[0]["tasks"] == [
        {"path": str(materialized_dir / "microsoft__vscode-12345")}
    ]
    assert attempt.harness.deep_swe_sha == POLYBENCH_REVISION


def test_run_cli_rejects_adhoc_non_deepswe_suite(tmp_path, monkeypatch, capsys) -> None:
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "benchmark": "multi-swe-bench",
                "source_revision": "3" * 40,
                "fingerprint": "4" * 64,
                "tasks": [
                    {
                        "slug": "mui__material-ui-1",
                        "language": "typescript",
                        "checksum": "5" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("SYMNAV_BENCH_STUDY_MANIFEST", raising=False)
    monkeypatch.delenv("SYMNAV_BENCH_SYMNAV_CHECKOUT", raising=False)
    monkeypatch.delenv("SYMNAV_BENCH_CONFIGURATION_ID", raising=False)
    monkeypatch.setenv("SYMNAV_BENCH_SUITE_MANIFEST", str(suite_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    exit_code = cli.main(
        [
            "run",
            "--agent", "claude:m:e",
            "--tasks", "mui__material-ui-1",
            "--results-dir", str(tmp_path / "results"),
            "--symnav-ref", "a" * 40,
        ]
    )

    assert exit_code == 1
    error = capsys.readouterr().err
    assert "declared study" in error
    assert "multi-swe-bench" in error


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
    assert [attempt.disposition.outcome for attempt in attempts] == ["retryable_error"]
    assert attempts[0].disposition.retry_reason == "runner"
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


def _write_symnav_checkout(root):
    checkout = root / "symnav"
    catalog = {
        "schemaVersion": 1,
        "sharedRulesFile": ".agents/integrations/symnav/shared-rules.md",
        "bundles": [
            {
                "id": "full",
                "skillDirectory": ".agents/skills/symnav",
                "rulesFile": ".agents/integrations/symnav/full/rules.md",
                "allowedCommands": ["overview", "resolve", "def", "refs", "context", "graph"],
                "claudeSettingsFile": ".agents/integrations/symnav/full/claude-settings.json",
                "claudeHookFile": ".agents/integrations/symnav/full/symnav-nudge.js",
            },
        ],
    }
    files = {
        ".agents/integrations/symnav/catalog.json": json.dumps(catalog, sort_keys=True),
        ".agents/integrations/symnav/shared-rules.md": "shared\n",
        ".agents/skills/symnav/SKILL.md": "skill\n",
        ".agents/integrations/symnav/full/rules.md": "rules\n",
        ".agents/integrations/symnav/full/claude-settings.json": "{}\n",
        ".agents/integrations/symnav/full/symnav-nudge.js": "hook\n",
    }
    for relative_path, content in files.items():
        path = checkout / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return checkout


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


def test_job_config_threads_task_workdir_to_agent(tmp_path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text(
        '[environment]\nworkdir = "/testbed"\n', encoding="utf-8"
    )

    config = yaml.safe_load(
        build_job_yaml(
            AgentSpec("codex", "m", "e"),
            Condition("symnav", "c" * 40),
            "task",
            tmp_path,
        )
    )

    assert config["agents"][0]["kwargs"]["workdir"] == "/testbed"


def test_job_config_omits_workdir_for_deepswe_layout(tmp_path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text(
        '[environment]\nworkdir = "/app"\n', encoding="utf-8"
    )

    config = yaml.safe_load(
        build_job_yaml(
            AgentSpec("codex", "m", "e"),
            Condition("symnav", "c" * 40),
            "task",
            tmp_path,
        )
    )

    assert "workdir" not in config["agents"][0]["kwargs"]
