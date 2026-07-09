from __future__ import annotations

from symnav_bench.agents.codex import StockCodex, SymnavCodex
from symnav_bench.agents.directives import claude_settings_json, codex_agents_md
from symnav_bench.agents.install import CODEX_AUTH_DOMAINS, INSTALL_DOMAINS, symnav_install_script, write_text_step


def test_symnav_install_script_pins_sha_and_builds() -> None:
    script = symnav_install_script("a" * 40, codex=True)
    assert "git checkout 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'" in script
    assert "pnpm install --frozen-lockfile" in script
    assert "pnpm build" in script
    assert "cp -R /opt/symnav/.agents/skills/symnav /app/.agents/skills/symnav" in script
    assert "exec pnpm --dir /opt/symnav --filter symnav dev \"$@\"" in script
    assert "exec pnpm --dir /opt/symnav --filter symnav dev -- \"$@\"" not in script
    assert "ln -sf /app/bin/symnav /usr/local/bin/symnav" in script
    assert "symnav --help >/dev/null" in script
    assert "/app/.git/info/exclude" in script


def test_codex_agents_md_timeout_rule_for_both_arms() -> None:
    assert "yield_time_ms" in codex_agents_md(symnav=False)
    assert "symnav" not in codex_agents_md(symnav=False).lower()
    assert "yield_time_ms" in codex_agents_md(symnav=True)
    assert "symnav overview" in codex_agents_md(symnav=True)
    assert "`symnav --cwd /app" in codex_agents_md(symnav=True)


def test_claude_settings_hook() -> None:
    settings = claude_settings_json()
    assert "Grep|Glob|Read|Bash" in settings
    assert "/app/symnav-nudge.js" in settings


def test_agent_allowlists_and_install_steps(tmp_path) -> None:
    stock = StockCodex(logs_dir=tmp_path / "stock")
    symnav = SymnavCodex(logs_dir=tmp_path / "symnav", symnav_sha="b" * 40)
    assert set(CODEX_AUTH_DOMAINS).issubset(set(stock.network_allowlist().domains))
    assert set(INSTALL_DOMAINS).issubset(set(symnav.network_allowlist().domains))
    assert any(
        "git clone https://github.com/mohasarc/symnav.git" in step.run
        for step in symnav.install_spec().steps
    )


def test_write_text_step_base64_encodes_multiword_text() -> None:
    step = write_text_step("/app/AGENTS.md", "hello world")
    assert "hello world" not in step.command
    assert "base64 -d" in step.command
