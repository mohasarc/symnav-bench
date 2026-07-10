from __future__ import annotations

import json

from symnav_bench.run_spec import SymnavSkillVariant


def nudge_js(symnav_skill_variant: SymnavSkillVariant = "all") -> str:
    command_text = (
        "overview, resolve, def, refs, context, and graph"
        if symnav_skill_variant == "all"
        else symnav_skill_variant
    )
    return f"""
const tool = process.env.CLAUDE_TOOL_NAME || "";
const input = JSON.parse(process.env.CLAUDE_TOOL_INPUT || "{{}}");
const text = input.command || input.pattern || input.file_path || "";
if (/\\b(rg|grep|find|cat|sed|head|awk)\\b/.test(text) && !/\\bsymnav\\b/.test(text)) {{
  console.error("The global symnav command is available for TypeScript symbol navigation in this benchmark arm: {command_text}. Invoke it as symnav ... alongside normal reads and search.");
}}
""".strip()


NUDGE_JS = nudge_js()


def claude_directive(symnav_skill_variant: SymnavSkillVariant = "all") -> str:
    return "\n".join(_base_lines(symnav_skill_variant))


def codex_agents_md(symnav: bool, symnav_skill_variant: SymnavSkillVariant = "all") -> str:
    lines = [
        "# Agent rules",
        "",
        "Hard rule: this environment can be slow. For every shell command you run, ALWAYS wait at least 5 minutes before treating it as stuck because it produced no output.",
        "When a tool supports timeout_ms or yield_time_ms, pass at least 300000 for commands you run.",
        "Continue polling long-running commands until at least 5 minutes have elapsed; an early empty poll is not the final result.",
    ]
    if symnav:
        lines.extend(["", *_symnav_lines(symnav_skill_variant)])
    return "\n".join(lines) + "\n"


def _base_lines(symnav_skill_variant: SymnavSkillVariant) -> list[str]:
    return [
        "Hard rule: this environment can be slow. For every shell command you run, ALWAYS wait at least 5 minutes before treating it as stuck because it produced no output.",
        "Continue polling long-running commands until at least 5 minutes have elapsed; an early empty poll is not the final result.",
        *_symnav_lines(symnav_skill_variant),
    ]


def _symnav_lines(symnav_skill_variant: SymnavSkillVariant) -> list[str]:
    command_text = (
        "overview, resolve, def, refs, context, and graph"
        if symnav_skill_variant == "all"
        else symnav_skill_variant
    )
    lines = [
        "Always read .agents/skills/symnav/SKILL.md before starting any work. No exceptions; read the symnav skill first.",
        "The symnav command is installed globally. Run it exactly as `symnav ...` from any shell.",
    ]
    if symnav_skill_variant == "all":
        lines.extend(
            [
                "The global `symnav ...` command provides deterministic TypeScript orientation and symbol navigation.",
                "Available symnav commands include overview, resolve, def, refs, context, and graph.",
                "Normal reads, search, tests, and edits remain available whenever they help.",
                "Run overview only on a .ts or .tsx file, never on a directory; use resolve or rg --files first when you need to find the file.",
            ]
        )
        return lines
    lines.extend(
        [
            f"This benchmark arm exposes only the `symnav {command_text}` command for symnav usage.",
            f"If you use symnav in this run, use `symnav {command_text} ...`; normal reads, search, tests, and edits remain available whenever they help.",
        ]
    )
    if symnav_skill_variant == "overview":
        lines.append("Run overview only on a .ts or .tsx file, never on a directory; use rg --files first when you need to find the file.")
    return lines


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
