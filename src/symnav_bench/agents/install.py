from __future__ import annotations

import base64
import shlex
import textwrap
from dataclasses import dataclass

from symnav_bench.run_spec import SymnavCommand, SymnavSkillVariant, symnav_variant_commands


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


def symnav_install_script(symnav_sha: str, *, codex: bool, skill_variant: SymnavSkillVariant = "all") -> str:
    escaped_sha = symnav_sha.replace("'", "")
    allowed_commands = "" if skill_variant == "all" else " ".join(symnav_variant_commands(skill_variant))
    skill_help_path = "" if skill_variant == "all" else f"/app/.agents/skills/symnav-{skill_variant}/SKILL.md"
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
        *_write_skill_variant_lines(skill_variant),
        "cat > /app/bin/symnav <<'EOF'",
        "#!/bin/sh",
        f"allowed_commands='{allowed_commands}'",
        f"skill_help_path='{skill_help_path}'",
        "if [ -n \"$allowed_commands\" ]; then",
        "  if [ \"$#\" -eq 0 ]; then",
        "    cat \"$skill_help_path\"",
        "    exit 0",
        "  fi",
        "  for arg in \"$@\"; do",
        "    case \"$arg\" in",
        "      --help|-h|help)",
        "        cat \"$skill_help_path\"",
        "        exit 0",
        "        ;;",
        "    esac",
        "    case \"$arg\" in",
        "      overview|resolve|def|refs|context|graph|stats)",
        "        allowed=0",
        "        for command in $allowed_commands; do",
        "          if [ \"$arg\" = \"$command\" ]; then allowed=1; fi",
        "        done",
        "        if [ \"$allowed\" -ne 1 ]; then",
        "          echo \"Unsupported symnav invocation for this benchmark arm.\" >&2",
        "          exit 2",
        "        fi",
        "        break",
        "        ;;",
        "    esac",
        "  done",
        "fi",
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


def _write_skill_variant_lines(skill_variant: SymnavSkillVariant) -> list[str]:
    if skill_variant == "all":
        return []
    skill_dir = f"/app/.agents/skills/symnav-{skill_variant}"
    return [
        "rm -rf /app/.agents/skills/symnav",
        f"mkdir -p {skill_dir}",
        f"cat > {skill_dir}/SKILL.md <<'EOF'",
        *symnav_skill_markdown(skill_variant).splitlines(),
        "EOF",
    ]


def symnav_skill_markdown(skill_variant: SymnavSkillVariant) -> str:
    commands = symnav_variant_commands(skill_variant)
    body = "\n\n".join(_variant_body(command) for command in commands)
    commands_text = " and ".join(f"`symnav {command}`" for command in commands)
    noun = "commands are" if len(commands) > 1 else "command is"
    return "\n".join(
        [
            "---",
            f"name: symnav-{skill_variant}",
            f"description: Use {commands_text} for deterministic TypeScript symbol navigation in this benchmark arm.",
            "---",
            "",
            f"{commands_text} {noun} installed globally.",
            "",
            "```",
            *(f"symnav {command} ..." for command in commands),
            "```",
            "",
            "Use normal reads, search, tests, and edits whenever they help.",
            "",
            body,
            "",
        ]
    )


def _variant_body(command: SymnavCommand) -> str:
    bodies: dict[SymnavCommand, str] = {
        "overview": """\
## `overview`

`overview` prints a symbol and fold tree for one TypeScript source file.

```
$ symnav overview src/file.ts --depth 0
$ symnav overview src/file.ts --depth 1
$ symnav overview src/file.ts --depth 2
$ symnav overview src/file.ts --at 'class Example' --depth 2
```

Use a `.ts` or `.tsx` file path, not a directory. `--depth` controls nesting. `--at <text>` selects a matching symbol, class, function, test block, or fold header from the overview output.
""",
        "resolve": """\
## `resolve`

`resolve` lists symbols and files whose names match a query.

```
$ symnav resolve 'queryClient'
$ symnav resolve 'QueryObserver'
$ symnav resolve --regex 'create.*Persister'
```

Pass one query per command. Use `--regex` for JavaScript regular expression matching. The output lists candidates; copy a precise candidate when you need to refer to a specific symbol elsewhere in normal code inspection.
""",
        "def": """\
## `def`

`def` prints the declaration location and signature for a unique symbol target.

```
$ symnav def charge
$ symnav def orders.ts::charge
$ symnav def src/orders.ts::PaymentProcessor::charge
```

Targets are suffix patterns. A short name works when it is unique. If the target is ambiguous, `def` prints candidates; copy a more specific candidate from that output. Quote targets that contain shell-sensitive characters.

Use workspace-relative file paths in targets. Write `src/orders.ts::charge`, not `/app/src/orders.ts::charge`. If `def` says a target is ambiguous, choose the printed candidate that matches the symbol you need and retry with that exact candidate string. If it says no symbol target was found, re-check that the file path is workspace-relative and that the symbol name appears in prior output.
""",
        "refs": """\
## `refs`

`refs` lists workspace references to a unique symbol target, grouped by file.

```
$ symnav refs src/orders.ts::charge
$ symnav refs src/orders.ts::charge --all
$ symnav refs src/orders.ts::charge --page 2 --page-size 50
```

Targets are suffix patterns. Use workspace-relative file paths in targets. Write `src/orders.ts::charge`, not `/app/src/orders.ts::charge`. Use `--all` for one complete listing, or page through large result sets. `--full-lines` prints untrimmed source previews.

If `refs` says a target is ambiguous, choose the printed candidate that matches the symbol you need and retry with that exact candidate string. If it says no symbol target was found, re-check that the file path is workspace-relative and that the symbol name appears in prior output.
""",
        "context": """\
## `context`

`context` prints one block around a symbol: definition, direct callers, direct callees, reference summary, and recent git history.

```
$ symnav context src/orders.ts::charge
$ symnav context src/orders.ts::PaymentProcessor::charge
```

Targets are suffix patterns and must identify one workspace symbol. Use workspace-relative file paths in targets. Write `src/orders.ts::charge`, not `/app/src/orders.ts::charge`. `context` reports direct statically resolved callers and callees in workspace files.

If `context` says a target is ambiguous, choose the printed candidate that matches the symbol you need and retry with that exact candidate string. If it says no symbol target was found, re-check that the file path is workspace-relative and that the symbol name appears in prior output.
""",
        "graph": """\
## `graph`

`graph` prints multi-hop incoming or outgoing call paths around a unique symbol target.

```
$ symnav graph src/orders.ts::charge --incoming --depth 2
$ symnav graph src/orders.ts::charge --outgoing --depth 3
$ symnav graph src/orders.ts::charge --incoming --depth 2 --all
```

Use workspace-relative file paths in targets. Write `src/orders.ts::charge`, not `/app/src/orders.ts::charge`. `--incoming` follows callers. `--outgoing` follows callees. `--depth` controls hop count. Use `--page`, `--page-size`, or `--all` for larger graphs.

If `graph` says a target is ambiguous, choose the printed candidate that matches the symbol you need and retry with that exact candidate string. If it says no symbol target was found, re-check that the file path is workspace-relative and that the symbol name appears in prior output.
""",
    }
    return textwrap.dedent(bodies[command]).strip()
