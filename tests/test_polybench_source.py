from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

import symnav_bench.deepswe
from symnav_bench.benchmark_sources import benchmark_task_source, swe_polybench_source
from symnav_bench.benchmark_sources.swe_polybench_source import (
    PolybenchChangeShape,
    SwePolybenchTaskSource,
    fit_tier,
    parse_polybench_rows,
)
from symnav_bench.cli import main
from symnav_bench.study import BenchmarkSelection
from symnav_bench.suite import suite_fingerprint

POLYBENCH_REVISION = "a" * 40


def change_shape(
    *,
    is_no_nodes: bool = False,
    is_single_func: bool = False,
    is_single_class: bool = False,
    num_func_changes: int = 2,
    num_class_changes: int = 1,
    modified_nodes: int = 2,
) -> PolybenchChangeShape:
    return PolybenchChangeShape(
        is_no_nodes=is_no_nodes,
        is_single_func=is_single_func,
        is_single_class=is_single_class,
        num_func_changes=num_func_changes,
        num_class_changes=num_class_changes,
        modified_nodes=modified_nodes,
    )


def dataset_row(**overrides: str) -> dict[str, str]:
    row = {
        "instance_id": "microsoft__vscode-106767",
        "repo": "microsoft/vscode",
        "pull_number": "106767",
        "base_commit": "c" * 40,
        "patch": "diff --git a/src/main.ts b/src/main.ts",
        "test_patch": "diff --git a/test.ts b/test.ts",
        "problem_statement": "statement",
        "language": "TypeScript",
        "Dockerfile": "FROM node:18",
        "P2P": "['suite keeps the old case', 'suite keeps another case']",
        "F2P": "['suite renders the fixed case']",
        "F2F": "[]",
        "test_command": "yarn test --run suite",
        "task_category": "Bug Fix",
        "is_no_nodes": "False",
        "is_single_func": "False",
        "is_single_class": "False",
        "num_func_changes": "2",
        "num_class_changes": "1",
        "modified_nodes": '["a.ts->program->f1", "a.ts->program->f2"]',
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        (change_shape(is_single_func=True, modified_nodes=9), "low"),
        (change_shape(is_single_class=True, num_func_changes=9), "low"),
        (
            change_shape(
                is_no_nodes=True,
                modified_nodes=9,
                num_func_changes=9,
                num_class_changes=9,
            ),
            "low",
        ),
        (change_shape(modified_nodes=6, num_func_changes=1, num_class_changes=0), "high"),
        (change_shape(modified_nodes=2, num_func_changes=3, num_class_changes=1), "high"),
        (change_shape(modified_nodes=5, num_func_changes=2, num_class_changes=1), "mid"),
    ],
)
def test_fit_tier_assigns_exactly_one_tier_per_branch(
    shape: PolybenchChangeShape, expected: str
) -> None:
    assert fit_tier(shape) == expected


def test_parse_rows_keeps_only_typescript_rows() -> None:
    rows = [
        dataset_row(instance_id="ts-1", language="TypeScript"),
        dataset_row(instance_id="js-1", language="JavaScript"),
        dataset_row(instance_id="java-1", language="Java"),
        dataset_row(instance_id="py-1", language="Python"),
    ]

    instances = parse_polybench_rows(rows)

    assert [instance.instance_id for instance in instances] == ["ts-1"]


def test_parse_rows_reads_instance_fields_and_change_shape() -> None:
    instance = parse_polybench_rows([dataset_row()])[0]

    assert instance.instance_id == "microsoft__vscode-106767"
    assert instance.repo == "microsoft/vscode"
    assert instance.base_commit == "c" * 40
    assert instance.problem_statement == "statement"
    assert instance.test_patch == "diff --git a/test.ts b/test.ts"
    assert instance.f2p == ("suite renders the fixed case",)
    assert instance.p2p == ("suite keeps the old case", "suite keeps another case")
    assert instance.test_command == "yarn test --run suite"
    assert instance.dockerfile == "FROM node:18"
    assert instance.change_shape == change_shape(
        num_func_changes=2, num_class_changes=1, modified_nodes=2
    )


@pytest.mark.parametrize(
    "column",
    [
        "is_no_nodes",
        "is_single_func",
        "is_single_class",
        "num_func_changes",
        "num_class_changes",
        "modified_nodes",
    ],
)
def test_missing_change_shape_column_errors_naming_the_instance(column: str) -> None:
    row = dataset_row()
    del row[column]

    with pytest.raises(ValueError, match="microsoft__vscode-106767") as error:
        parse_polybench_rows([row])
    assert column in str(error.value)


