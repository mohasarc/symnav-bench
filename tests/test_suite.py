from __future__ import annotations

import json
from pathlib import Path

import pytest

from symnav_bench.suite import (
    TaskManifestEntry,
    build_suite_manifest,
    parse_suite_manifest,
    serialize_suite_manifest,
    suite_fingerprint,
    suite_mapping,
)

COMMITTED_V1_SUITE = Path(__file__).parent / "fixtures" / "studies" / "deepswe-v1-suite.json"
COMMITTED_V1_SUITE_FINGERPRINT = (
    "2bc576336ca85c7750a00c7d4bc3bb56e7bd372840ce5f699601a9a4b488d1b3"
)
COMMITTED_V1_DEEP_SWE_SHA = "6db64a40f3318d8659238ff34a8cc4b491c49205"


def committed_v1_suite_text() -> str:
    return COMMITTED_V1_SUITE.read_text(encoding="utf-8")


def test_committed_deepswe_suite_parses_as_deepswe_benchmark() -> None:
    suite = parse_suite_manifest(json.loads(committed_v1_suite_text()))

    assert suite.benchmark == "deepswe"
    assert suite.source_revision == COMMITTED_V1_DEEP_SWE_SHA
    assert suite.fingerprint == COMMITTED_V1_SUITE_FINGERPRINT
    assert [task.slug for task in suite.tasks] == ["ts-pattern-match-each"]
    assert all(task.tier is None for task in suite.tasks)


def test_committed_deepswe_suite_round_trips_byte_identically() -> None:
    raw_text = committed_v1_suite_text()

    suite = parse_suite_manifest(json.loads(raw_text))

    assert serialize_suite_manifest(suite) == raw_text


def test_committed_deepswe_suite_fingerprint_reproduces() -> None:
    suite = parse_suite_manifest(json.loads(committed_v1_suite_text()))

    recomputed = suite_fingerprint(suite.benchmark, suite.source_revision, suite.tasks)

    assert recomputed == COMMITTED_V1_SUITE_FINGERPRINT


def v2_polybench_suite_data() -> dict:
    return {
        "benchmark": "swe-polybench",
        "source_revision": "b" * 40,
        "fingerprint": "f" * 64,
        "tasks": [
            {
                "slug": "amazon__ion-js-717",
                "language": "typescript",
                "checksum": "1" * 64,
                "tier": "mid",
            },
            {
                "slug": "microsoft__vscode-106767",
                "language": "typescript",
                "checksum": "2" * 64,
                "tier": "high",
            },
        ],
    }


def v2_multi_swe_suite_data() -> dict:
    return {
        "benchmark": "multi-swe-bench",
        "source_revision": "c" * 40,
        "fingerprint": "e" * 64,
        "tasks": [
            {
                "slug": "vuejs__core-11739",
                "language": "typescript",
                "checksum": "3" * 64,
            },
        ],
    }


def test_v2_polybench_suite_parses_with_per_task_tiers() -> None:
    suite = parse_suite_manifest(v2_polybench_suite_data())

    assert suite.benchmark == "swe-polybench"
    assert suite.source_revision == "b" * 40
    assert suite.fingerprint == "f" * 64
    assert [task.slug for task in suite.tasks] == [
        "amazon__ion-js-717",
        "microsoft__vscode-106767",
    ]
    assert [task.tier for task in suite.tasks] == ["mid", "high"]


def test_v2_multi_swe_suite_parses_without_tiers() -> None:
    suite = parse_suite_manifest(v2_multi_swe_suite_data())

    assert suite.benchmark == "multi-swe-bench"
    assert suite.source_revision == "c" * 40
    assert [task.slug for task in suite.tasks] == ["vuejs__core-11739"]
    assert all(task.tier is None for task in suite.tasks)


def test_v2_suite_round_trips_through_mapping() -> None:
    suite = parse_suite_manifest(v2_polybench_suite_data())

    mapping = suite_mapping(suite)

    assert "deep_swe_sha" not in mapping
    assert mapping["benchmark"] == "swe-polybench"
    assert mapping["source_revision"] == "b" * 40
    assert [task["tier"] for task in mapping["tasks"]] == ["mid", "high"]
    assert parse_suite_manifest(mapping) == suite


def test_v2_multi_swe_mapping_omits_tier_key() -> None:
    suite = parse_suite_manifest(v2_multi_swe_suite_data())

    mapping = suite_mapping(suite)

    assert all("tier" not in task for task in mapping["tasks"])
    assert parse_suite_manifest(mapping) == suite


