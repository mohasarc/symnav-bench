from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


GitRevisionResolver = Callable[[Path, str], str]


@dataclass(frozen=True)
class TaskManifestEntry:
    slug: str
    language: str
    checksum: str


@dataclass(frozen=True)
class SuiteManifest:
    deep_swe_sha: str
    tasks: tuple[TaskManifestEntry, ...]
    fingerprint: str


def build_suite_manifest(
    tasks_dir: Path,
    deep_swe_sha: str,
    *,
    resolve_git_revision: GitRevisionResolver | None = None,
) -> SuiteManifest:
    raise NotImplementedError
