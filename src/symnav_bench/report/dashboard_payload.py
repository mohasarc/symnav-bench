from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactPointer:
    archive_url: str | None
    archive_sha256: str | None
    archive_path: str | None
    direct_urls: dict[str, str]


@dataclass(frozen=True)
class DashboardPayload:
    schema_version: int
    study: dict[str, Any]
    coverage: dict[str, Any]
    configurations: tuple[dict[str, Any], ...]
    comparisons: tuple[dict[str, Any], ...]
    tasks: tuple[dict[str, Any], ...]
    versions: tuple[dict[str, Any], ...]
    official_references: tuple[dict[str, Any], ...]
    attempts: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
