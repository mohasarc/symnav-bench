from __future__ import annotations

import json


NUDGE_JS = """
const tool = process.env.CLAUDE_TOOL_NAME || "";
const input = JSON.parse(process.env.CLAUDE_TOOL_INPUT || "{}");
const text = input.command || input.pattern || input.file_path || "";
if (/\\b(rg|grep|find|cat|sed|head|awk)\\b/.test(text) && !/\\bsymnav\\b/.test(text)) {
  console.error("Consider symnav overview/resolve/def/refs/context/graph before text search or file reads.");
}
""".strip()


def claude_directive() -> str:
    return "\n".join(
        [
            "Use the symnav skill at .agents/skills/symnav/SKILL.md before exploring TypeScript.",
            "Prefer symnav overview, resolve, def, refs, context, and graph for code navigation.",
            "Use text search only when symbol navigation cannot answer the question.",
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
                "Prefer symnav overview, resolve, def, refs, context, and graph over raw file reads.",
                "Use symnav first for TypeScript navigation, then fall back to text search only for non-TypeScript files or text that is not a symbol.",
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
