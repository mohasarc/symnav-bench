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
    exit_code: int | None
    succeeded: bool | None
    output_chars: int


def extract_commands(trajectory: dict[str, Any]) -> list[ExecutedCommand]:
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        return []
    commands: list[ExecutedCommand] = []
    commands_by_session: dict[str, str] = {}
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
            if not command and tool == "write_stdin":
                command = commands_by_session.get(str(args.get("session_id") or ""), "")
            session_id = _running_session_id(observation)
            if command and session_id:
                commands_by_session[session_id] = command
            exit_code = _exit_code(observation)
            commands.append(
                ExecutedCommand(
                    step_id=_step_id(step, step_index),
                    timestamp=str(step.get("timestamp") or ""),
                    tool=tool,
                    command=command,
                    args=dict(args),
                    tags=classify(tool, command),
                    timed_out=_timed_out(observation),
                    exit_code=exit_code,
                    succeeded=None if exit_code is None else exit_code == 0,
                    output_chars=len(observation),
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
    observation = step.get("observation")
    call_id = tool_call.get("tool_call_id")
    if isinstance(observation, dict):
        results = observation.get("results")
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, dict):
                    continue
                if call_id is not None and result.get("source_call_id") != call_id:
                    continue
                content = result.get("content")
                if isinstance(content, str):
                    chunks.append(content)
            if chunks:
                return "\n".join(chunks)
    for source in (step, tool_call):
        for key in ("observation", "output", "result", "content"):
            value = source.get(key)
            if isinstance(value, str):
                chunks.append(value)
    return "\n".join(chunks)


def _timed_out(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in TIMEOUT_MARKERS)


def _exit_code(text: str) -> int | None:
    match = re.search(r"(?:Process exited with code|Exit code) (-?\d+)", text)
    return int(match.group(1)) if match else None


def _running_session_id(text: str) -> str | None:
    match = re.search(r"Process running with session ID (\d+)", text)
    return match.group(1) if match else None


def _symnav_subcommand(command: str) -> str | None:
    tokens = _shell_tokens(command)
    for index, token in enumerate(tokens):
        if _is_symnav_executable(token):
            return _next_symnav_subcommand(tokens[index + 1 :])
    if _is_pnpm_symnav_invocation(tokens):
        return _next_symnav_subcommand(tokens)
    if "symnav" in command:
        match = re.search(r"\bsymnav\s+([a-z-]+)", command)
        return match.group(1) if match else None
    return None


def _shell_tokens(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if len(tokens) >= 3 and tokens[0].endswith("bash") and tokens[1] == "-lc":
        try:
            return shlex.split(tokens[2])
        except ValueError:
            return tokens[2].split()
    return tokens


def _is_symnav_executable(token: str) -> bool:
    return token == "symnav" or token.endswith("/symnav")


def _is_pnpm_symnav_invocation(tokens: list[str]) -> bool:
    return (
        "pnpm" in tokens
        and "symnav" in tokens
        and any(token.endswith("/symnav") or token == "/opt/symnav" for token in tokens)
    )


def _next_symnav_subcommand(tokens: list[str]) -> str | None:
    commands = {"overview", "resolve", "def", "refs", "context", "graph", "stats"}
    for token in tokens:
        if token in commands:
            return token
        if token in {"--help", "-h"}:
            return "help"
    return None


def _starts_with(command: str, words: tuple[str, ...]) -> bool:
    return any(command == word or command.startswith(f"{word} ") for word in words)
