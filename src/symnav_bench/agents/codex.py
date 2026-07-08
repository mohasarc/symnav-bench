from __future__ import annotations

from symnav_bench.agents.directives import codex_agents_md
from symnav_bench.agents.install import CODEX_AUTH_DOMAINS, INSTALL_DOMAINS, InstallStep, symnav_install_script, toolchain_root_step, write_text_step
from symnav_bench.agents.pier_compat import Codex


class StockCodex(Codex):
    def __init__(self, **kwargs):
        steps = (
            toolchain_root_step(),
            write_text_step("/app/AGENTS.md", codex_agents_md(symnav=False)),
        )
        super().__init__(
            install_steps=tuple(kwargs.pop("install_steps", ())) + steps,
            network_allowlist=tuple(kwargs.pop("network_allowlist", ())) + CODEX_AUTH_DOMAINS,
            **kwargs,
        )


class SymnavCodex(StockCodex):
    def __init__(self, *, symnav_sha: str, **kwargs):
        steps = (
            write_text_step("/app/AGENTS.md", codex_agents_md(symnav=True)),
            InstallStep("install symnav", symnav_install_script(symnav_sha, codex=True)),
        )
        super().__init__(
            install_steps=tuple(kwargs.pop("install_steps", ())) + steps,
            network_allowlist=tuple(kwargs.pop("network_allowlist", ())) + INSTALL_DOMAINS,
            **kwargs,
        )
