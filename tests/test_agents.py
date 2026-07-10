from __future__ import annotations

from symnav_bench.agents.codex import StockCodex, SymnavCodex
from symnav_bench.agents.directives import claude_settings_json, codex_agents_md
from symnav_bench.agents.claude import SymnavClaudeCode
from symnav_bench.agents.install import (
    CODEX_AUTH_DOMAINS,
    INSTALL_DOMAINS,
    append_text_step,
    symnav_install_script,
    toolchain_root_step,
    workspace_capture_step,
    write_text_step,
)


def test_symnav_install_script_pins_sha_and_builds() -> None:
    script = symnav_install_script("a" * 40, codex=True)
    assert "git checkout 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'" in script
    assert "pnpm install --frozen-lockfile" in script
    assert "pnpm build" in script
    assert "cp -R /opt/symnav/.agents/skills/symnav /app/.agents/skills/symnav" in script
    assert "exec pnpm --dir /opt/symnav --filter symnav dev --cwd /app \"$@\"" in script
    assert "has_cwd=0" in script
    assert "--cwd|--cwd=*) has_cwd=1 ;;" in script
    assert "exec pnpm --dir /opt/symnav --filter symnav dev -- \"$@\"" not in script
    assert "ln -sf /app/bin/symnav /usr/local/bin/symnav" in script
    assert "symnav --help >/dev/null" in script
    assert "/app/bin/symnav /opt/symnav /app/.agents" not in script


def test_toolchain_root_creates_claude_compat_links() -> None:
    step = toolchain_root_step()
    assert "[ -e /app/.claude/skills ] || ln -s ../.agents/skills /app/.claude/skills" in step.command
    assert "[ -e /app/CLAUDE.md ] || ln -s AGENTS.md /app/CLAUDE.md" in step.command
    assert "bin/symnav .agents/ .claude/ AGENTS.md CLAUDE.md" in step.command


def test_codex_agents_md_timeout_rule_for_both_arms() -> None:
    assert "yield_time_ms" in codex_agents_md(symnav=False)
    assert "several minutes" in codex_agents_md(symnav=False)
    assert "early empty poll is not the final result" in codex_agents_md(symnav=False)
    assert "symnav" not in codex_agents_md(symnav=False).lower()
    assert "yield_time_ms" in codex_agents_md(symnav=True)
    assert "several minutes" in codex_agents_md(symnav=True)
    assert "No exceptions; read the symnav skill first" in codex_agents_md(symnav=True)
    assert "installed globally" in codex_agents_md(symnav=True)
    assert "`symnav ...`" in codex_agents_md(symnav=True)
    assert "`symnav --cwd /app" not in codex_agents_md(symnav=True)
    assert "provides deterministic TypeScript orientation" in codex_agents_md(symnav=True)
    assert "Available symnav commands include overview, resolve, def, refs, context, and graph" in codex_agents_md(
        symnav=True
    )
    assert "Normal reads, search, tests, and edits remain available whenever they help" in codex_agents_md(
        symnav=True
    )
    assert "never on a directory" in codex_agents_md(symnav=True)
    assert "continue exploring" not in codex_agents_md(symnav=True)
    assert "run symnav again" not in codex_agents_md(symnav=True)
    assert "increasing depth or changing direction" not in codex_agents_md(symnav=True)
    assert "after orientation" not in codex_agents_md(symnav=True)


def test_claude_settings_hook() -> None:
    settings = claude_settings_json()
    assert "Grep|Glob|Read|Bash" in settings
    assert "/tmp/symnav-bench/symnav-nudge.js" in settings


def test_agent_allowlists_and_install_steps(tmp_path) -> None:
    stock = StockCodex(logs_dir=tmp_path / "stock")
    symnav = SymnavCodex(logs_dir=tmp_path / "symnav", symnav_sha="b" * 40)
    claude = SymnavClaudeCode(logs_dir=tmp_path / "claude", symnav_sha="b" * 40)
    assert set(CODEX_AUTH_DOMAINS).issubset(set(stock.network_allowlist().domains))
    assert set(INSTALL_DOMAINS).issubset(set(symnav.network_allowlist().domains))
    assert any("mkdir -p /app/.git/info" in step.run for step in claude.install_spec().steps)
    assert any("/app/AGENTS.md" in step.run for step in claude.install_spec().steps)
    assert any("/app/CLAUDE.md" in step.run and "-ef" in step.run for step in claude.install_spec().steps)
    assert any("/tmp/symnav-bench/symnav-nudge.js" in step.run for step in claude.install_spec().steps)
    assert not any("/app/symnav-nudge.js" in step.run for step in claude.install_spec().steps)
    assert any("symnav-bench-capture-workspace" in step.run for step in stock.install_spec().steps)
    assert any(str(tmp_path / "symnav") in step.run and "workspace/app" in step.run for step in symnav.install_spec().steps)
    assert any(
        "git clone https://github.com/mohasarc/symnav.git" in step.run
        for step in symnav.install_spec().steps
    )


def test_write_text_step_base64_encodes_multiword_text() -> None:
    step = write_text_step("/app/AGENTS.md", "hello world")
    assert "hello world" not in step.command
    assert "base64 -d" in step.command


def test_append_text_step_preserves_tracked_instruction_files() -> None:
    step = append_text_step("/app/AGENTS.md", "hello world")
    assert "hello world" not in step.command
    assert "symnav-bench injected instructions" in step.command
    assert "update-index --skip-worktree" in step.command
    assert ">> \"$path\"" in step.command


def test_workspace_capture_step_wraps_agent_binary(tmp_path) -> None:
    step = workspace_capture_step(tmp_path / "agent", ("codex",))
    assert "symnav-bench-capture-workspace" in step.command
    assert str(tmp_path / "agent") in step.command
    assert "workspace/app" in step.command
    assert "git -C /app diff >" in step.command
    assert 'real_copy="$real.symnav-bench-real"' in step.command
    assert 'mv "$real" "$real_copy"' in step.command
    assert 'cat > "$real" <<EOF' in step.command
    assert 'SYMNAV_BENCH_WORKSPACE_CAPTURE_DIR="$capture_dir" "$real_copy"' in step.command


def test_workspace_capture_defaults_to_persisted_agent_logs() -> None:
    step = workspace_capture_step(None, ("claude",))
    assert "logs_dir=/logs/agent" in step.command
    assert "workspace/app" in step.command
