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
    "nodejs.org",
)
CODEX_AUTH_DOMAINS: tuple[str, ...] = (
    "chatgpt.com",
    "auth.openai.com",
    "api.openai.com",
)
DEFAULT_WORKDIR = "/app"


@dataclass(frozen=True)
class InstallStep:
    name: str
    command: str


def toolchain_root_step(workdir: str = DEFAULT_WORKDIR) -> InstallStep:
    return InstallStep(
        name="install toolchain roots",
        command="\n".join(
            [
                "set -eu",
                f"mkdir -p {workdir}/.git/info {workdir}/bin {workdir}/.agents/skills {workdir}/.claude",
                f"printf '%s\\n' bin/symnav .agents/ .claude/ AGENTS.md CLAUDE.md >> {workdir}/.git/info/exclude",
                f"[ -e {workdir}/.claude/skills ] || ln -s ../.agents/skills {workdir}/.claude/skills",
                f"[ -e {workdir}/CLAUDE.md ] || ln -s AGENTS.md {workdir}/CLAUDE.md",
            ]
        ),
    )


def capture_pre_agent_baseline_step(workdir: str = DEFAULT_WORKDIR) -> InstallStep:
    return InstallStep(
        name="capture pre-agent baseline",
        command="\n".join(
            [
                "set -eu",
                f"cd {workdir}",
                "baseline_index=$(mktemp)",
                'cp "$(git rev-parse --git-path index)" "$baseline_index" 2>/dev/null || true',
                'GIT_INDEX_FILE="$baseline_index" git add -A',
                'GIT_INDEX_FILE="$baseline_index" git write-tree'
                ' > "$(git rev-parse --git-dir)/symnav-bench-baseline-tree"',
                'rm -f "$baseline_index"',
            ]
        ),
    )


def write_text_step(path: str, text: str) -> InstallStep:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return InstallStep(
        name=f"write {path}",
        command=f"mkdir -p $(dirname {path}) && printf %s {encoded} | base64 -d > {path}",
    )


