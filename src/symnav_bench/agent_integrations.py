from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from symnav_bench.run_spec import SYMNAV_COMMANDS, SymnavCommand


CATALOG_PATH = Path(".agents/integrations/symnav/catalog.json")


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
        checkout = symnav_checkout.resolve(strict=True)
        catalog_path = _catalog_file(checkout, CATALOG_PATH.as_posix())
        try:
            payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise ValueError(f"invalid integration catalog: {error}") from error
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
            raise ValueError("unsupported integration catalog schema")
        shared_path = _required_string(payload, "sharedRulesFile")
        shared_rules = _integration_file(checkout, shared_path, PurePosixPath("/app/AGENTS.md"))
        manifests = payload.get("bundles")
        if not isinstance(manifests, list):
            raise ValueError("invalid integration catalog bundles")
        bundles: dict[str, AgentIntegrationBundle] = {}
        for manifest in manifests:
            bundle = _load_bundle(checkout, catalog_path, shared_rules, manifest)
            if bundle.id in bundles:
                raise ValueError(f"duplicate integration bundle {bundle.id!r}")
            bundles[bundle.id] = bundle
        return cls(bundles)

    def bundle(self, bundle_id: str) -> AgentIntegrationBundle:
        try:
            return self._bundles[bundle_id]
        except KeyError as error:
            raise ValueError(f"unknown integration bundle {bundle_id!r}") from error


def _load_bundle(
    checkout: Path,
    catalog_path: Path,
    shared_rules: IntegrationFile,
    raw_manifest: Any,
) -> AgentIntegrationBundle:
    if not isinstance(raw_manifest, dict):
        raise ValueError("invalid integration bundle manifest")
    manifest = cast(dict[str, Any], raw_manifest)
    bundle_id = _required_string(manifest, "id")
    skill_directory_name = _required_string(manifest, "skillDirectory")
    skill_directory = _catalog_directory(checkout, skill_directory_name)
    skill_files = tuple(
        _integration_file(
            checkout,
            path.relative_to(checkout).as_posix(),
            PurePosixPath("/app") / path.relative_to(checkout).as_posix(),
        )
        for path in sorted(skill_directory.rglob("*"))
        if path.is_file()
    )
    if not skill_files:
        raise ValueError(f"missing integration skill files for {bundle_id!r}")
    rules = _integration_file(
        checkout,
        _required_string(manifest, "rulesFile"),
        PurePosixPath("/app/AGENTS.md"),
    )
    claude_settings = _integration_file(
        checkout,
        _required_string(manifest, "claudeSettingsFile"),
        PurePosixPath("/app/.claude/settings.json"),
    )
    claude_hook = _integration_file(
        checkout,
        _required_string(manifest, "claudeHookFile"),
        PurePosixPath("/tmp/symnav-bench/symnav-nudge.js"),
    )
    allowed_commands = _allowed_commands(manifest, bundle_id)
    hashed_paths = [
        catalog_path,
        shared_rules.source,
        *(file.source for file in skill_files),
        rules.source,
        claude_settings.source,
        claude_hook.source,
    ]
    return AgentIntegrationBundle(
        id=bundle_id,
        shared_rules=shared_rules,
        skill_directory=skill_directory,
        skill_files=skill_files,
        rules=rules,
        allowed_commands=allowed_commands,
        claude_settings=claude_settings,
        claude_hook=claude_hook,
        content_hash=_content_hash(checkout, hashed_paths),
    )


def _allowed_commands(manifest: dict[str, Any], bundle_id: str) -> tuple[SymnavCommand, ...]:
    raw_commands = manifest.get("allowedCommands")
    if not isinstance(raw_commands, list) or not all(command in SYMNAV_COMMANDS for command in raw_commands):
        raise ValueError(f"invalid commands for integration bundle {bundle_id!r}")
    commands = cast(tuple[SymnavCommand, ...], tuple(raw_commands))
    expected = SYMNAV_COMMANDS if bundle_id == "full" else tuple(bundle_id.split("-"))
    if commands != expected:
        raise ValueError(f"commands do not match integration bundle {bundle_id!r}")
    return commands


def _required_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid integration catalog field {key!r}")
    return value


def _integration_file(checkout: Path, name: str, destination: PurePosixPath) -> IntegrationFile:
    source = _catalog_file(checkout, name)
    return IntegrationFile(
        source=source,
        destination=destination,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )


def _catalog_file(checkout: Path, name: str) -> Path:
    source = _catalog_path(checkout, name)
    if not source.is_file():
        raise ValueError(f"missing integration catalog file {name!r}")
    return source


def _catalog_directory(checkout: Path, name: str) -> Path:
    source = _catalog_path(checkout, name)
    if not source.is_dir():
        raise ValueError(f"missing integration catalog directory {name!r}")
    return source


def _catalog_path(checkout: Path, name: str) -> Path:
    unresolved = checkout / name
    try:
        unresolved.resolve(strict=False).relative_to(checkout)
    except ValueError as error:
        raise ValueError(f"integration catalog path escapes checkout: {name!r}") from error
    try:
        resolved = unresolved.resolve(strict=True)
        resolved.relative_to(checkout)
    except FileNotFoundError as error:
        raise ValueError(f"missing integration catalog path {name!r}") from error
    except ValueError as error:
        raise ValueError(f"integration catalog path escapes checkout: {name!r}") from error
    return resolved


def _content_hash(checkout: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.relative_to(checkout).as_posix()):
        relative = path.relative_to(checkout).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
