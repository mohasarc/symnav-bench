from __future__ import annotations

import base64
import hashlib
import shlex
from dataclasses import dataclass

from symnav_bench.agent_integrations import RuntimeAgentIntegrationBundle, RuntimeIntegrationFile


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
    content_id = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    marker = f"symnav-bench injected instructions {content_id}"
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
                f'  if ! grep -Fq "{marker}" "$path"; then',
                f'    printf "\\n\\n<!-- {marker} start -->\\n" >> "$path"',
                '    cat "$payload" >> "$path"',
                f'    printf "<!-- {marker} end -->\\n" >> "$path"',
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


def append_integration_file_step(
    integration_file: RuntimeIntegrationFile,
    *,
    destination: str | None = None,
    unless_same_file_as: str | None = None,
) -> InstallStep:
    return append_text_step(
        destination or integration_file.destination.as_posix(),
        integration_file.content.decode("utf-8"),
        unless_same_file_as=unless_same_file_as,
    )


def write_integration_file_step(
    integration_file: RuntimeIntegrationFile,
    *,
    destination: str | None = None,
) -> InstallStep:
    return write_text_step(
        destination or integration_file.destination.as_posix(),
        integration_file.content.decode("utf-8"),
    )


AGENT_RULES_PATH = "/app/AGENTS.md"
CLAUDE_RULES_PATH = "/app/CLAUDE.md"


def codex_integration_steps(bundle: RuntimeAgentIntegrationBundle, *, treatment: bool) -> tuple[InstallStep, ...]:
    steps = [append_integration_file_step(bundle.shared_rules)]
    if treatment:
        steps.append(append_integration_file_step(bundle.rules))
        steps.extend(_skill_injection_steps(bundle, AGENT_RULES_PATH))
    return tuple(steps)


def claude_integration_steps(bundle: RuntimeAgentIntegrationBundle, *, treatment: bool) -> tuple[InstallStep, ...]:
    steps = [
        append_integration_file_step(bundle.shared_rules),
        append_integration_file_step(
            bundle.shared_rules,
            destination=CLAUDE_RULES_PATH,
            unless_same_file_as=AGENT_RULES_PATH,
        ),
    ]
    if treatment:
        steps.extend(
            [
                append_integration_file_step(bundle.rules),
                append_integration_file_step(
                    bundle.rules,
                    destination=CLAUDE_RULES_PATH,
                    unless_same_file_as=AGENT_RULES_PATH,
                ),
                *_skill_injection_steps(bundle, AGENT_RULES_PATH),
                *_skill_injection_steps(
                    bundle,
                    CLAUDE_RULES_PATH,
                    unless_same_file_as=AGENT_RULES_PATH,
                ),
                write_integration_file_step(bundle.claude_settings),
                write_integration_file_step(bundle.claude_hook),
            ]
        )
    return tuple(steps)


def _skill_injection_steps(
    bundle: RuntimeAgentIntegrationBundle,
    destination: str,
    *,
    unless_same_file_as: str | None = None,
) -> tuple[InstallStep, ...]:
    return tuple(
        append_integration_file_step(
            file,
            destination=destination,
            unless_same_file_as=unless_same_file_as,
        )
        for file in bundle.skill_files
    )


def symnav_command_wrapper(allowed_commands: tuple[str, ...], upstream: str) -> str:
    allowed = " ".join(allowed_commands)
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            f"allowed_commands={shlex.quote(allowed)}",
            f"upstream={shlex.quote(upstream)}",
            'for arg in "$@"; do',
            '  case "$arg" in',
            "    overview|resolve|def|refs|context|graph|stats)",
            "      allowed=0",
            "      for command in $allowed_commands; do",
            '        if [ "$arg" = "$command" ]; then allowed=1; fi',
            "      done",
            '      if [ "$allowed" -ne 1 ]; then',
            '        echo "Unsupported symnav invocation for this benchmark arm." >&2',
            "        exit 2",
            "      fi",
            "      break",
            "      ;;",
            "  esac",
            "done",
            'exec "$upstream" "$@"',
            "",
        ]
    )


def pinned_symnav_install_script(
    symnav_sha: str,
    *,
    codex: bool,
    allowed_commands: tuple[str, ...],
) -> str:
    escaped_sha = symnav_sha.replace("'", "")
    wrapper = symnav_command_wrapper(allowed_commands, "/app/bin/symnav-real")
    lines = [
        "set -eu",
        "mkdir -p /opt /app/bin /app/.git/info",
        "git clone https://github.com/mohasarc/symnav.git /opt/symnav",
        "cd /opt/symnav",
        f"git checkout '{escaped_sha}'",
        "pnpm install --frozen-lockfile",
        "pnpm build",
        "cat > /app/bin/symnav-real <<'EOF'",
        "#!/bin/sh",
        "has_cwd=0",
        'for arg in "$@"; do',
        '  case "$arg" in',
        "    --cwd|--cwd=*) has_cwd=1 ;;",
        "  esac",
        "done",
        'if [ "$has_cwd" -eq 1 ]; then',
        '  exec pnpm --dir /opt/symnav --filter symnav dev "$@"',
        "fi",
        'exec pnpm --dir /opt/symnav --filter symnav dev --cwd /app "$@"',
        "EOF",
        "chmod +x /app/bin/symnav-real",
        "cat > /app/bin/symnav <<'EOF'",
        *wrapper.splitlines(),
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


def workspace_capture_step(logs_dir: object, binaries: tuple[str, ...]) -> InstallStep:
    target = shlex.quote(str(logs_dir or "/logs/agent"))
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
        'real_copy="$real.symnav-bench-real"',
        'if [ ! -e "$real_copy" ]; then mv "$real" "$real_copy"; fi',
        'cat > "$real" <<EOF',
        "#!/bin/sh",
        "set +e",
        'SYMNAV_BENCH_WORKSPACE_CAPTURE_DIR="$capture_dir" "$real_copy" "\\$@"',
        "status=\\$?",
        "SYMNAV_BENCH_WORKSPACE_CAPTURE_DIR=\"$capture_dir\" /usr/local/bin/symnav-bench-capture-workspace >/dev/null 2>&1 || true",
        "exit \\$status",
        "EOF",
        'chmod +x "$real"',
        'if [ "$real" != "$wrapper" ]; then',
        '  cat > "$wrapper" <<EOF',
        "#!/bin/sh",
        "set +e",
        'SYMNAV_BENCH_WORKSPACE_CAPTURE_DIR="$capture_dir" "$real_copy" "\\$@"',
        "status=\\$?",
        "SYMNAV_BENCH_WORKSPACE_CAPTURE_DIR=\"$capture_dir\" /usr/local/bin/symnav-bench-capture-workspace >/dev/null 2>&1 || true",
        "exit \\$status",
        "EOF",
        '  chmod +x "$wrapper"',
        "fi",
        "fi",
    ]
