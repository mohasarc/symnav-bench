from __future__ import annotations

import pytest

from symnav_bench.cli import main
from symnav_bench.tasks import list_tasks


def test_list_tasks_returns_sorted_subdirectories(tmp_path) -> None:
    (tmp_path / "b").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "file").write_text("", encoding="utf-8")
    assert list_tasks(tmp_path) == ["a", "b"]


def test_list_tasks_missing_dir_is_clear(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="tasks dir does not exist"):
        list_tasks(tmp_path / "missing")


def test_list_tasks_cli_smoke(tmp_path, capsys) -> None:
    (tmp_path / "task").mkdir()
    assert main(["list-tasks", "--tasks-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "task\n"
