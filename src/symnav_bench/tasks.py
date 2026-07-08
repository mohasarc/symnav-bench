from __future__ import annotations

from pathlib import Path


def list_tasks(tasks_dir: Path) -> list[str]:
    if not tasks_dir.exists():
        raise FileNotFoundError(f"tasks dir does not exist: {tasks_dir}")
    if not tasks_dir.is_dir():
        raise NotADirectoryError(f"tasks dir is not a directory: {tasks_dir}")
    return sorted(path.name for path in tasks_dir.iterdir() if path.is_dir())
