from __future__ import annotations

import json
import re
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


TIMEOUT_MARKERS: tuple[str, ...] = (
    "timed out",
    "timeout",
    "command exceeded",
    "killed after",
    "yielded before completion",
)


@dataclass(frozen=True)
class ExecutedCommand:
    step_id: int
    timestamp: str
    tool: str
    command: str
    args: dict[str, Any]
    tags: tuple[str, ...]
    timed_out: bool


def extract_commands(trajectory: dict[str, Any]) -> list[ExecutedCommand]:
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        return []
    commands: list[ExecutedCommand] = []
    for step_index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        for tool_call in _tool_calls(step):
            tool = str(tool_call.get("function_name") or tool_call.get("name") or "")
            args = tool_call.get("arguments")
            if not isinstance(args, dict):
                args = {}
            command = _primary_command(tool, args)
            observation = _observation_text(step, tool_call)
            commands.append(
                ExecutedCommand(
                    step_id=_step_id(step, step_index),
                    timestamp=str(step.get("timestamp") or ""),
                    tool=tool,
                    command=command,
                    args=dict(args),
                    tags=classify(tool, command),
                    timed_out=_timed_out(observation),
                )
            )
    return commands


def classify(tool: str, command: str) -> tuple[str, ...]:
    lowered_tool = tool.lower()
    lowered_command = command.lower()
    symnav = _symnav_subcommand(command)
    if symnav:
        return (f"symnav:{symnav}",)
    if lowered_tool in {"grep", "glob"} or _starts_with(lowered_command, ("rg", "grep", "find")):
        return ("search",)
    if lowered_command.startswith("git grep"):
        return ("search",)
    if lowered_tool == "read" or _starts_with(lowered_command, ("cat", "head", "awk")):
        return ("read",)
    if lowered_command.startswith("sed -n") or lowered_command.startswith("sed "):
        return ("read",)
    return ("other",)


def write_commands_jsonl(commands: list[ExecutedCommand], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for command in commands:
            row = asdict(command)
            row["tags"] = list(command.tags)
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def _tool_calls(step: dict[str, Any]) -> list[dict[str, Any]]:
    calls = step.get("tool_calls")
    if isinstance(calls, list):
        return [call for call in calls if isinstance(call, dict)]
    return []


def _primary_command(tool: str, args: dict[str, Any]) -> str:
    if tool == "exec_command":
        return str(args.get("cmd") or "")
    for key in ("command", "cmd", "pattern", "file_path", "path"):
        if key in args:
            return str(args.get(key) or "")
    return ""


def _step_id(step: dict[str, Any], fallback: int) -> int:
    value = step.get("step_id", step.get("id", fallback))
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _observation_text(step: dict[str, Any], tool_call: dict[str, Any]) -> str:
    chunks: list[str] = []
    for source in (step, tool_call):
        for key in ("observation", "output", "result", "content"):
            value = source.get(key)
            if isinstance(value, str):
                chunks.append(value)
    return "\n".join(chunks)


def _timed_out(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in TIMEOUT_MARKERS)


def _symnav_subcommand(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for index, token in enumerate(tokens):
        if token.endswith("symnav") or token == "symnav-bench":
            if index + 1 < len(tokens):
                return tokens[index + 1]
    match = re.search(r"\bsymnav\s+([a-z-]+)", command)
    return match.group(1) if match else None


def _starts_with(command: str, words: tuple[str, ...]) -> bool:
    return any(command == word or command.startswith(f"{word} ") for word in words)
