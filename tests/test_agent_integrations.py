from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from symnav_bench.agent_integrations import SymnavIntegrationCatalog
from symnav_bench.agents.claude import SymnavClaudeCode
from symnav_bench.agents.codex import StockCodex, SymnavCodex
from symnav_bench.agents.install import symnav_command_wrapper


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


def test_stock_codex_installs_shared_rules_without_treatment_assets(tmp_path: Path) -> None:
    bundle = SymnavIntegrationCatalog.load(_write_checkout(tmp_path)).bundle("full")

    commands = [step.run for step in StockCodex(logs_dir=tmp_path / "logs", integration_bundle=bundle).install_spec().steps]
    combined = "\n".join(commands)

    assert _encoded(bundle.shared_rules.source) in combined
    assert _encoded(bundle.rules.source) not in combined
    assert _encoded(bundle.skill_files[0].source) not in combined
    assert _encoded(bundle.claude_hook.source) not in combined
    assert "install symnav" not in combined


def test_full_codex_installs_shared_rules_bundle_rules_and_skill_byte_for_byte(tmp_path: Path) -> None:
    bundle = SymnavIntegrationCatalog.load(_write_checkout(tmp_path)).bundle("full")

    commands = [
        step.run
        for step in SymnavCodex(
            logs_dir=tmp_path / "logs",
            symnav_sha="a" * 40,
            integration_bundle=bundle,
        ).install_spec().steps
    ]
    combined = "\n".join(commands)

    assert _encoded(bundle.shared_rules.source) in combined
    assert _encoded(bundle.rules.source) in combined
    assert _encoded(bundle.skill_files[0].source) in combined
    assert _encoded(bundle.claude_settings.source) not in combined
    assert _encoded(bundle.claude_hook.source) not in combined


def test_full_codex_injects_skill_body_into_agents_md_not_a_skill_file(tmp_path: Path) -> None:
    bundle = SymnavIntegrationCatalog.load(_write_checkout(tmp_path)).bundle("full")

    steps = SymnavCodex(
        logs_dir=tmp_path / "logs",
        symnav_sha="a" * 40,
        integration_bundle=bundle,
    ).install_spec().steps

    skill_b64 = _encoded(bundle.skill_files[0].source)
    skill_destination = bundle.skill_files[0].destination.as_posix()
    injecting = [step.run for step in steps if skill_b64 in step.run]

    assert injecting, "skill content is not injected anywhere"
    assert all("/app/AGENTS.md" in command for command in injecting)
    assert all(skill_destination not in command for command in injecting)


def test_full_claude_installs_every_bundle_asset_byte_for_byte(tmp_path: Path) -> None:
    bundle = SymnavIntegrationCatalog.load(_write_checkout(tmp_path)).bundle("full")

    commands = [
        step.run
        for step in SymnavClaudeCode(
            logs_dir=tmp_path / "logs",
            symnav_sha="a" * 40,
            integration_bundle=bundle,
        ).install_spec().steps
    ]
    combined = "\n".join(commands)

    for integration_file in (
        bundle.shared_rules,
        bundle.rules,
        *bundle.skill_files,
        bundle.claude_settings,
        bundle.claude_hook,
    ):
        assert _encoded(integration_file.source) in combined


def test_full_claude_injects_skill_body_into_agents_and_claude_md(tmp_path: Path) -> None:
    bundle = SymnavIntegrationCatalog.load(_write_checkout(tmp_path)).bundle("full")

    steps = SymnavClaudeCode(
        logs_dir=tmp_path / "logs",
        symnav_sha="a" * 40,
        integration_bundle=bundle,
    ).install_spec().steps

    skill_b64 = _encoded(bundle.skill_files[0].source)
    skill_destination = bundle.skill_files[0].destination.as_posix()
    injecting = [step.run for step in steps if skill_b64 in step.run]

    assert len(injecting) == 2
    assert any("/app/AGENTS.md" in command for command in injecting)
    assert any("/app/CLAUDE.md" in command for command in injecting)
    assert all(skill_destination not in command for command in injecting)


def test_variant_wrapper_rejects_sibling_command(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    upstream.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\"\n", encoding="utf-8")
    upstream.chmod(0o755)
    wrapper = tmp_path / "symnav"
    wrapper.write_text(symnav_command_wrapper(("overview",), str(upstream)), encoding="utf-8")
    wrapper.chmod(0o755)

    allowed = subprocess.run([wrapper, "overview", "file.ts"], text=True, capture_output=True, check=False)
    rejected = subprocess.run([wrapper, "refs", "symbol"], text=True, capture_output=True, check=False)

    assert allowed.returncode == 0
    assert allowed.stdout == "overview file.ts\n"
    assert rejected.returncode == 2
    assert rejected.stderr == "Unsupported symnav invocation for this benchmark arm.\n"


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


def _encoded(path: Path) -> str:
    import base64

    return base64.b64encode(path.read_bytes()).decode("ascii")
