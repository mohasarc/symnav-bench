from __future__ import annotations

import hashlib
import json
import base64
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, cast

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

    def job_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content_hash": self.content_hash,
            "allowed_commands": list(self.allowed_commands),
            "shared_rules": _job_file_payload(self.shared_rules),
            "skill_files": [_job_file_payload(file) for file in self.skill_files],
            "rules": _job_file_payload(self.rules),
            "claude_settings": _job_file_payload(self.claude_settings),
            "claude_hook": _job_file_payload(self.claude_hook),
        }


@dataclass(frozen=True)
class RuntimeIntegrationFile:
    destination: PurePosixPath
    sha256: str
    content: bytes


@dataclass(frozen=True)
class RuntimeAgentIntegrationBundle:
    id: str
    shared_rules: RuntimeIntegrationFile
    skill_files: tuple[RuntimeIntegrationFile, ...]
    rules: RuntimeIntegrationFile
    allowed_commands: tuple[SymnavCommand, ...]
    claude_settings: RuntimeIntegrationFile
    claude_hook: RuntimeIntegrationFile
    content_hash: str


def runtime_integration_bundle(
    value: AgentIntegrationBundle | Mapping[str, Any],
) -> RuntimeAgentIntegrationBundle:
    if isinstance(value, AgentIntegrationBundle):
        return RuntimeAgentIntegrationBundle(
            id=value.id,
            shared_rules=_runtime_file(value.shared_rules),
            skill_files=tuple(_runtime_file(file) for file in value.skill_files),
            rules=_runtime_file(value.rules),
            allowed_commands=value.allowed_commands,
            claude_settings=_runtime_file(value.claude_settings),
            claude_hook=_runtime_file(value.claude_hook),
            content_hash=value.content_hash,
        )
    bundle_id = _payload_string(value, "id")
    raw_commands = value.get("allowed_commands")
    if not isinstance(raw_commands, list) or not all(command in SYMNAV_COMMANDS for command in raw_commands):
        raise ValueError("invalid runtime integration commands")
    return RuntimeAgentIntegrationBundle(
        id=bundle_id,
        shared_rules=_runtime_payload_file(value.get("shared_rules")),
        skill_files=tuple(_runtime_payload_file(file) for file in _payload_list(value, "skill_files")),
        rules=_runtime_payload_file(value.get("rules")),
        allowed_commands=cast(tuple[SymnavCommand, ...], tuple(raw_commands)),
        claude_settings=_runtime_payload_file(value.get("claude_settings")),
        claude_hook=_runtime_payload_file(value.get("claude_hook")),
        content_hash=_payload_string(value, "content_hash"),
    )


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


def _job_file_payload(integration_file: IntegrationFile) -> dict[str, str]:
    return {
        "destination": integration_file.destination.as_posix(),
        "sha256": integration_file.sha256,
        "content_base64": base64.b64encode(integration_file.source.read_bytes()).decode("ascii"),
    }


def _runtime_file(integration_file: IntegrationFile) -> RuntimeIntegrationFile:
    return RuntimeIntegrationFile(
        destination=integration_file.destination,
        sha256=integration_file.sha256,
        content=integration_file.source.read_bytes(),
    )


def _runtime_payload_file(value: object) -> RuntimeIntegrationFile:
    if not isinstance(value, Mapping):
        raise ValueError("invalid runtime integration file")
    destination = _payload_string(value, "destination")
    expected_sha256 = _payload_string(value, "sha256")
    encoded = _payload_string(value, "content_base64")
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("invalid runtime integration file encoding") from error
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("runtime integration file hash mismatch")
    return RuntimeIntegrationFile(PurePosixPath(destination), expected_sha256, content)


def _payload_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid runtime integration field {key!r}")
    return value


def _payload_list(mapping: Mapping[str, Any], key: str) -> list[Any]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise ValueError(f"invalid runtime integration field {key!r}")
    return value
