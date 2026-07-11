from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from symnav_bench.run_spec import SymnavCommand


@dataclass(frozen=True)
class IntegrationFile:
    source: Path
    destination: PurePosixPath
    sha256: str


@dataclass(frozen=True)
class AgentIntegrationBundle:
    id: str
    shared_rules: IntegrationFile
    skill_directory: Path
    skill_files: tuple[IntegrationFile, ...]
    rules: IntegrationFile
    allowed_commands: tuple[SymnavCommand, ...]
    claude_settings: IntegrationFile
    claude_hook: IntegrationFile
    content_hash: str


class SymnavIntegrationCatalog:
    def __init__(self, bundles: dict[str, AgentIntegrationBundle]) -> None:
        self._bundles = bundles

    @classmethod
    def load(cls, symnav_checkout: Path) -> "SymnavIntegrationCatalog":
        raise NotImplementedError

    def bundle(self, bundle_id: str) -> AgentIntegrationBundle:
        raise NotImplementedError
