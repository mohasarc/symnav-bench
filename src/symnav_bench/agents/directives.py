from __future__ import annotations

import json

from symnav_bench.run_spec import SymnavSkillVariant, symnav_variant_commands


def nudge_js(symnav_skill_variant: SymnavSkillVariant = "all") -> str:
    command_text = command_list_text(symnav_skill_variant)
    noun = command_noun(symnav_skill_variant)
    return f"""
const tool = process.env.CLAUDE_TOOL_NAME || "";
const input = JSON.parse(process.env.CLAUDE_TOOL_INPUT || "{{}}");
const text = input.command || input.pattern || input.file_path || "";
if (/\\b(rg|grep|find|cat|sed|head|awk)\\b/.test(text) && !/\\bsymnav\\b/.test(text)) {{
  console.error("The global {command_text} {noun} available for TypeScript symbol navigation in this benchmark arm. Invoke it alongside normal reads and search.");
}}
""".strip()


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
    if symnav_skill_variant == "all":
        return [
            "Always read .agents/skills/symnav/SKILL.md before starting any work. No exceptions; read the symnav skill first.",
            "The symnav command is installed globally. Run it exactly as `symnav ...` from any shell.",
            "The global `symnav ...` command provides deterministic TypeScript orientation and symbol navigation.",
            "Available symnav commands include overview, resolve, def, refs, context, and graph.",
            "Normal reads, search, tests, and edits remain available whenever they help.",
            "Run overview only on a .ts or .tsx file, never on a directory; use resolve or rg --files first when you need to find the file.",
        ]
    commands = symnav_variant_commands(symnav_skill_variant)
    commands_text = command_list_text(symnav_skill_variant)
    noun = command_noun(symnav_skill_variant)
    invocation_text = " or ".join(f"`symnav {command} ...`" for command in commands)
    lines = [
        f"Always read .agents/skills/symnav-{symnav_skill_variant}/SKILL.md before starting any work. No exceptions; read the symnav-{symnav_skill_variant} skill first.",
        f"The {commands_text} {noun} installed globally. Run {command_pronoun(symnav_skill_variant)} exactly as {invocation_text} from any shell.",
        f"{command_subject(symnav_skill_variant)} {command_verb(symnav_skill_variant)} deterministic TypeScript symbol navigation.",
        "Normal reads, search, tests, and edits remain available whenever they help.",
    ]
    if "overview" in commands:
        lines.append("Run overview only on a .ts or .tsx file, never on a directory; use rg --files first when you need to find the file.")
    return lines


def command_list_text(symnav_skill_variant: SymnavSkillVariant) -> str:
    if symnav_skill_variant == "all":
        return "overview, resolve, def, refs, context, and graph"
    return " and ".join(f"`symnav {command}`" for command in symnav_variant_commands(symnav_skill_variant))


def command_noun(symnav_skill_variant: SymnavSkillVariant) -> str:
    return "commands are" if len(symnav_variant_commands(symnav_skill_variant)) > 1 else "command is"


def command_pronoun(symnav_skill_variant: SymnavSkillVariant) -> str:
    return "them" if len(symnav_variant_commands(symnav_skill_variant)) > 1 else "it"


def command_subject(symnav_skill_variant: SymnavSkillVariant) -> str:
    return "These commands" if len(symnav_variant_commands(symnav_skill_variant)) > 1 else "This command"


def command_verb(symnav_skill_variant: SymnavSkillVariant) -> str:
    return "provide" if len(symnav_variant_commands(symnav_skill_variant)) > 1 else "provides"


NUDGE_JS = nudge_js()


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
