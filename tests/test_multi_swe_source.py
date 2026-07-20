from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from symnav_bench.benchmark_sources import benchmark_task_source, multi_swe_bench_source
from symnav_bench.benchmark_sources.multi_swe_bench_source import (
    REPO_PROFILES,
    MultiSweBenchTaskSource,
    MultiSweInstance,
    eval_image_repository,
    eval_image_tag,
    execution_profile_for,
    parse_multi_swe_rows,
)
from symnav_bench.cli import main
from symnav_bench.study import BenchmarkSelection
from symnav_bench.suite import directory_checksum, suite_fingerprint

MULTI_SWE_REVISION = "d" * 40


def test_statuses(names: tuple[str, ...]) -> dict[str, dict[str, str]]:
    return {name: {"run": "NONE", "test": "FAIL", "fix": "PASS"} for name in names}


def dataset_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "org": "darkreader",
        "repo": "darkreader",
        "number": 7241,
        "state": "closed",
        "title": "Fix: parser should ignore Base64 padding within CSS",
        "body": "Fixes #7238.",
        "base": {"label": "darkreader:master", "ref": "master", "sha": "c" * 40},
        "fix_patch": "diff --git a/src/parse.ts b/src/parse.ts",
        "test_patch": "diff --git a/tests/parse.tests.ts b/tests/parse.tests.ts",
        "f2p_tests": test_statuses(
            (
                "tests/generators/utils/parse.tests.ts:Base64 in CSS",
                "tests/generators/utils/parse.tests.ts",
            )
        ),
        "p2p_tests": test_statuses(
            (
                "tests/utils/time.tests.ts:Time parse",
                "tests/utils/time.tests.ts",
            )
        ),
        "instance_id": "darkreader__darkreader-7241",
    }
    row.update(overrides)
    return row


def three_repo_rows() -> list[dict[str, Any]]:
    return [
        dataset_row(),
        dataset_row(
            instance_id="darkreader__darkreader-6747",
            number=6747,
            title="Fix: ensure that first fix is generic fix",
        ),
        dataset_row(
            org="vuejs",
            repo="core",
            number=11899,
            instance_id="vuejs__core-11899",
            title="fix(suspense): nested suspense",
        ),
        dataset_row(
            org="mui",
            repo="material-ui",
            number=39962,
            instance_id="mui__material-ui-39962",
            title="[system] Fix sx style function",
        ),
    ]


def test_parse_rows_reads_instance_fields() -> None:
    instance = parse_multi_swe_rows([dataset_row()])[0]

    assert instance.instance_id == "darkreader__darkreader-7241"
    assert instance.org == "darkreader"
    assert instance.repo == "darkreader"
    assert instance.number == 7241
    assert instance.base_commit == "c" * 40
    assert instance.test_patch == (
        "diff --git a/tests/parse.tests.ts b/tests/parse.tests.ts"
    )
    assert instance.f2p == (
        "tests/generators/utils/parse.tests.ts:Base64 in CSS",
        "tests/generators/utils/parse.tests.ts",
    )
    assert instance.p2p == (
        "tests/utils/time.tests.ts:Time parse",
        "tests/utils/time.tests.ts",
    )


def test_problem_statement_joins_title_and_body() -> None:
    instance = parse_multi_swe_rows([dataset_row()])[0]

    assert instance.problem_statement == (
        "Fix: parser should ignore Base64 padding within CSS\n\nFixes #7238."
    )


def test_problem_statement_is_title_when_body_is_blank() -> None:
    instance = parse_multi_swe_rows([dataset_row(body="  \n")])[0]

    assert instance.problem_statement == (
        "Fix: parser should ignore Base64 padding within CSS"
    )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("org", ""),
        ("repo", None),
        ("number", "7241"),
        ("number", True),
        ("title", ""),
        ("body", None),
        ("base", {"label": "x", "ref": "master"}),
        ("base", "not a mapping"),
        ("test_patch", ""),
        ("f2p_tests", {}),
        ("f2p_tests", ["not", "a", "mapping"]),
        ("p2p_tests", ["not", "a", "mapping"]),
    ],
)
def test_malformed_row_value_errors_naming_the_instance(
    column: str, value: Any
) -> None:
    row = dataset_row(**{column: value})

    with pytest.raises(ValueError, match="darkreader__darkreader-7241"):
        parse_multi_swe_rows([row])


