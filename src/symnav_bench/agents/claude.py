from __future__ import annotations

from symnav_bench.agents.directives import NUDGE_JS, claude_directive, claude_settings_json
from symnav_bench.agents.install import INSTALL_DOMAINS, InstallStep, symnav_install_script, toolchain_root_step, write_text_step
from symnav_bench.agents.pier_compat import ClaudeCode


class SymnavClaudeCode(ClaudeCode):
    def __init__(self, *, symnav_sha: str, **kwargs):
        steps = (
            toolchain_root_step(),
            write_text_step("/app/CLAUDE.md", claude_directive()),
            write_text_step("/app/.claude/settings.json", claude_settings_json()),
            write_text_step("/app/symnav-nudge.js", NUDGE_JS),
            InstallStep("install symnav", symnav_install_script(symnav_sha, codex=False)),
        )
        super().__init__(
            install_steps=tuple(kwargs.pop("install_steps", ())) + steps,
            network_allowlist=tuple(kwargs.pop("network_allowlist", ())) + INSTALL_DOMAINS,
            **kwargs,
        )
