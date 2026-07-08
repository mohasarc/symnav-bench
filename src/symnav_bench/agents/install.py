from __future__ import annotations

import base64
from dataclasses import dataclass


INSTALL_DOMAINS: tuple[str, ...] = (
    "github.com",
    "raw.githubusercontent.com",
    "registry.npmjs.org",
)
CODEX_AUTH_DOMAINS: tuple[str, ...] = (
    "chatgpt.com",
    "auth.openai.com",
    "api.openai.com",
)


@dataclass(frozen=True)
class InstallStep:
    name: str
    command: str


def toolchain_root_step() -> InstallStep:
    return InstallStep(
        name="install toolchain roots",
        command="mkdir -p /app/.git/info /app/bin /app/.agents/skills",
    )


def write_text_step(path: str, text: str) -> InstallStep:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return InstallStep(
        name=f"write {path}",
        command=f"mkdir -p $(dirname {path}) && printf %s {encoded} | base64 -d > {path}",
    )


def symnav_install_script(symnav_sha: str, *, codex: bool) -> str:
    escaped_sha = symnav_sha.replace("'", "")
    lines = [
        "set -eu",
        "mkdir -p /opt /app/bin /app/.git/info",
        "git clone https://github.com/mohasarc/symnav.git /opt/symnav",
        "cd /opt/symnav",
        f"git checkout '{escaped_sha}'",
        "pnpm install --frozen-lockfile",
        "pnpm build",
        "cat > /app/bin/symnav <<'EOF'",
        "#!/bin/sh",
        "exec pnpm --dir /opt/symnav --filter symnav dev -- \"$@\"",
        "EOF",
        "chmod +x /app/bin/symnav",
        "printf '%s\\n' /app/bin/symnav /opt/symnav /app/.agents >> /app/.git/info/exclude",
    ]
    if codex:
        lines.append("mkdir -p /app/.codex")
    return "\n".join(lines)