def append_text_step(
    path: str,
    text: str,
    *,
    unless_same_file_as: str | None = None,
    workdir: str = DEFAULT_WORKDIR,
) -> InstallStep:
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
                f'mkdir -p "$(dirname "$path")" {workdir}/.git/info',
                "payload=$(mktemp)",
                f"printf %s {encoded} | base64 -d > \"$payload\"",
                f'rel="${{path#{workdir}/}}"',
                'if [ -e "$path" ]; then',
                f'  if ! grep -Fq "{marker}" "$path"; then',
                f'    printf "\\n\\n<!-- {marker} start -->\\n" >> "$path"',
                '    cat "$payload" >> "$path"',
                f'    printf "<!-- {marker} end -->\\n" >> "$path"',
                "  fi",
                f'  if git -C {workdir} ls-files --error-unmatch "$rel" >/dev/null 2>&1; then',
                f'    git -C {workdir} update-index --skip-worktree -- "$rel"',
                "  else",
                f'    printf "%s\\n" "$rel" >> {workdir}/.git/info/exclude',
                "  fi",
                "else",
                '  cat "$payload" > "$path"',
                f'  printf "%s\\n" "$rel" >> {workdir}/.git/info/exclude',
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
    workdir: str = DEFAULT_WORKDIR,
) -> InstallStep:
    return append_text_step(
        destination or integration_file.destination.as_posix(),
        integration_file.content.decode("utf-8"),
        unless_same_file_as=unless_same_file_as,
        workdir=workdir,
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


def agent_rules_path(workdir: str) -> str:
    return f"{workdir}/AGENTS.md"


def claude_rules_path(workdir: str) -> str:
    return f"{workdir}/CLAUDE.md"


def integration_destination(
    integration_file: RuntimeIntegrationFile, workdir: str
) -> str:
    default_destination = integration_file.destination.as_posix()
    if workdir == DEFAULT_WORKDIR:
        return default_destination
    if default_destination.startswith(f"{DEFAULT_WORKDIR}/"):
        return workdir + default_destination[len(DEFAULT_WORKDIR):]
    return default_destination


def codex_integration_steps(
    bundle: RuntimeAgentIntegrationBundle,
    *,
    treatment: bool,
    workdir: str = DEFAULT_WORKDIR,
) -> tuple[InstallStep, ...]:
    steps = [
        append_integration_file_step(
            bundle.shared_rules,
            destination=integration_destination(bundle.shared_rules, workdir),
            workdir=workdir,
        )
    ]
    if treatment:
        steps.append(
            append_integration_file_step(
                bundle.rules,
                destination=integration_destination(bundle.rules, workdir),
                workdir=workdir,
            )
        )
        steps.extend(_skill_injection_steps(bundle, agent_rules_path(workdir), workdir=workdir))
    return tuple(steps)


def claude_integration_steps(
    bundle: RuntimeAgentIntegrationBundle,
    *,
    treatment: bool,
    workdir: str = DEFAULT_WORKDIR,
) -> tuple[InstallStep, ...]:
    rules_path = agent_rules_path(workdir)
    claude_path = claude_rules_path(workdir)
    steps = [
        append_integration_file_step(
            bundle.shared_rules,
            destination=integration_destination(bundle.shared_rules, workdir),
            workdir=workdir,
        ),
        append_integration_file_step(
            bundle.shared_rules,
            destination=claude_path,
            unless_same_file_as=rules_path,
            workdir=workdir,
        ),
    ]
    if treatment:
        steps.extend(
            [
                append_integration_file_step(
                    bundle.rules,
                    destination=integration_destination(bundle.rules, workdir),
                    workdir=workdir,
                ),
                append_integration_file_step(
                    bundle.rules,
                    destination=claude_path,
                    unless_same_file_as=rules_path,
                    workdir=workdir,
                ),
                *_skill_injection_steps(bundle, rules_path, workdir=workdir),
                *_skill_injection_steps(
                    bundle,
                    claude_path,
                    unless_same_file_as=rules_path,
                    workdir=workdir,
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
    workdir: str = DEFAULT_WORKDIR,
) -> tuple[InstallStep, ...]:
    return tuple(
        append_integration_file_step(
            file,
            destination=destination,
            unless_same_file_as=unless_same_file_as,
            workdir=workdir,
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


def node_toolchain_bootstrap_lines() -> list[str]:
    return [
        "if ! command -v pnpm >/dev/null 2>&1; then",
        '  export NVM_DIR="$HOME/.nvm"',
        '  if [ ! -s "$NVM_DIR/nvm.sh" ]; then',
        "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash",
        "  fi",
        '  \\. "$NVM_DIR/nvm.sh"',
        "  nvm install 22",
        "  npm install -g pnpm@10",
        "fi",
        'symnav_bench_node_bin="$(dirname "$(command -v node)")"',
    ]


def pinned_symnav_install_script(
    symnav_sha: str,
    *,
    codex: bool,
    allowed_commands: tuple[str, ...],
    workdir: str = DEFAULT_WORKDIR,
) -> str:
    escaped_sha = symnav_sha.replace("'", "")
    wrapper = symnav_command_wrapper(allowed_commands, f"{workdir}/bin/symnav-real")
    lines = [
        "set -eu",
        f"mkdir -p /opt {workdir}/bin {workdir}/.git/info",
        *node_toolchain_bootstrap_lines(),
        "git clone https://github.com/mohasarc/symnav.git /opt/symnav",
        "cd /opt/symnav",
        f"git checkout '{escaped_sha}'",
        "pnpm install --frozen-lockfile",
        "pnpm build",
        f"cat > {workdir}/bin/symnav-real <<EOF",
        "#!/bin/sh",
        'PATH="$symnav_bench_node_bin:\\$PATH"',
        "export PATH",
        "has_cwd=0",
        'for arg in "\\$@"; do',
        '  case "\\$arg" in',
        "    --cwd|--cwd=*) has_cwd=1 ;;",
        "  esac",
        "done",
        'if [ "\\$has_cwd" -eq 1 ]; then',
        '  exec pnpm --dir /opt/symnav --filter symnav dev "\\$@"',
        "fi",
        f'exec pnpm --dir /opt/symnav --filter symnav dev --cwd {workdir} "\\$@"',
        "EOF",
        f"chmod +x {workdir}/bin/symnav-real",
        f"cat > {workdir}/bin/symnav <<'EOF'",
        *wrapper.splitlines(),
        "EOF",
        f"chmod +x {workdir}/bin/symnav",
        f"ln -sf {workdir}/bin/symnav /usr/local/bin/symnav",
        "symnav --help >/dev/null",
        "git config --global user.name symnav-bench",
        "git config --global user.email symnav-bench@example.invalid",
    ]
    if codex:
        lines.append(f"mkdir -p {workdir}/.codex")
    return "\n".join(lines)


def workspace_capture_step(
    logs_dir: object,
    binaries: tuple[str, ...],
    workdir: str = DEFAULT_WORKDIR,
) -> InstallStep:
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
        f'if [ ! -e {workdir}/.git ]; then',
        f'  printf "%s\\n" "missing {workdir}/.git" > "$target/error.txt"',
        "  exit 0",
        "fi",
        f'git -C {workdir} status --short > "$target/status-short.txt" 2>&1',
        f'git -C {workdir} status --short --untracked-files=all > "$target/status-short-untracked.txt" 2>&1',
        f'git -C {workdir} diff --stat > "$target/diff-stat.txt" 2>&1',
        f'git -C {workdir} diff > "$target/diff.patch" 2>&1',
        f'git -C {workdir} diff --cached > "$target/diff-cached.patch" 2>&1',
        f'git -C {workdir} ls-files --others --exclude-standard > "$target/untracked-files.txt" 2>&1',
        'rm -rf "$target/untracked"',
        'mkdir -p "$target/untracked"',
        f'git -C {workdir} ls-files --others --exclude-standard | while IFS= read -r file; do',
        '  case "$file" in',
        '    .agents/*|.claude/*|AGENTS.md|CLAUDE.md|bin/symnav) continue ;;',
        "  esac",
        '  mkdir -p "$target/untracked/$(dirname "$file")"',
        f'  cp "{workdir}/$file" "$target/untracked/$file" 2>/dev/null || true',
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