@pytest.mark.parametrize(
    "column",
    [
        "is_no_nodes",
        "is_single_func",
        "is_single_class",
        "num_func_changes",
        "num_class_changes",
        "modified_nodes",
    ],
)
def test_empty_change_shape_value_errors_naming_the_instance(column: str) -> None:
    row = dataset_row(**{column: ""})

    with pytest.raises(ValueError, match="microsoft__vscode-106767"):
        parse_polybench_rows([row])


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("is_single_func", "yes"),
        ("num_func_changes", "two"),
        ("modified_nodes", "not a list"),
        ("modified_nodes", "3"),
        ("F2P", "not a list"),
        ("P2P", "['name', 3]"),
    ],
)
def test_malformed_row_value_errors_naming_the_instance(column: str, value: str) -> None:
    row = dataset_row(**{column: value})

    with pytest.raises(ValueError, match="microsoft__vscode-106767"):
        parse_polybench_rows([row])


def test_f2f_column_present_absent_or_populated_is_tolerated() -> None:
    with_empty_f2f = dataset_row()
    without_f2f = dataset_row()
    del without_f2f["F2F"]
    with_populated_f2f = dataset_row(F2F="['suite stays broken']")

    parsed = [
        parse_polybench_rows([row])
        for row in (with_empty_f2f, without_f2f, with_populated_f2f)
    ]

    assert parsed[0] == parsed[1] == parsed[2]


def tiered_rows() -> list[dict[str, str]]:
    return [
        dataset_row(
            instance_id="b-high",
            modified_nodes='["n1", "n2", "n3", "n4", "n5", "n6"]',
            num_func_changes="1",
            num_class_changes="0",
        ),
        dataset_row(instance_id="c-mid"),
        dataset_row(instance_id="a-low", is_single_func="True"),
        dataset_row(instance_id="js-1", language="JavaScript"),
    ]


def polybench_source(
    rows: list[dict[str, str]], tiers: tuple[str, ...] = ("high", "mid")
) -> SwePolybenchTaskSource:
    selection = BenchmarkSelection(
        name="swe-polybench", source_revision=POLYBENCH_REVISION, tiers=tiers
    )
    return SwePolybenchTaskSource(
        selection, load_rows=lambda revision: rows, resolve_image=pinned_image
    )


def test_factory_returns_polybench_source_for_polybench_selection() -> None:
    selection = BenchmarkSelection(
        name="swe-polybench", source_revision=POLYBENCH_REVISION, tiers=("high",)
    )

    source = benchmark_task_source(selection)

    assert isinstance(source, SwePolybenchTaskSource)
    assert source.selection == selection


def test_resolve_builds_sorted_v2_suite_for_selected_tiers() -> None:
    suite = polybench_source(tiered_rows()).resolve()

    assert suite.benchmark == "swe-polybench"
    assert suite.source_revision == POLYBENCH_REVISION
    assert [task.slug for task in suite.tasks] == ["b-high", "c-mid"]
    assert [task.tier for task in suite.tasks] == ["high", "mid"]
    assert all(task.language == "typescript" for task in suite.tasks)
    assert suite.fingerprint == suite_fingerprint(
        "swe-polybench", POLYBENCH_REVISION, suite.tasks
    )


def test_resolve_with_all_tiers_keeps_every_typescript_task() -> None:
    suite = polybench_source(tiered_rows(), tiers=("high", "mid", "low")).resolve()

    assert [task.slug for task in suite.tasks] == ["a-low", "b-high", "c-mid"]
    assert [task.tier for task in suite.tasks] == ["low", "high", "mid"]


def test_resolve_rejects_empty_tier_selection_result() -> None:
    rows = [dataset_row(instance_id="a-low", is_single_func="True")]

    with pytest.raises(ValueError, match="no tasks"):
        polybench_source(rows, tiers=("high",)).resolve()


def test_resolve_rejects_selection_without_tiers() -> None:
    selection = BenchmarkSelection(
        name="swe-polybench", source_revision=POLYBENCH_REVISION, tiers=None
    )

    with pytest.raises(ValueError, match="tiers"):
        SwePolybenchTaskSource(selection, load_rows=lambda revision: []).resolve()


def test_resolve_is_deterministic_and_checksum_is_content_sensitive() -> None:
    assert polybench_source(tiered_rows()).resolve() == polybench_source(
        tiered_rows()
    ).resolve()

    edited_rows = tiered_rows()
    edited_rows[0]["test_patch"] = "diff --git a/other.ts b/other.ts"
    original = polybench_source(tiered_rows()).resolve()
    edited = polybench_source(edited_rows).resolve()

    assert original.tasks[0].checksum != edited.tasks[0].checksum
    assert original.fingerprint != edited.fingerprint


def test_resolve_passes_pinned_revision_to_loader() -> None:
    revisions: list[str] = []

    def load_rows(revision: str) -> list[dict[str, str]]:
        revisions.append(revision)
        return tiered_rows()

    selection = BenchmarkSelection(
        name="swe-polybench", source_revision=POLYBENCH_REVISION, tiers=("high",)
    )
    SwePolybenchTaskSource(
        selection, load_rows=load_rows, resolve_image=pinned_image
    ).resolve()

    assert revisions == [POLYBENCH_REVISION]


