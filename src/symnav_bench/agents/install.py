from __future__ import annotations

import base64
import shlex
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
        command="\n".join(
            [
                "set -eu",
                "mkdir -p /app/.git/info /app/bin /app/.agents/skills /app/.claude",
                "printf '%s\\n' bin/symnav .agents/ .claude/ AGENTS.md CLAUDE.md >> /app/.git/info/exclude",
                "[ -e /app/.claude/skills ] || ln -s ../.agents/skills /app/.claude/skills",
                "[ -e /app/CLAUDE.md ] || ln -s AGENTS.md /app/CLAUDE.md",
            ]
        ),
    )


def write_text_step(path: str, text: str) -> InstallStep:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return InstallStep(
        name=f"write {path}",
        command=f"mkdir -p $(dirname {path}) && printf %s {encoded} | base64 -d > {path}",
    )


def append_text_step(path: str, text: str, *, unless_same_file_as: str | None = None) -> InstallStep:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    quoted_path = shlex.quote(path)
    quoted_compare = shlex.quote(unless_same_file_as) if unless_same_file_as else "''"
    return InstallStep(
        name=f"append {path}",
        command="\n".join(
            [
                "set -eu",
                f"path={quoted_path}",
                f"compare={quoted_compare}",
                'if [ -n "$compare" ] && [ -e "$path" ] && [ -e "$compare" ] && [ "$path" -ef "$compare" ]; then exit 0; fi',
                'mkdir -p "$(dirname "$path")" /app/.git/info',
                "payload=$(mktemp)",
                f"printf %s {encoded} | base64 -d > \"$payload\"",
                'rel="${path#/app/}"',
                'if [ -e "$path" ]; then',
                '  if ! grep -Fq "symnav-bench injected instructions" "$path"; then',
                '    printf "\\n\\n<!-- symnav-bench injected instructions start -->\\n" >> "$path"',
                '    cat "$payload" >> "$path"',
                '    printf "<!-- symnav-bench injected instructions end -->\\n" >> "$path"',
                "  fi",
                '  if git -C /app ls-files --error-unmatch "$rel" >/dev/null 2>&1; then',
                '    git -C /app update-index --skip-worktree -- "$rel"',
                "  else",
                '    printf "%s\\n" "$rel" >> /app/.git/info/exclude',
                "  fi",
                "else",
                '  cat "$payload" > "$path"',
                '  printf "%s\\n" "$rel" >> /app/.git/info/exclude',
                "fi",
                'rm -f "$payload"',
            ]
        ),
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
        "git config --global user.name symnav-bench",
        "git config --global user.email symnav-bench@example.invalid",
    ]
    if codex:
        lines.append("mkdir -p /app/.codex")
    return "\n".join(lines)
