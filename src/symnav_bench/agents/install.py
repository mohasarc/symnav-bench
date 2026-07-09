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
        command=" && ".join(
            [
                "mkdir -p /app/.git/info /app/bin /app/.agents/skills /app/.claude",
                "ln -sfn ../.agents/skills /app/.claude/skills",
                "ln -sfn AGENTS.md /app/CLAUDE.md",
            ]
        ),
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
        "rm -rf /app/.agents/skills/symnav",
        "cp -R /opt/symnav/.agents/skills/symnav /app/.agents/skills/symnav",
        "cat > /app/bin/symnav <<'EOF'",
        "#!/bin/sh",
        "exec pnpm --dir /opt/symnav --filter symnav dev \"$@\"",
        "EOF",
        "chmod +x /app/bin/symnav",
        "ln -sf /app/bin/symnav /usr/local/bin/symnav",
        "symnav --help >/dev/null",
        "printf '%s\\n' /app/bin/symnav /opt/symnav /app/.agents >> /app/.git/info/exclude",
        "git config --global user.name symnav-bench",
        "git config --global user.email symnav-bench@example.invalid",
    ]
    if codex:
        lines.append("mkdir -p /app/.codex")
    return "\n".join(lines)
