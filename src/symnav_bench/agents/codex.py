from __future__ import annotations

from pier.models.agent.install import InstallStep as PierInstallStep
from pier.models.agent.network import NetworkAllowlist

from symnav_bench.agents.directives import codex_agents_md
from symnav_bench.agents.install import (
    CODEX_AUTH_DOMAINS,
    INSTALL_DOMAINS,
    InstallStep,
    append_text_step,
    symnav_install_script,
    toolchain_root_step,
    workspace_capture_step,
)
from symnav_bench.agents.pier_compat import Codex
from symnav_bench.run_spec import SymnavSkillVariant


class StockCodex(Codex):
    def __init__(self, **kwargs):
        logs_dir = kwargs.get("logs_dir")
        self._symnav_bench_steps = (
            toolchain_root_step(),
            append_text_step("/app/AGENTS.md", codex_agents_md(symnav=False)),
            workspace_capture_step(logs_dir, ("codex",)),
        )
        super().__init__(**kwargs)

    def install_spec(self):
        spec = super().install_spec()
        if spec is None:
            return spec
        spec.steps.extend(_pier_steps(self._symnav_bench_steps))
        return spec

    def network_allowlist(self) -> NetworkAllowlist:
        domains = [*super().network_allowlist().domains, *CODEX_AUTH_DOMAINS]
        return NetworkAllowlist(domains=domains)


class SymnavCodex(StockCodex):
    def __init__(self, *, symnav_sha: str, symnav_skill_variant: SymnavSkillVariant = "all", **kwargs):
        logs_dir = kwargs.get("logs_dir")
        self._symnav_bench_steps = (
            toolchain_root_step(),
            append_text_step("/app/AGENTS.md", codex_agents_md(symnav=True, symnav_skill_variant=symnav_skill_variant)),
            InstallStep(
                "install symnav",
                symnav_install_script(symnav_sha, codex=True, skill_variant=symnav_skill_variant),
            ),
            workspace_capture_step(logs_dir, ("codex",)),
        )
        Codex.__init__(self, **kwargs)

    def network_allowlist(self) -> NetworkAllowlist:
        domains = [*super().network_allowlist().domains, *INSTALL_DOMAINS]
        return NetworkAllowlist(domains=domains)


def _pier_steps(steps: tuple[InstallStep, ...]) -> list[PierInstallStep]:
    return [PierInstallStep(user="root", run=step.command) for step in steps]