def polybench_manifest_data() -> dict:
    protocol = {
        "benchmark": {
            "name": "swe-polybench",
            "source": {"revision": POLYBENCH_REVISION},
            "tiers": ["high", "mid"],
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
        "id": "swe-polybench-ts-himid-test",
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


def fingerprint(protocol: dict) -> str:
    canonical = json.dumps(protocol, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def write_manifest(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(copy.deepcopy(data), sort_keys=False), encoding="utf-8")
    return path


def test_resolve_suite_cli_writes_identical_polybench_suites_across_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        swe_polybench_source, "load_dataset_rows", lambda revision: tiered_rows()
    )
    monkeypatch.setattr(swe_polybench_source, "resolve_eval_image", pinned_image)
    manifest = write_manifest(tmp_path / "manifest.yml", polybench_manifest_data())
    first_out = tmp_path / "first-suite.json"
    second_out = tmp_path / "second-suite.json"

    assert main(["resolve-suite", "--study", str(manifest), "--out", str(first_out)]) == 0
    assert main(["resolve-suite", "--study", str(manifest), "--out", str(second_out)]) == 0

    assert first_out.read_bytes() == second_out.read_bytes()
    payload = json.loads(first_out.read_text(encoding="utf-8"))
    assert payload["benchmark"] == "swe-polybench"
    assert payload["source_revision"] == POLYBENCH_REVISION
    assert [task["tier"] for task in payload["tasks"]] == ["high", "mid"]
    assert "swe-polybench-ts-himid-test: 2 tasks, 8 slots" in capsys.readouterr().out


def test_resolve_suite_cli_resolves_deepswe_studies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checkout = tmp_path / "deep-swe"
    (checkout / ".git").mkdir(parents=True)
    task_dir = checkout / "tasks" / "alpha"
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(
        '[metadata]\nlanguage = "typescript"\n', encoding="utf-8"
    )
    monkeypatch.setenv("DEEPSWE_ROOT", str(checkout))
    monkeypatch.setattr(symnav_bench.deepswe, "_run", lambda command: None)
    data = polybench_manifest_data()
    data["id"] = "deepswe-ts-test"
    data["protocol"]["benchmark"] = {
        "name": "deepswe",
        "source": {"revision": POLYBENCH_REVISION},
    }
    data["protocol_fingerprint"] = fingerprint(data["protocol"])
    manifest = write_manifest(tmp_path / "manifest.yml", data)
    out = tmp_path / "suite.json"

    assert main(["resolve-suite", "--study", str(manifest), "--out", str(out)]) == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["deep_swe_sha"] == POLYBENCH_REVISION
    assert "benchmark" not in payload
    assert [task["slug"] for task in payload["tasks"]] == ["alpha"]
    assert "deepswe-ts-test: 1 tasks, 4 slots" in capsys.readouterr().out


def pinned_image(instance_id: str, digest: str = "0" * 64) -> str:
    return (
        "ghcr.io/timesler/swe-polybench.eval.x86_64."
        + instance_id.lower()
        + "@sha256:"
        + digest
    )


def materializing_source(
    rows: list[dict[str, str]],
    tiers: tuple[str, ...] = ("high", "mid"),
    resolve_image=pinned_image,
    suite=None,
    resolve_workdir=lambda image: "/testbed",
) -> SwePolybenchTaskSource:
    selection = BenchmarkSelection(
        name="swe-polybench", source_revision=POLYBENCH_REVISION, tiers=tiers
    )
    return SwePolybenchTaskSource(
        selection,
        load_rows=lambda revision: rows,
        resolve_image=resolve_image,
        suite=suite,
        resolve_workdir=resolve_workdir,
    )


def test_resolve_checksums_match_runtime_materialization(tmp_path: Path) -> None:
    from pier.models.task.paths import TaskPaths

    from symnav_bench.suite import directory_checksum

    suite = materializing_source(tiered_rows()).resolve()
    source = materializing_source(tiered_rows(), suite=suite)

    tasks_dir = source.ensure_tasks_dir(["b-high"], tmp_path)

    task_dir = tasks_dir / "b-high"
    assert TaskPaths(task_dir).is_valid()
    declared = {task.slug: task.checksum for task in suite.tasks}
    assert directory_checksum(task_dir) == declared["b-high"]


def test_ensure_tasks_dir_materializes_only_requested_slugs(tmp_path: Path) -> None:
    suite = materializing_source(tiered_rows()).resolve()
    source = materializing_source(tiered_rows(), suite=suite)

    source.ensure_tasks_dir(["b-high"], tmp_path)

    assert (tmp_path / "b-high").is_dir()
    assert not (tmp_path / "c-mid").exists()


def test_materialized_task_carries_instance_content(tmp_path: Path) -> None:
    import json as json_module

    from symnav_bench.benchmark_sources.grading import grade_script_source

    suite = materializing_source(tiered_rows()).resolve()
    source = materializing_source(tiered_rows(), suite=suite)

    task_dir = source.ensure_tasks_dir(["b-high"], tmp_path) / "b-high"

    assert (task_dir / "instruction.md").read_text(encoding="utf-8") == "statement"
    config = json_module.loads(
        (task_dir / "tests" / "config.json").read_text(encoding="utf-8")
    )
    assert config["log_parser"] == "mocha"
    assert config["docker_image"] == pinned_image("b-high")
    assert config["base_commit"] == "c" * 40
    grade = (task_dir / "tests" / "grade.py").read_text(encoding="utf-8")
    assert grade == grade_script_source()
    task_toml = (task_dir / "task.toml").read_text(encoding="utf-8")
    assert "docker_image" not in task_toml
    environment_dockerfile = (task_dir / "environment" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert pinned_image("b-high") in environment_dockerfile


def test_resolve_excludes_instances_without_eval_images(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def only_high_published(instance_id: str) -> str | None:
        return pinned_image(instance_id) if instance_id == "b-high" else None

    suite = materializing_source(
        tiered_rows(), resolve_image=only_high_published
    ).resolve()

    assert [task.slug for task in suite.tasks] == ["b-high"]
    stderr = capsys.readouterr().err
    assert "excluded 1 of 2" in stderr
    assert "c-mid" in stderr


def test_resolve_errors_when_no_selected_instance_has_an_image() -> None:
    with pytest.raises(ValueError, match="no tasks"):
        materializing_source(tiered_rows(), resolve_image=lambda _: None).resolve()


def test_resolve_rejects_repo_without_log_parser() -> None:
    rows = [dataset_row(repo="unknown/repo")]

    with pytest.raises(ValueError, match="unknown/repo"):
        materializing_source(rows).resolve()


def test_ensure_tasks_dir_requires_declared_suite(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="suite"):
        materializing_source(tiered_rows()).ensure_tasks_dir(["b-high"], tmp_path)


def test_ensure_tasks_dir_rejects_slug_missing_from_suite(tmp_path: Path) -> None:
    suite = materializing_source(tiered_rows()).resolve()
    source = materializing_source(tiered_rows(), suite=suite)

    with pytest.raises(ValueError, match="a-low"):
        source.ensure_tasks_dir(["a-low"], tmp_path)


def test_ensure_tasks_dir_rejects_slug_missing_from_dataset(tmp_path: Path) -> None:
    suite = materializing_source(tiered_rows()).resolve()
    shrunken = [row for row in tiered_rows() if row["instance_id"] != "b-high"]
    source = materializing_source(shrunken, suite=suite)

    with pytest.raises(ValueError, match="b-high"):
        source.ensure_tasks_dir(["b-high"], tmp_path)


def test_ensure_tasks_dir_rejects_vanished_eval_image(tmp_path: Path) -> None:
    suite = materializing_source(tiered_rows()).resolve()
    source = materializing_source(tiered_rows(), resolve_image=lambda _: None, suite=suite)

    with pytest.raises(ValueError, match="b-high"):
        source.ensure_tasks_dir(["b-high"], tmp_path)


def test_ensure_tasks_dir_rejects_checksum_drift(tmp_path: Path) -> None:
    suite = materializing_source(tiered_rows()).resolve()

    def moved_image(instance_id: str) -> str:
        return pinned_image(instance_id, digest="f" * 64)

    source = materializing_source(tiered_rows(), resolve_image=moved_image, suite=suite)

    with pytest.raises(ValueError, match="b-high"):
        source.ensure_tasks_dir(["b-high"], tmp_path)


def test_materialized_workdir_comes_from_the_eval_image(tmp_path: Path) -> None:
    suite = materializing_source(
        tiered_rows(), resolve_workdir=lambda image: "/repo"
    ).resolve()
    source = materializing_source(
        tiered_rows(), suite=suite, resolve_workdir=lambda image: "/repo"
    )

    task_dir = source.ensure_tasks_dir(["b-high"], tmp_path) / "b-high"

    task_toml = (task_dir / "task.toml").read_text(encoding="utf-8")
    assert 'workdir = "/repo"' in task_toml
    run_tests = (task_dir / "tests" / "run_tests.sh").read_text(encoding="utf-8")
    assert "cd /repo" in run_tests


def test_image_without_working_dir_is_a_hard_error() -> None:
    with pytest.raises(ValueError, match="working dir"):
        materializing_source(
            tiered_rows(), resolve_workdir=lambda image: ""
        ).resolve()
