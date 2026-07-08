from __future__ import annotations

import tomllib
from pathlib import Path


def list_tasks(tasks_dir: Path) -> list[str]:
    if not tasks_dir.exists():
        raise FileNotFoundError(f"tasks dir does not exist: {tasks_dir}")
    if not tasks_dir.is_dir():
        raise NotADirectoryError(f"tasks dir is not a directory: {tasks_dir}")
    return sorted(path.name for path in tasks_dir.iterdir() if is_typescript_task(path))


def is_typescript_task(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        data = tomllib.loads((path / "task.toml").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return False
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return False
    return metadata.get("language") == "typescript"
