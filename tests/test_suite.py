from __future__ import annotations

import json
from pathlib import Path

from symnav_bench.suite import (
    build_suite_manifest,
    parse_suite_manifest,
    serialize_suite_manifest,
    suite_fingerprint,
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
    assert suite.deep_swe_sha == "a" * 40
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
