from __future__ import annotations

import json
from pathlib import Path

import pytest

from symnav_bench.benchmark_sources.pier_task_writer import (
    MaterializedTaskSpec,
    write_pier_task_dir,
)
from symnav_bench.cli import main
from symnav_bench.deepswe import TASK_SLUGS, ensure_deepswe_tasks
from symnav_bench.tasks import list_tasks


STUDY_FIXTURES = Path(__file__).parent / "fixtures" / "studies"


def test_list_tasks_returns_sorted_subdirectories(tmp_path) -> None:
    write_task(tmp_path / "b", "typescript")
    write_task(tmp_path / "a", "typescript")
    write_task(tmp_path / "python", "python")
    (tmp_path / "file").write_text("", encoding="utf-8")
    assert list_tasks(tmp_path) == ["a", "b"]


def test_list_tasks_missing_dir_is_clear(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="tasks dir does not exist"):
        list_tasks(tmp_path / "missing")


def test_list_tasks_cli_smoke(tmp_path, capsys) -> None:
    write_task(tmp_path / "task", "typescript")
    assert main(["list-tasks", "--tasks-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "task\n"


def test_list_tasks_cli_uses_slug_catalog_without_tasks_dir(capsys, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSWE_TASKS_DIR", raising=False)
    assert main(["list-tasks"]) == 0
    assert capsys.readouterr().out.splitlines() == list(TASK_SLUGS)


def test_slug_catalog_is_typescript_only() -> None:
    assert "abs-module-cache-flags" not in TASK_SLUGS
    assert "kysely-window-grouping-helpers" in TASK_SLUGS


def test_ensure_deepswe_tasks_clones_then_fetches_ref(tmp_path) -> None:
    commands = []

    def runner(command: list[str]) -> None:
        commands.append(command)
        if command[:2] == ["git", "clone"]:
            (tmp_path / "deep-swe" / ".git").mkdir(parents=True)
            (tmp_path / "deep-swe" / "tasks").mkdir()

    tasks_dir = ensure_deepswe_tasks("abc123", root=tmp_path / "deep-swe", runner=runner)
    assert tasks_dir == tmp_path / "deep-swe" / "tasks"
    assert commands[0][:3] == ["git", "clone", "--depth"]
    assert commands[1][-1] == "abc123"


def test_study_metadata_reproduces_v1_workflow_metadata(capsys) -> None:
    exit_code = main(
        [
            "study-metadata",
            "--study", str(STUDY_FIXTURES / "deepswe-v1-manifest.yml"),
            "--suite", str(STUDY_FIXTURES / "deepswe-v1-suite.json"),
            "--configuration", "codex-gpt-5.6-terra-medium",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "agent_spec": "codex:gpt-5.6-terra:medium",
        "agent_version": "0.144.1",
        "benchmark": "deepswe",
        "source_revision": "6db64a40f3318d8659238ff34a8cc4b491c49205",
        "symnav_sha": "80aa4bfa421a7960945005d637ffa5c74665a3ab",
        "protocol_fingerprint": "4695372f68fe8178dec2d1bd09e7864a1bcd251a6036cd6d300f370d115f6419",
        "suite_fingerprint": "2bc576336ca85c7750a00c7d4bc3bb56e7bd372840ce5f699601a9a4b488d1b3",
    }


def test_study_metadata_emits_v2_benchmark_and_source_revision(capsys) -> None:
    exit_code = main(
        [
            "study-metadata",
            "--study", str(STUDY_FIXTURES / "swe-polybench-v2-manifest.yml"),
            "--suite", str(STUDY_FIXTURES / "swe-polybench-v2-suite.json"),
            "--configuration", "codex-gpt-5.6-terra-medium",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "agent_spec": "codex:gpt-5.6-terra:medium",
        "agent_version": "0.144.1",
        "benchmark": "swe-polybench",
        "source_revision": "1234567890abcdef1234567890abcdef12345678",
        "symnav_sha": "b" * 40,
        "protocol_fingerprint": "64cae105cbe79ed19d39ab6a40ea39fa86d4d744c12e8b6aa773e9e043b844de",
        "suite_fingerprint": "2b4e5a711c469875a99cc13d25c65aef02a7f92167d7032cd116e84debcebdb6",
    }


def test_study_metadata_rejects_unknown_configuration(capsys) -> None:
    exit_code = main(
        [
            "study-metadata",
            "--study", str(STUDY_FIXTURES / "deepswe-v1-manifest.yml"),
            "--suite", str(STUDY_FIXTURES / "deepswe-v1-suite.json"),
            "--configuration", "missing-configuration",
        ]
    )

    assert exit_code == 1
    assert "missing-configuration" in capsys.readouterr().err


def test_list_tasks_prints_materialized_instance_ids(tmp_path, capsys) -> None:
    materialize_polybench_fixture_tasks(tmp_path)

    assert main(["list-tasks", "--tasks-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "coder__code-server-321",
        "microsoft__vscode-12345",
    ]


def test_plan_study_counts_slots_for_v2_study(tmp_path, capsys) -> None:
    materialize_polybench_fixture_tasks(tmp_path)

    exit_code = main(
        [
            "plan-study",
            "--study", str(STUDY_FIXTURES / "swe-polybench-v2-manifest.yml"),
            "--tasks-dir", str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "swe-polybench-ts-codex-terra-medium-smoke: 2 tasks, 1 configurations, 4 slots\n"
    )


def materialize_polybench_fixture_tasks(tasks_dir: Path) -> None:
    for slug in ("microsoft__vscode-12345", "coder__code-server-321"):
        spec = MaterializedTaskSpec(
            benchmark="swe-polybench",
            slug=slug,
            instruction="fix the reported issue",
            docker_image="ghcr.io/example/eval@sha256:" + "0" * 64,
            workdir="/testbed",
            base_commit="9" * 40,
            test_patch="diff --git a/a b/a\n",
            f2p=("suite > case",),
            p2p=(),
            test_command="yarn test",
            log_parser="mocha",
            grade_script="print('grade')\n",
        )
        write_pier_task_dir(spec, tasks_dir / slug)


def write_task(path, language: str) -> None:
    path.mkdir()
    (path / "task.toml").write_text(
        f'[metadata]\nlanguage = "{language}"\n',
        encoding="utf-8",
    )