def test_row_without_instance_id_is_rejected() -> None:
    row = dataset_row()
    del row["instance_id"]

    with pytest.raises(ValueError, match="instance_id"):
        parse_multi_swe_rows([row])


@pytest.mark.parametrize(
    ("org", "repo", "number", "workdir", "log_parser"),
    [
        ("darkreader", "darkreader", 7241, "/home/darkreader", "jest-darkreader"),
        ("mui", "material-ui", 39962, "/home/material-ui", "mocha-mui"),
        ("vuejs", "core", 11899, "/home/core", "vitest-vuejs"),
    ],
)
def test_repo_profiles_cover_the_three_typescript_repos(
    org: str, repo: str, number: int, workdir: str, log_parser: str
) -> None:
    instance = parse_multi_swe_rows(
        [
            dataset_row(
                org=org, repo=repo, number=number, instance_id=f"{org}__{repo}-{number}"
            )
        ]
    )[0]

    profile = execution_profile_for(instance)

    assert profile.org == org
    assert profile.repo == repo
    assert profile.workdir == workdir
    assert profile.test_command == "bash /home/run.sh"
    assert profile.log_parser == log_parser
    assert eval_image_repository(instance) == f"mswebench/{org}_m_{repo}"
    assert eval_image_tag(instance) == f"pr-{number}"


def test_exactly_three_repo_profiles_are_registered() -> None:
    assert len(REPO_PROFILES) == 3
    assert {(profile.org, profile.repo) for profile in REPO_PROFILES} == {
        ("darkreader", "darkreader"),
        ("mui", "material-ui"),
        ("vuejs", "core"),
    }


def test_unknown_repo_is_a_hard_error() -> None:
    instance = parse_multi_swe_rows(
        [dataset_row(org="sveltejs", repo="svelte", instance_id="sveltejs__svelte-1")]
    )[0]

    with pytest.raises(ValueError, match="sveltejs/svelte"):
        execution_profile_for(instance)


def pinned_image(instance: MultiSweInstance, digest: str = "0" * 64) -> str:
    return (
        f"docker.io/mswebench/{instance.org}_m_{instance.repo}@sha256:{digest}"
    )


def multi_swe_source(
    rows: list[dict[str, Any]],
    resolve_image=pinned_image,
    suite=None,
) -> MultiSweBenchTaskSource:
    selection = BenchmarkSelection(
        name="multi-swe-bench", source_revision=MULTI_SWE_REVISION, tiers=None
    )
    return MultiSweBenchTaskSource(
        selection,
        load_rows=lambda revision: rows,
        resolve_image=resolve_image,
        suite=suite,
    )


def test_factory_returns_multi_swe_source_for_multi_swe_selection() -> None:
    selection = BenchmarkSelection(
        name="multi-swe-bench", source_revision=MULTI_SWE_REVISION, tiers=None
    )

    source = benchmark_task_source(selection)

    assert isinstance(source, MultiSweBenchTaskSource)
    assert source.selection == selection


def test_resolve_builds_sorted_v2_suite_without_tiers() -> None:
    suite = multi_swe_source(three_repo_rows()).resolve()

    assert suite.benchmark == "multi-swe-bench"
    assert suite.source_revision == MULTI_SWE_REVISION
    assert [task.slug for task in suite.tasks] == [
        "darkreader__darkreader-6747",
        "darkreader__darkreader-7241",
        "mui__material-ui-39962",
        "vuejs__core-11899",
    ]
    assert all(task.tier is None for task in suite.tasks)
    assert all(task.language == "typescript" for task in suite.tasks)
    assert suite.fingerprint == suite_fingerprint(
        "multi-swe-bench", MULTI_SWE_REVISION, suite.tasks
    )


def test_resolve_is_deterministic_and_checksum_is_content_sensitive() -> None:
    assert multi_swe_source(three_repo_rows()).resolve() == multi_swe_source(
        three_repo_rows()
    ).resolve()

    edited_rows = three_repo_rows()
    edited_rows[1]["test_patch"] = "diff --git a/other.ts b/other.ts"
    original = multi_swe_source(three_repo_rows()).resolve()
    edited = multi_swe_source(edited_rows).resolve()

    assert original.tasks[0].checksum != edited.tasks[0].checksum
    assert original.fingerprint != edited.fingerprint


