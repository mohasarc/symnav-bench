from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from symnav_bench.study import (
    BenchmarkName,
    FitTier,
    require_list,
    require_mapping,
    require_string,
)


GitRevisionResolver = Callable[[Path, str], str]
GIT_SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")


@dataclass(frozen=True)
class TaskManifestEntry:
    slug: str
    language: str
    checksum: str
    tier: FitTier | None = None


@dataclass(frozen=True)
class SuiteManifest:
    benchmark: BenchmarkName
    source_revision: str
    tasks: tuple[TaskManifestEntry, ...]
    fingerprint: str


def build_suite_manifest(
    tasks_dir: Path,
    deep_swe_sha: str,
    *,
    resolve_git_revision: GitRevisionResolver | None = None,
) -> SuiteManifest:
    if not tasks_dir.is_dir():
        raise FileNotFoundError(f"tasks dir does not exist: {tasks_dir}")
    resolved_sha = (
        resolve_git_revision(tasks_dir.parent, deep_swe_sha)
        if resolve_git_revision is not None
        else deep_swe_sha
    )
    if not GIT_SHA.fullmatch(resolved_sha):
        raise ValueError("DeepSWE revision must resolve to an immutable git sha")
    tasks = tuple(
        entry
        for task_dir in sorted(tasks_dir.iterdir(), key=lambda path: path.name)
        if (entry := build_task_manifest_entry(task_dir)) is not None
    )
    fingerprint = suite_fingerprint("deepswe", resolved_sha, tasks)
    return SuiteManifest(
        benchmark="deepswe",
        source_revision=resolved_sha,
        tasks=tasks,
        fingerprint=fingerprint,
    )


def parse_suite_manifest(raw: dict[str, Any]) -> SuiteManifest:
    if "deep_swe_sha" not in raw:
        raise ValueError("suite manifest must declare deep_swe_sha")
    source_revision = require_string(raw.get("deep_swe_sha"), "suite deep_swe_sha")
    return SuiteManifest(
        benchmark="deepswe",
        source_revision=source_revision,
        tasks=parse_task_entries(raw.get("tasks")),
        fingerprint=require_string(raw.get("fingerprint"), "suite fingerprint"),
    )


def parse_task_entries(value: object) -> tuple[TaskManifestEntry, ...]:
    return tuple(
        parse_task_entry(require_mapping(task, "suite task"))
        for task in require_list(value, "suite tasks")
    )


def parse_task_entry(data: dict[str, Any]) -> TaskManifestEntry:
    return TaskManifestEntry(
        slug=require_string(data.get("slug"), "suite task slug"),
        language=require_string(data.get("language"), "suite task language"),
        checksum=require_string(data.get("checksum"), "suite task checksum"),
    )


def suite_mapping(suite: SuiteManifest) -> dict[str, Any]:
    return {
        "deep_swe_sha": suite.source_revision,
        "fingerprint": suite.fingerprint,
        "tasks": [task_entry_mapping(task) for task in suite.tasks],
    }


def task_entry_mapping(task: TaskManifestEntry) -> dict[str, Any]:
    return {
        "slug": task.slug,
        "language": task.language,
        "checksum": task.checksum,
    }


def serialize_suite_manifest(suite: SuiteManifest) -> str:
    return json.dumps(suite_mapping(suite), indent=2, sort_keys=True) + "\n"


def build_task_manifest_entry(task_dir: Path) -> TaskManifestEntry | None:
    if not task_dir.is_dir():
        return None
    try:
        task_data = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return None
    metadata = task_data.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("language") != "typescript":
        return None
    return TaskManifestEntry(
        slug=task_dir.name,
        language="typescript",
        checksum=directory_checksum(task_dir),
    )


def directory_checksum(directory: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        (path for path in directory.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(directory).as_posix(),
    )
    for path in files:
        relative_path = path.relative_to(directory).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative_path).to_bytes(8, "big"))
        digest.update(relative_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def suite_fingerprint(
    benchmark: BenchmarkName,
    source_revision: str,
    tasks: tuple[TaskManifestEntry, ...],
) -> str:
    if benchmark != "deepswe":
        raise ValueError(f"suite fingerprint not implemented for benchmark {benchmark!r}")
    value = {
        "deep_swe_sha": source_revision,
        "tasks": [task_entry_mapping(task) for task in tasks],
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
