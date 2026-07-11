from __future__ import annotations

from pathlib import Path

from symnav_bench.suite import build_suite_manifest


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