def test_resolve_passes_pinned_revision_to_loader() -> None:
    revisions: list[str] = []

    def load_rows(revision: str) -> list[dict[str, Any]]:
        revisions.append(revision)
        return three_repo_rows()

    selection = BenchmarkSelection(
        name="multi-swe-bench", source_revision=MULTI_SWE_REVISION, tiers=None
    )
    MultiSweBenchTaskSource(
        selection, load_rows=load_rows, resolve_image=pinned_image
    ).resolve()

    assert revisions == [MULTI_SWE_REVISION]


def test_resolve_rejects_instance_from_unknown_repo() -> None:
    rows = [dataset_row(org="sveltejs", repo="svelte", instance_id="sveltejs__svelte-1")]

    with pytest.raises(ValueError, match="sveltejs/svelte"):
        multi_swe_source(rows).resolve()


def test_resolve_excludes_instances_without_eval_images(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def only_darkreader_published(instance: MultiSweInstance) -> str | None:
        return pinned_image(instance) if instance.org == "darkreader" else None

    suite = multi_swe_source(
        three_repo_rows(), resolve_image=only_darkreader_published
    ).resolve()

    assert [task.slug for task in suite.tasks] == [
        "darkreader__darkreader-6747",
        "darkreader__darkreader-7241",
    ]
    stderr = capsys.readouterr().err
    assert "excluded 2 of 4" in stderr
    assert "mui__material-ui-39962" in stderr
    assert "vuejs__core-11899" in stderr


def test_resolve_errors_when_no_instance_has_an_image() -> None:
    with pytest.raises(ValueError, match="no tasks"):
        multi_swe_source(three_repo_rows(), resolve_image=lambda _: None).resolve()


def multi_swe_manifest_data() -> dict[str, Any]:
    protocol = {
        "benchmark": {
            "name": "multi-swe-bench",
            "source": {"revision": MULTI_SWE_REVISION},
        },
        "symnav": {
            "sha": "b" * 40,
            "kind": "main",
            "evaluation_sequence": 1,
            "base_ref": "main",
            "base_sha": "b" * 40,
            "pull_request": None,
        },
        "repetitions": 2,
        "wall_clock_seconds": 9_000,
        "randomization_seed": 7,
        "conditions": ["stock", "symnav"],
        "scoring_policy": "deepswe-pass-fraction-v1",
        "practical_uplift_points": 5.0,
    }
    return {
        "schema_version": 2,
        "id": "multi-swe-ts-test",
        "protocol_fingerprint": fingerprint(protocol),
        "protocol": protocol,
        "configurations": [
            {
                "id": "codex-terra-medium",
                "agent": "codex",
                "model": "gpt-5.6-terra",
                "effort": "medium",
                "agent_version": "0.31.0",
            }
        ],
    }


def fingerprint(protocol: dict[str, Any]) -> str:
    canonical = json.dumps(protocol, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def test_resolve_suite_cli_writes_identical_multi_swe_suites_across_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        multi_swe_bench_source, "load_dataset_rows", lambda revision: three_repo_rows()
    )
    monkeypatch.setattr(multi_swe_bench_source, "resolve_eval_image", pinned_image)
    manifest = tmp_path / "manifest.yml"
    manifest.write_text(
        yaml.safe_dump(copy.deepcopy(multi_swe_manifest_data()), sort_keys=False),
        encoding="utf-8",
    )
    first_out = tmp_path / "first-suite.json"
    second_out = tmp_path / "second-suite.json"

    assert main(["resolve-suite", "--study", str(manifest), "--out", str(first_out)]) == 0
    assert main(["resolve-suite", "--study", str(manifest), "--out", str(second_out)]) == 0

    assert first_out.read_bytes() == second_out.read_bytes()
    payload = json.loads(first_out.read_text(encoding="utf-8"))
    assert payload["benchmark"] == "multi-swe-bench"
    assert payload["source_revision"] == MULTI_SWE_REVISION
    assert all("tier" not in task for task in payload["tasks"])
    assert "multi-swe-ts-test: 4 tasks, 16 slots" in capsys.readouterr().out


def test_resolve_checksums_match_runtime_materialization(tmp_path: Path) -> None:
    from pier.models.task.paths import TaskPaths

    suite = multi_swe_source(three_repo_rows()).resolve()
    source = multi_swe_source(three_repo_rows(), suite=suite)

    tasks_dir = source.ensure_tasks_dir(["vuejs__core-11899"], tmp_path)

    task_dir = tasks_dir / "vuejs__core-11899"
    assert TaskPaths(task_dir).is_valid()
    declared = {task.slug: task.checksum for task in suite.tasks}
    assert directory_checksum(task_dir) == declared["vuejs__core-11899"]


def test_ensure_tasks_dir_materializes_only_requested_slugs(tmp_path: Path) -> None:
    suite = multi_swe_source(three_repo_rows()).resolve()
    source = multi_swe_source(three_repo_rows(), suite=suite)

    source.ensure_tasks_dir(["darkreader__darkreader-7241"], tmp_path)

    assert (tmp_path / "darkreader__darkreader-7241").is_dir()
    assert not (tmp_path / "vuejs__core-11899").exists()


def test_materialized_task_carries_instance_and_profile_content(tmp_path: Path) -> None:
    from symnav_bench.benchmark_sources.grading import grade_script_source

    suite = multi_swe_source(three_repo_rows()).resolve()
    source = multi_swe_source(three_repo_rows(), suite=suite)

    task_dir = source.ensure_tasks_dir(["mui__material-ui-39962"], tmp_path) / (
        "mui__material-ui-39962"
    )

    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    assert instruction.startswith("[system] Fix sx style function")
    config = json.loads((task_dir / "tests" / "config.json").read_text(encoding="utf-8"))
    assert config["benchmark"] == "multi-swe-bench"
    assert config["log_parser"] == "mocha-mui"
    assert config["workdir"] == "/home/material-ui"
    assert config["test_command"] == "bash /home/run.sh"
    assert config["base_commit"] == "c" * 40
    assert config["f2p"] == [
        "tests/generators/utils/parse.tests.ts:Base64 in CSS",
        "tests/generators/utils/parse.tests.ts",
    ]
    assert config["p2p"] == [
        "tests/utils/time.tests.ts:Time parse",
        "tests/utils/time.tests.ts",
    ]
    grade = (task_dir / "tests" / "grade.py").read_text(encoding="utf-8")
    assert grade == grade_script_source()


def test_ensure_tasks_dir_requires_declared_suite(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="suite"):
        multi_swe_source(three_repo_rows()).ensure_tasks_dir(
            ["darkreader__darkreader-7241"], tmp_path
        )


def test_ensure_tasks_dir_rejects_slug_missing_from_suite(tmp_path: Path) -> None:
    suite = multi_swe_source(three_repo_rows()).resolve()
    source = multi_swe_source(three_repo_rows(), suite=suite)

    with pytest.raises(ValueError, match="unknown-slug"):
        source.ensure_tasks_dir(["unknown-slug"], tmp_path)


def test_ensure_tasks_dir_rejects_slug_missing_from_dataset(tmp_path: Path) -> None:
    suite = multi_swe_source(three_repo_rows()).resolve()
    shrunken = [
        row
        for row in three_repo_rows()
        if row["instance_id"] != "darkreader__darkreader-7241"
    ]
    source = multi_swe_source(shrunken, suite=suite)

    with pytest.raises(ValueError, match="darkreader__darkreader-7241"):
        source.ensure_tasks_dir(["darkreader__darkreader-7241"], tmp_path)


def test_ensure_tasks_dir_rejects_vanished_eval_image(tmp_path: Path) -> None:
    suite = multi_swe_source(three_repo_rows()).resolve()
    source = multi_swe_source(
        three_repo_rows(), resolve_image=lambda _: None, suite=suite
    )

    with pytest.raises(ValueError, match="darkreader__darkreader-7241"):
        source.ensure_tasks_dir(["darkreader__darkreader-7241"], tmp_path)


def test_ensure_tasks_dir_rejects_checksum_drift(tmp_path: Path) -> None:
    suite = multi_swe_source(three_repo_rows()).resolve()

    def moved_image(instance: MultiSweInstance) -> str:
        return pinned_image(instance, digest="f" * 64)

    source = multi_swe_source(three_repo_rows(), resolve_image=moved_image, suite=suite)

    with pytest.raises(ValueError, match="darkreader__darkreader-7241"):
        source.ensure_tasks_dir(["darkreader__darkreader-7241"], tmp_path)
