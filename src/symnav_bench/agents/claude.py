from __future__ import annotations

from pier.models.agent.install import InstallStep as PierInstallStep
from pier.models.agent.network import NetworkAllowlist

from symnav_bench.agents.directives import NUDGE_JS, claude_directive, claude_settings_json
from symnav_bench.agents.install import (
    INSTALL_DOMAINS,
    InstallStep,
    symnav_install_script,
    toolchain_root_step,
    write_text_step,
)
from symnav_bench.agents.pier_compat import ClaudeCode


class SymnavClaudeCode(ClaudeCode):
    def __init__(self, *, symnav_sha: str, **kwargs):
        self._symnav_bench_steps = (
            toolchain_root_step(),
            write_text_step("/app/CLAUDE.md", claude_directive()),
            write_text_step("/app/.claude/settings.json", claude_settings_json()),
            write_text_step("/app/symnav-nudge.js", NUDGE_JS),
            InstallStep(
                "install symnav",
                symnav_install_script(symnav_sha, codex=False),
            ),
        )
        super().__init__(**kwargs)

    def install_spec(self):
        spec = super().install_spec()
        if spec is None:
            return spec
        spec.steps.extend(_pier_steps(self._symnav_bench_steps))
        return spec

    def network_allowlist(self) -> NetworkAllowlist:
        domains = [*super().network_allowlist().domains, *INSTALL_DOMAINS]
        return NetworkAllowlist(domains=domains)


def _pier_steps(steps: tuple[InstallStep, ...]) -> list[PierInstallStep]:
    return [PierInstallStep(user="root", run=step.command) for step in steps]
