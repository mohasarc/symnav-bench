from __future__ import annotations

import json


NUDGE_JS = """
const tool = process.env.CLAUDE_TOOL_NAME || "";
const input = JSON.parse(process.env.CLAUDE_TOOL_INPUT || "{}");
const text = input.command || input.pattern || input.file_path || "";
if (/\\b(rg|grep|find|cat|sed|head|awk)\\b/.test(text) && !/\\bsymnav\\b/.test(text)) {
  console.error("For TypeScript orientation, consider symnav overview/resolve/def/refs/context/graph alongside normal reads and search.");
}
""".strip()


def claude_directive() -> str:
    return "\n".join(
        [
            "Before TypeScript code exploration, read .agents/skills/symnav/SKILL.md.",
            "Use that symnav skill for deterministic TypeScript orientation and symbol navigation.",
            "Use symnav overview, resolve, def, refs, context, and graph to choose what code to inspect.",
            "Use normal reads, search, tests, and edits whenever they help after orientation.",
            "Run overview only on a .ts or .tsx file, never on a directory.",
        ]
    )


def codex_agents_md(symnav: bool) -> str:
    lines = [
        "# Agent rules",
        "",
        "Always pass generous timeout_ms or yield_time_ms values for slow commands.",
        "Never abandon a slow command only because the first poll returned no output.",
    ]
    if symnav:
        lines.extend(
            [
                "",
                "Read .agents/skills/symnav/SKILL.md before TypeScript code exploration.",
                "Run symnav as `symnav --cwd /app <command> ...`; do not call pnpm, /opt/symnav, or wrapper internals.",
                "Use symnav for deterministic TypeScript orientation and symbol navigation, then read/search/test/edit normally as needed.",
                "Run overview only on a .ts or .tsx file, never on a directory; use resolve or rg --files first when you need to find the file.",
                "Start with overview --depth 0 for a file map, then expand with --depth or --at only where more structure helps.",
                "Use refs before changing exported behavior or call signatures; use graph when wrappers, adapters, callbacks, or dispatchers hide the call path.",
            ]
        )
    return "\n".join(lines) + "\n"


def claude_settings_json() -> str:
    return json.dumps(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Grep|Glob|Read|Bash",
                        "hooks": [{"type": "command", "command": "node /app/symnav-nudge.js"}],
                    }
                ]
            }
        },
        indent=2,
        sort_keys=True,
    )