def test_v2_fingerprint_covers_benchmark_revision_and_tier() -> None:
    high_task = (TaskManifestEntry("task", "typescript", "1" * 64, "high"),)
    mid_task = (TaskManifestEntry("task", "typescript", "1" * 64, "mid"),)
    untiered_task = (TaskManifestEntry("task", "typescript", "1" * 64),)

    polybench = suite_fingerprint("swe-polybench", "b" * 40, high_task)

    assert polybench != suite_fingerprint("swe-polybench", "b" * 40, mid_task)
    assert polybench != suite_fingerprint("swe-polybench", "c" * 40, high_task)
    assert suite_fingerprint("multi-swe-bench", "b" * 40, untiered_task) != suite_fingerprint(
        "swe-polybench", "b" * 40, untiered_task
    )


@pytest.mark.parametrize(
    ("description", "mutate"),
    [
        ("unknown benchmark name", lambda data: data.update(benchmark="swe-bench")),
        (
            "invalid tier value",
            lambda data: data["tasks"][0].update(tier="extreme"),
        ),
        (
            "missing source revision",
            lambda data: data.pop("source_revision"),
        ),
    ],
)
def test_rejects_invalid_v2_suite(description: str, mutate) -> None:
    data = v2_polybench_suite_data()
    mutate(data)

    with pytest.raises(ValueError):
        parse_suite_manifest(data)


def test_rejects_tier_on_multi_swe_suite() -> None:
    data = v2_multi_swe_suite_data()
    data["tasks"][0]["tier"] = "high"

    with pytest.raises(ValueError, match="tier"):
        parse_suite_manifest(data)


def test_rejects_tier_on_legacy_deepswe_suite() -> None:
    data = json.loads(committed_v1_suite_text())
    data["tasks"][0]["tier"] = "high"

    with pytest.raises(ValueError, match="tier"):
        parse_suite_manifest(data)


def test_builds_sorted_typescript_suite_and_resolves_revision_once(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    write_task(tasks_dir / "zeta", "typescript", "zeta")
    write_task(tasks_dir / "alpha", "typescript", "alpha")
    write_task(tasks_dir / "python-task", "python", "python")
    write_task(tasks_dir / "go-task", "go", "go")
    calls: list[tuple[Path, str]] = []

    def resolve_revision(checkout: Path, ref: str) -> str:
        calls.append((checkout, ref))
        return "a" * 40

    suite = build_suite_manifest(
        tasks_dir,
        "refs/tags/benchmark-v1",
        resolve_git_revision=resolve_revision,
    )

    assert calls == [(tmp_path, "refs/tags/benchmark-v1")]
    assert suite.benchmark == "deepswe"
    assert suite.source_revision == "a" * 40
    assert [task.slug for task in suite.tasks] == ["alpha", "zeta"]
    assert all(task.language == "typescript" for task in suite.tasks)
    assert all(len(task.checksum) == 64 for task in suite.tasks)


def test_task_content_changes_task_and_suite_fingerprints(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    task_dir = tasks_dir / "task"
    write_task(task_dir, "typescript", "before")
    before = build_suite_manifest(tasks_dir, "a" * 40)

    (task_dir / "nested" / "source.ts").write_text("after", encoding="utf-8")
    after = build_suite_manifest(tasks_dir, "a" * 40)

    assert before.tasks[0].checksum != after.tasks[0].checksum
    assert before.fingerprint != after.fingerprint


def test_task_creation_order_does_not_change_suite_fingerprint(tmp_path: Path) -> None:
    first = tmp_path / "first" / "tasks"
    write_task(first / "alpha", "typescript", "alpha")
    write_task(first / "zeta", "typescript", "zeta")
    second = tmp_path / "second" / "tasks"
    write_task(second / "zeta", "typescript", "zeta")
    write_task(second / "alpha", "typescript", "alpha")

    first_suite = build_suite_manifest(first, "a" * 40)
    second_suite = build_suite_manifest(second, "a" * 40)

    assert first_suite.tasks == second_suite.tasks
    assert first_suite.fingerprint == second_suite.fingerprint


def write_task(path: Path, language: str, source: str) -> None:
    (path / "nested").mkdir(parents=True)
    (path / "task.toml").write_text(
        f'[metadata]\nlanguage = "{language}"\n',
        encoding="utf-8",
    )
    (path / "nested" / "source.ts").write_text(source, encoding="utf-8")
