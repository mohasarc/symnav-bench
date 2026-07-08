from __future__ import annotations

import pytest

from symnav_bench.cli import main
from symnav_bench.deepswe import TASK_SLUGS, ensure_deepswe_tasks
from symnav_bench.tasks import list_tasks


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


def write_task(path, language: str) -> None:
    path.mkdir()
    (path / "task.toml").write_text(
        f'[metadata]\nlanguage = "{language}"\n',
        encoding="utf-8",
    )
