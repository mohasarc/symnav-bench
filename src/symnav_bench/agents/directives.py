from __future__ import annotations

import json


NUDGE_JS = """
const tool = process.env.CLAUDE_TOOL_NAME || "";
const input = JSON.parse(process.env.CLAUDE_TOOL_INPUT || "{}");
const text = input.command || input.pattern || input.file_path || "";
if (/\\b(rg|grep|find|cat|sed|head|awk)\\b/.test(text) && !/\\bsymnav\\b/.test(text)) {
  console.error("For TypeScript orientation, run the global command symnav ... for overview/resolve/def/refs/context/graph alongside normal reads and search.");
}
""".strip()


def claude_directive() -> str:
    return "\n".join(
        [
            "Always read .agents/skills/symnav/SKILL.md before starting any work. No exceptions; read the symnav skill first.",
            "The symnav command is installed globally. Run it exactly as `symnav ...` from any shell.",
            "Use the global `symnav ...` command for deterministic TypeScript orientation and symbol navigation.",
            "Start TypeScript exploration with `symnav resolve <name>` or `symnav overview <file> --depth 0`.",
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
                "Always read .agents/skills/symnav/SKILL.md before starting any work. No exceptions; read the symnav skill first.",
                "The symnav command is installed globally. Run it exactly as `symnav ...` from any shell.",
                "Use the global `symnav ...` command for deterministic TypeScript orientation and symbol navigation.",
                "Start TypeScript exploration with `symnav resolve <name>` or `symnav overview <file> --depth 0`.",
                "Use symnav to choose what code to inspect, then read/search/test/edit normally as needed.",
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
                        "hooks": [{"type": "command", "command": "node /tmp/symnav-bench/symnav-nudge.js"}],
                    }
                ]
            }
        },
        indent=2,
        sort_keys=True,
    )
