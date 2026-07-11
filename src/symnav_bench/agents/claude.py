from __future__ import annotations

from pier.models.agent.install import InstallStep as PierInstallStep
from pier.models.agent.network import NetworkAllowlist

from symnav_bench.agent_integrations import AgentIntegrationBundle
from symnav_bench.agents.directives import claude_directive, claude_settings_json, nudge_js
from symnav_bench.agents.install import (
    INSTALL_DOMAINS,
    InstallStep,
    append_text_step,
    claude_integration_steps,
    pinned_symnav_install_script,
    symnav_install_script,
    toolchain_root_step,
    workspace_capture_step,
    write_text_step,
)
from symnav_bench.agents.pier_compat import ClaudeCode
from symnav_bench.run_spec import SymnavSkillVariant


class StockClaudeCode(ClaudeCode):
    def __init__(self, *, integration_bundle: AgentIntegrationBundle | None = None, **kwargs):
        logs_dir = kwargs.get("logs_dir")
        integration_steps = (
            claude_integration_steps(integration_bundle, treatment=False)
            if integration_bundle is not None
            else ()
        )
        self._symnav_bench_steps = (
            toolchain_root_step(),
            *integration_steps,
            workspace_capture_step(logs_dir, ("claude", "claude-code")),
        )
        super().__init__(**kwargs)

    def install_spec(self):
        spec = super().install_spec()
        if spec is None:
            return spec
        spec.steps.extend(_pier_steps(self._symnav_bench_steps))
        return spec


class SymnavClaudeCode(StockClaudeCode):
    def __init__(
        self,
        *,
        symnav_sha: str,
        integration_bundle: AgentIntegrationBundle | None = None,
        symnav_skill_variant: SymnavSkillVariant = "all",
        **kwargs,
    ):
        logs_dir = kwargs.get("logs_dir")
        if integration_bundle is None:
            integration_steps = (
                append_text_step("/app/AGENTS.md", claude_directive(symnav_skill_variant)),
                append_text_step(
                    "/app/CLAUDE.md",
                    claude_directive(symnav_skill_variant),
                    unless_same_file_as="/app/AGENTS.md",
                ),
                write_text_step("/app/.claude/settings.json", claude_settings_json()),
                write_text_step("/tmp/symnav-bench/symnav-nudge.js", nudge_js(symnav_skill_variant)),
            )
            install_script = symnav_install_script(
                symnav_sha,
                codex=False,
                skill_variant=symnav_skill_variant,
            )
        else:
            integration_steps = claude_integration_steps(integration_bundle, treatment=True)
            install_script = pinned_symnav_install_script(
                symnav_sha,
                codex=False,
                allowed_commands=integration_bundle.allowed_commands,
            )
        self._symnav_bench_steps = (
            toolchain_root_step(),
            *integration_steps,
            InstallStep("install symnav", install_script),
            workspace_capture_step(logs_dir, ("claude", "claude-code")),
        )
        ClaudeCode.__init__(self, **kwargs)

    def network_allowlist(self) -> NetworkAllowlist:
        domains = [*super().network_allowlist().domains, *INSTALL_DOMAINS]
        return NetworkAllowlist(domains=domains)


def _pier_steps(steps: tuple[InstallStep, ...]) -> list[PierInstallStep]:
    return [PierInstallStep(user="root", run=step.command) for step in steps]
