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


def workspace_capture_step(logs_dir: object, binaries: tuple[str, ...]) -> InstallStep:
    target = shlex.quote(str(logs_dir or "/tmp/symnav-bench-agent"))
    wrapper_lines = [
        "set -eu",
        f"logs_dir={target}",
        'capture_dir="$logs_dir/workspace/app"',
        "mkdir -p /usr/local/bin",
        "cat > /usr/local/bin/symnav-bench-capture-workspace <<'EOF'",
        "#!/bin/sh",
        "set +e",
        'target="${SYMNAV_BENCH_WORKSPACE_CAPTURE_DIR:-}"',
        '[ -n "$target" ] || exit 0',
        'mkdir -p "$target"',
        'if [ ! -e /app/.git ]; then',
        '  printf "%s\\n" "missing /app/.git" > "$target/error.txt"',
        "  exit 0",
        "fi",
        'git -C /app status --short > "$target/status-short.txt" 2>&1',
        'git -C /app status --short --untracked-files=all > "$target/status-short-untracked.txt" 2>&1',
        'git -C /app diff --stat > "$target/diff-stat.txt" 2>&1',
        'git -C /app diff > "$target/diff.patch" 2>&1',
        'git -C /app diff --cached > "$target/diff-cached.patch" 2>&1',
        'git -C /app ls-files --others --exclude-standard > "$target/untracked-files.txt" 2>&1',
        'rm -rf "$target/untracked"',
        'mkdir -p "$target/untracked"',
        'git -C /app ls-files --others --exclude-standard | while IFS= read -r file; do',
        '  case "$file" in',
        '    .agents/*|.claude/*|AGENTS.md|CLAUDE.md|bin/symnav) continue ;;',
        "  esac",
        '  mkdir -p "$target/untracked/$(dirname "$file")"',
        '  cp "/app/$file" "$target/untracked/$file" 2>/dev/null || true',
        "done",
        "EOF",
        "chmod +x /usr/local/bin/symnav-bench-capture-workspace",
    ]
    for binary in binaries:
        wrapper_lines.extend(_wrap_binary_lines(binary))
    return InstallStep(name="capture workspace artifacts", command="\n".join(wrapper_lines))


def _wrap_binary_lines(binary: str) -> list[str]:
    quoted_binary = shlex.quote(binary)
    return [
        f"binary={quoted_binary}",
        'real="$(command -v "$binary" || true)"',
        'if [ -n "$real" ] && ! printf "%s" "$real" | grep -q "/symnav-bench-real$"; then',
        'wrapper="/usr/local/bin/$binary"',
        'real_copy="$wrapper.symnav-bench-real"',
        'if [ "$real" = "$wrapper" ]; then',
        '  if [ ! -e "$real_copy" ]; then mv "$wrapper" "$real_copy"; fi',
        '  real="$real_copy"',
        "fi",
        'cat > "$wrapper" <<EOF',
        "#!/bin/sh",
        "set +e",
        'SYMNAV_BENCH_WORKSPACE_CAPTURE_DIR="$capture_dir" "$real" "\\$@"',
        "status=\\$?",
        "SYMNAV_BENCH_WORKSPACE_CAPTURE_DIR=\"$capture_dir\" /usr/local/bin/symnav-bench-capture-workspace >/dev/null 2>&1 || true",
        "exit \\$status",
        "EOF",
        'chmod +x "$wrapper"',
        "fi",
    ]


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
        "has_cwd=0",
        "for arg in \"$@\"; do",
        "  case \"$arg\" in",
        "    --cwd|--cwd=*) has_cwd=1 ;;",
        "  esac",
        "done",
        "if [ \"$has_cwd\" -eq 1 ]; then",
        "  exec pnpm --dir /opt/symnav --filter symnav dev \"$@\"",
        "fi",
        "exec pnpm --dir /opt/symnav --filter symnav dev --cwd /app \"$@\"",
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
