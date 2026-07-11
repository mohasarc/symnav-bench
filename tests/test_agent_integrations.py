from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from symnav_bench.agent_integrations import SymnavIntegrationCatalog


COMMANDS = ["overview", "resolve", "def", "refs", "context", "graph"]


def test_loads_bundle_and_hashes_catalog_and_every_asset(tmp_path: Path) -> None:
    checkout = _write_checkout(tmp_path)

    catalog = SymnavIntegrationCatalog.load(checkout)
    bundle = catalog.bundle("full")

    expected_paths = [
        checkout / ".agents/integrations/symnav/catalog.json",
        checkout / ".agents/integrations/symnav/shared-rules.md",
        checkout / ".agents/skills/symnav/SKILL.md",
        checkout / ".agents/integrations/symnav/full/rules.md",
        checkout / ".agents/integrations/symnav/full/claude-settings.json",
        checkout / ".agents/integrations/symnav/full/symnav-nudge.js",
    ]
    digest = hashlib.sha256()
    for path in sorted(expected_paths, key=lambda item: item.relative_to(checkout).as_posix()):
        relative = path.relative_to(checkout).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)

    assert bundle.id == "full"
    assert bundle.allowed_commands == tuple(COMMANDS)
    assert bundle.shared_rules.destination.as_posix() == "/app/AGENTS.md"
    assert bundle.rules.destination.as_posix() == "/app/AGENTS.md"
    assert bundle.skill_files[0].destination.as_posix() == "/app/.agents/skills/symnav/SKILL.md"
    assert bundle.claude_settings.destination.as_posix() == "/app/.claude/settings.json"
    assert bundle.claude_hook.destination.as_posix() == "/tmp/symnav-bench/symnav-nudge.js"
    assert bundle.content_hash == digest.hexdigest()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda catalog: catalog.update(schemaVersion=2), "schema"),
        (lambda catalog: catalog.update(sharedRulesFile="missing.md"), "missing"),
        (lambda catalog: catalog["bundles"][0].update(allowedCommands=["refs"]), "commands"),
    ],
)
def test_rejects_invalid_catalog(tmp_path: Path, mutation, message: str) -> None:
    checkout = _write_checkout(tmp_path)
    catalog_path = checkout / ".agents/integrations/symnav/catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    mutation(catalog)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        SymnavIntegrationCatalog.load(checkout)


def test_rejects_unknown_bundle(tmp_path: Path) -> None:
    catalog = SymnavIntegrationCatalog.load(_write_checkout(tmp_path))

    with pytest.raises(ValueError, match="unknown integration bundle"):
        catalog.bundle("missing")


def test_rejects_catalog_path_outside_checkout(tmp_path: Path) -> None:
    checkout = _write_checkout(tmp_path)
    catalog_path = checkout / ".agents/integrations/symnav/catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["sharedRulesFile"] = "../shared-rules.md"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes"):
        SymnavIntegrationCatalog.load(checkout)


def _write_checkout(root: Path) -> Path:
    checkout = root / "symnav"
    catalog = {
        "schemaVersion": 1,
        "sharedRulesFile": ".agents/integrations/symnav/shared-rules.md",
        "bundles": [
            {
                "id": "full",
                "skillDirectory": ".agents/skills/symnav",
                "rulesFile": ".agents/integrations/symnav/full/rules.md",
                "allowedCommands": COMMANDS,
                "claudeSettingsFile": ".agents/integrations/symnav/full/claude-settings.json",
                "claudeHookFile": ".agents/integrations/symnav/full/symnav-nudge.js",
            },
            {
                "id": "overview",
                "skillDirectory": ".agents/integrations/symnav/variants/overview/skill",
                "rulesFile": ".agents/integrations/symnav/variants/overview/rules.md",
                "allowedCommands": ["overview"],
                "claudeSettingsFile": ".agents/integrations/symnav/variants/overview/claude-settings.json",
                "claudeHookFile": ".agents/integrations/symnav/variants/overview/symnav-nudge.js",
            },
        ],
    }
    _write(checkout / ".agents/integrations/symnav/catalog.json", json.dumps(catalog, sort_keys=True))
    _write(checkout / ".agents/integrations/symnav/shared-rules.md", "shared\n")
    _write(checkout / ".agents/skills/symnav/SKILL.md", "full skill\n")
    _write(checkout / ".agents/integrations/symnav/full/rules.md", "full rules\n")
    _write(checkout / ".agents/integrations/symnav/full/claude-settings.json", "{}\n")
    _write(checkout / ".agents/integrations/symnav/full/symnav-nudge.js", "full hook\n")
    _write(checkout / ".agents/integrations/symnav/variants/overview/skill/SKILL.md", "overview skill\n")
    _write(checkout / ".agents/integrations/symnav/variants/overview/rules.md", "overview rules\n")
    _write(checkout / ".agents/integrations/symnav/variants/overview/claude-settings.json", "{}\n")
    _write(checkout / ".agents/integrations/symnav/variants/overview/symnav-nudge.js", "overview hook\n")
    return checkout


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
