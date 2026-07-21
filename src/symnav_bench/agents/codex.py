from __future__ import annotations

from typing import Any, Mapping

from pier.models.agent.install import InstallStep as PierInstallStep
from pier.models.agent.network import NetworkAllowlist

from symnav_bench.agent_integrations import AgentIntegrationBundle, runtime_integration_bundle
from symnav_bench.agents.install import (
    capture_pre_agent_baseline_step,
    CODEX_AUTH_DOMAINS,
    INSTALL_DOMAINS,
    InstallStep,
    codex_integration_steps,
    pinned_symnav_install_script,
    toolchain_root_step,
    workspace_capture_step,
)
from symnav_bench.agents.pier_compat import Codex


class StockCodex(Codex):
    def __init__(
        self,
        *,
        integration_bundle: AgentIntegrationBundle | Mapping[str, Any],
        workdir: str = "/app",
        **kwargs,
    ):
        logs_dir = kwargs.get("logs_dir")
        bundle = runtime_integration_bundle(integration_bundle)
        self._symnav_bench_steps = (
            toolchain_root_step(workdir),
            *codex_integration_steps(bundle, treatment=False, workdir=workdir),
            workspace_capture_step(logs_dir, ("codex",), workdir=workdir),
            capture_pre_agent_baseline_step(workdir),
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
    def __init__(
        self,
        *,
        symnav_sha: str,
        integration_bundle: AgentIntegrationBundle | Mapping[str, Any],
        workdir: str = "/app",
        **kwargs,
    ):
        logs_dir = kwargs.get("logs_dir")
        bundle = runtime_integration_bundle(integration_bundle)
        self._symnav_bench_steps = (
            toolchain_root_step(workdir),
            *codex_integration_steps(bundle, treatment=True, workdir=workdir),
            InstallStep(
                "install symnav",
                pinned_symnav_install_script(
                    symnav_sha,
                    codex=True,
                    allowed_commands=bundle.allowed_commands,
                    workdir=workdir,
                ),
            ),
            workspace_capture_step(logs_dir, ("codex",), workdir=workdir),
            capture_pre_agent_baseline_step(workdir),
        )
        Codex.__init__(self, **kwargs)

    def network_allowlist(self) -> NetworkAllowlist:
        domains = [*super().network_allowlist().domains, *INSTALL_DOMAINS]
        return NetworkAllowlist(domains=domains)


def _pier_steps(steps: tuple[InstallStep, ...]) -> list[PierInstallStep]:
    return [PierInstallStep(user="root", run=step.command) for step in steps]
