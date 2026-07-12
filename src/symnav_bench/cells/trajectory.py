from __future__ import annotations

import json
import re
import shlex
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


TIMEOUT_MARKERS: tuple[str, ...] = (
    "timed out",
    "timeout",
    "command exceeded",
    "killed after",
    "yielded before completion",
)

MAX_COMMAND_OUTPUT_CHARS = 200_000


ToolEventKind = Literal["shell", "read", "search", "patch", "skill", "other"]


@dataclass(frozen=True)
class NormalizedToolEvent:
    step_id: int
    timestamp: str | None
    tool: str
    command: str
    args: dict[str, Any]
    tags: tuple[str, ...]
    timed_out: bool
    exit_code: int | None
    succeeded: bool | None
    output_chars: int
    output_truncated: bool
    output: str
    sequence: int = 0
    outer_tool: str = ""
    kind: ToolEventKind = "other"
    session_id: str | int | None = None
    parser_warning: str | None = None


ExecutedCommand = NormalizedToolEvent


@dataclass(frozen=True)
class AdoptionSummary:
    used_symnav: bool
    read_symnav_skill: bool
    symnav_calls: int
    symnav_calls_per_agent_step: float
    symnav_failures: int
    symnav_timeouts: int
    first_symnav_step: int | None
    search_calls: int
    read_calls: int
    patch_calls: int
    command_counts: dict[str, int]


def extract_tool_events(trajectory: Mapping[str, Any]) -> list[NormalizedToolEvent]:
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        return []
    events: list[NormalizedToolEvent] = []
    skill_paths = _bundle_skill_paths(trajectory)
    for step_index, step in enumerate(steps):
        if not isinstance(step, Mapping):
            continue
        for tool_call in _tool_calls(step):
            outer_tool = _tool_name(tool_call)
            args = _tool_arguments(tool_call)
            observation = _observation_text(step, tool_call)
            if outer_tool == "exec":
                nested = extract_nested_exec_events(
                    {
                        "step_id": _step_id(step, step_index),
                        "timestamp": _timestamp(step),
                        "outer_tool": outer_tool,
                        "arguments": args,
                        "observation": observation,
                        "skill_paths": skill_paths,
                    }
                )
                first_sequence = len(events)
                events.extend(replace(event, sequence=first_sequence + index) for index, event in enumerate(nested))
                continue
            event = _normalized_event(
                step_id=_step_id(step, step_index),
                sequence=len(events),
                timestamp=_timestamp(step),
                outer_tool=outer_tool,
                tool=outer_tool,
                args=args,
                observation=observation,
                skill_paths=skill_paths,
            )
            events.append(event)
    return _reconstruct_command_sessions(events)


def extract_nested_exec_events(event: Mapping[str, Any]) -> list[NormalizedToolEvent]:
    args = event.get("arguments")
    source = _exec_source(args)
    observation = str(event.get("observation") or "")
    outer_tool = str(event.get("outer_tool") or "exec")
    step_id = _integer(event.get("step_id"), 0)
    timestamp = event.get("timestamp")
    normalized_timestamp = str(timestamp) if timestamp is not None else None
    raw_skill_paths = event.get("skill_paths")
    skill_paths = {
        str(path)
        for path in raw_skill_paths
        if isinstance(path, str)
    } if isinstance(raw_skill_paths, (set, tuple, list)) else set()
    try:
        calls = _nested_calls(source)
    except ValueError as error:
        return [
            _normalized_event(
                step_id=step_id,
                sequence=0,
                timestamp=normalized_timestamp,
                outer_tool=outer_tool,
                tool=outer_tool,
                args=_mapping(args),
                observation=observation,
                skill_paths=skill_paths,
                parser_warning=str(error),
            )
        ]
    if not calls:
        return [
            _normalized_event(
                step_id=step_id,
                sequence=0,
                timestamp=normalized_timestamp,
                outer_tool=outer_tool,
                tool=outer_tool,
                args=_mapping(args),
                observation=observation,
                skill_paths=skill_paths,
            )
        ]
    return [
        _normalized_event(
            step_id=step_id,
            sequence=sequence,
            timestamp=normalized_timestamp,
            outer_tool=outer_tool,
            tool=tool,
            args=nested_args,
            observation=observation,
            skill_paths=skill_paths,
        )
        for sequence, (tool, nested_args) in enumerate(calls)
    ]


def extract_commands(trajectory: dict[str, Any]) -> list[ExecutedCommand]:
    return extract_tool_events(trajectory)


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


def summarize_adoption(
    events: Sequence[NormalizedToolEvent],
    agent_steps: int | None,
) -> AdoptionSummary:
    symnav_events = [event for event in events if any(tag.startswith("symnav:") for tag in event.tags)]
    command_counts: dict[str, int] = {}
    for event in symnav_events:
        for tag in event.tags:
            if not tag.startswith("symnav:"):
                continue
            command = tag.removeprefix("symnav:")
            command_counts[command] = command_counts.get(command, 0) + 1
    symnav_calls = len(symnav_events)
    valid_agent_steps = agent_steps if agent_steps is not None and agent_steps > 0 else None
    return AdoptionSummary(
        used_symnav=bool(symnav_events),
        read_symnav_skill=any(event.kind == "skill" and "skill:symnav" in event.tags for event in events),
        symnav_calls=symnav_calls,
        symnav_calls_per_agent_step=symnav_calls / valid_agent_steps if valid_agent_steps else 0.0,
        symnav_failures=sum(event.succeeded is False for event in symnav_events),
        symnav_timeouts=sum(event.timed_out for event in symnav_events),
        first_symnav_step=min((event.step_id for event in symnav_events), default=None),
        search_calls=sum(event.kind == "search" or "search" in event.tags for event in events),
        read_calls=sum(event.kind == "read" or "read" in event.tags for event in events),
        patch_calls=sum(event.kind == "patch" for event in events),
        command_counts=command_counts,
    )


def write_commands_jsonl(commands: list[ExecutedCommand], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for command in commands:
            row = asdict(command)
            row["tags"] = list(command.tags)
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def _tool_calls(step: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    calls = step.get("tool_calls")
    if isinstance(calls, list):
        return [call for call in calls if isinstance(call, Mapping)]
    return []


def _normalized_event(
    *,
    step_id: int,
    sequence: int,
    timestamp: str | None,
    outer_tool: str,
    tool: str,
    args: dict[str, Any],
    observation: str,
    skill_paths: set[str],
    parser_warning: str | None = None,
) -> NormalizedToolEvent:
    command = _primary_command(tool, args)
    kind = _event_kind(tool, command, args, skill_paths)
    exit_code = _exit_code(observation)
    return NormalizedToolEvent(
        step_id=step_id,
        sequence=sequence,
        timestamp=timestamp,
        outer_tool=outer_tool,
        tool=tool,
        kind=kind,
        command=command,
        args=args,
        tags=_event_tags(tool, command, args, kind),
        session_id=args.get("session_id") or _running_session_id(observation),
        exit_code=exit_code,
        succeeded=None if exit_code is None else exit_code == 0,
        timed_out=_timed_out(observation),
        output=_truncate_output(observation),
        output_chars=len(observation),
        output_truncated=len(observation) > MAX_COMMAND_OUTPUT_CHARS,
        parser_warning=parser_warning,
    )


def _tool_name(tool_call: Mapping[str, Any]) -> str:
    name = str(tool_call.get("function_name") or tool_call.get("name") or "")
    return name.rsplit(".", 1)[-1].rsplit("__", 1)[-1]


def _tool_arguments(tool_call: Mapping[str, Any]) -> dict[str, Any]:
    arguments = tool_call.get("arguments")
    if isinstance(arguments, Mapping):
        return dict(arguments)
    if isinstance(arguments, str):
        return {"code": arguments}
    return {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _timestamp(step: Mapping[str, Any]) -> str | None:
    value = step.get("timestamp")
    return str(value) if value is not None else None


def _primary_command(tool: str, args: dict[str, Any]) -> str:
    if tool == "exec_command":
        return str(args.get("cmd") or "")
    if tool == "apply_patch":
        return str(args.get("patch") or "")
    for key in ("command", "cmd", "pattern", "file_path", "path"):
        if key in args:
            return str(args.get(key) or "")
    return ""


def _step_id(step: Mapping[str, Any], fallback: int) -> int:
    value = step.get("step_id", step.get("id", fallback))
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _observation_text(step: Mapping[str, Any], tool_call: Mapping[str, Any]) -> str:
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


def _event_kind(
    tool: str,
    command: str,
    args: Mapping[str, Any],
    skill_paths: set[str],
) -> ToolEventKind:
    lowered = tool.lower()
    if lowered == "skill" or _is_skill_read(command, args, skill_paths):
        return "skill"
    if lowered in {"exec_command", "bash", "write_stdin"}:
        return "shell"
    if lowered in {"read"}:
        return "read"
    if lowered in {"grep", "glob"}:
        return "search"
    if lowered in {"apply_patch", "edit", "write"}:
        return "patch"
    return "other"


def _event_tags(
    tool: str,
    command: str,
    args: Mapping[str, Any],
    kind: ToolEventKind,
) -> tuple[str, ...]:
    if kind == "skill":
        skill = str(args.get("skill") or "symnav")
        return (f"skill:{skill}",)
    classified = classify(tool, command)
    if classified != ("other",):
        return classified
    if kind in {"read", "search", "patch"}:
        return (kind,)
    return classified


def _is_skill_read(command: str, args: Mapping[str, Any], skill_paths: set[str]) -> bool:
    candidate = command or str(args.get("file_path") or args.get("path") or "")
    if any(path and path in candidate for path in skill_paths):
        return True
    normalized = candidate.replace("\\", "/")
    return bool(
        re.search(r"/\.agents/skills/symnav/SKILL\.md$", normalized)
        or re.search(r"/\.agents/integrations/symnav/variants/[^/]+/skill/SKILL\.md$", normalized)
    )


def _bundle_skill_paths(value: Mapping[str, Any]) -> set[str]:
    paths: set[str] = set()

    def visit(item: Any, under_skill_files: bool = False) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                visit(nested, under_skill_files or str(key) == "skill_files")
            return
        if isinstance(item, list):
            for nested in item:
                visit(nested, under_skill_files)
            return
        if under_skill_files and isinstance(item, str) and item.endswith("/SKILL.md"):
            paths.add(item)

    for key in ("bundle_metadata", "integration_bundle", "bundle"):
        metadata = value.get(key)
        if metadata is not None:
            visit(metadata)
    return paths


def _exec_source(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    if isinstance(arguments, Mapping):
        for key in ("code", "source", "input"):
            value = arguments.get(key)
            if isinstance(value, str):
                return value
    return ""


def _nested_calls(source: str) -> list[tuple[str, dict[str, Any]]]:
    call_pattern = re.compile(r"tools\.(exec_command|write_stdin|apply_patch)\s*\(")
    calls: list[tuple[str, dict[str, Any]]] = []
    position = 0
    while match := call_pattern.search(source, position):
        closing = _closing_parenthesis(source, match.end())
        if closing is None:
            raise ValueError(f"could not parse nested {match.group(1)} call")
        raw_arguments = source[match.end() : closing].strip()
        try:
            parsed = _JavascriptLiteralParser(raw_arguments).parse()
        except ValueError as error:
            raise ValueError(f"could not parse nested {match.group(1)} arguments: {error}") from error
        tool = match.group(1)
        if tool == "apply_patch":
            if not isinstance(parsed, str):
                raise ValueError("could not parse nested apply_patch arguments: expected string")
            arguments = {"patch": parsed}
        elif isinstance(parsed, dict):
            arguments = parsed
        else:
            raise ValueError(f"could not parse nested {tool} arguments: expected object")
        calls.append((tool, arguments))
        position = closing + 1
    if not calls and any(f"tools.{tool}" in source for tool in ("exec_command", "write_stdin", "apply_patch")):
        raise ValueError("could not parse nested tool call")
    return calls


def _closing_parenthesis(source: str, start: int) -> int | None:
    depth = 1
    quote: str | None = None
    escaped = False
    for index in range(start, len(source)):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'", "`"}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


class _JavascriptLiteralParser:
    def __init__(self, source: str) -> None:
        self._source = source
        self._position = 0

    def parse(self) -> Any:
        value = self._value()
        self._whitespace()
        if self._position != len(self._source):
            raise ValueError("unexpected trailing input")
        return value

    def _value(self) -> Any:
        self._whitespace()
        character = self._peek()
        if character == "{":
            return self._object()
        if character == "[":
            return self._array()
        if character in {'"', "'", "`"}:
            return self._string()
        number = re.match(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?", self._source[self._position :])
        if number:
            token = number.group(0)
            self._position += len(token)
            return float(token) if any(marker in token for marker in (".", "e", "E")) else int(token)
        identifier = self._identifier()
        if identifier == "true":
            return True
        if identifier == "false":
            return False
        if identifier in {"null", "undefined"}:
            return None
        raise ValueError(f"unsupported value {identifier!r}")

    def _object(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        self._expect("{")
        self._whitespace()
        if self._consume("}"):
            return result
        while True:
            self._whitespace()
            key = self._string() if self._peek() in {'"', "'", "`"} else self._identifier()
            if not key:
                raise ValueError("missing object key")
            self._whitespace()
            self._expect(":")
            result[key] = self._value()
            self._whitespace()
            if self._consume("}"):
                return result
            self._expect(",")
            self._whitespace()
            if self._consume("}"):
                return result

    def _array(self) -> list[Any]:
        result: list[Any] = []
        self._expect("[")
        self._whitespace()
        if self._consume("]"):
            return result
        while True:
            result.append(self._value())
            self._whitespace()
            if self._consume("]"):
                return result
            self._expect(",")

    def _string(self) -> str:
        quote = self._peek()
        if quote not in {'"', "'", "`"}:
            raise ValueError("expected string")
        self._position += 1
        characters: list[str] = []
        escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
        while self._position < len(self._source):
            character = self._source[self._position]
            self._position += 1
            if character == quote:
                return "".join(characters)
            if character != "\\":
                characters.append(character)
                continue
            if self._position >= len(self._source):
                raise ValueError("unterminated escape")
            escaped = self._source[self._position]
            self._position += 1
            if escaped == "u":
                digits = self._source[self._position : self._position + 4]
                if len(digits) != 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                    raise ValueError("invalid unicode escape")
                characters.append(chr(int(digits, 16)))
                self._position += 4
            else:
                characters.append(escapes.get(escaped, escaped))
        raise ValueError("unterminated string")

    def _identifier(self) -> str:
        match = re.match(r"[A-Za-z_$][A-Za-z0-9_$-]*", self._source[self._position :])
        if not match:
            return ""
        identifier = match.group(0)
        self._position += len(identifier)
        return identifier

    def _whitespace(self) -> None:
        while self._position < len(self._source) and self._source[self._position].isspace():
            self._position += 1

    def _peek(self) -> str:
        return self._source[self._position] if self._position < len(self._source) else ""

    def _consume(self, expected: str) -> bool:
        if self._peek() != expected:
            return False
        self._position += 1
        return True

    def _expect(self, expected: str) -> None:
        if not self._consume(expected):
            raise ValueError(f"expected {expected!r}")


def _integer(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _reconstruct_command_sessions(events: list[NormalizedToolEvent]) -> list[NormalizedToolEvent]:
    reconstructed: list[NormalizedToolEvent] = []
    commands_by_session: dict[str, int] = {}
    commands_by_cell: dict[str, int] = {}
    for event in events:
        if event.tool == "wait":
            cell_id = str(event.args.get("cell_id") or "")
            command_index = commands_by_cell.get(cell_id)
            if command_index is not None:
                reconstructed[command_index] = _with_completion(reconstructed[command_index], event)
                continue
        if event.tool == "write_stdin":
            session_id = str(event.session_id or "")
            command_index = commands_by_session.get(session_id)
            if command_index is not None:
                original = reconstructed[command_index]
                reconstructed[command_index] = _with_completion(original, event)
                if event.outer_tool == "exec":
                    continue
                event = replace(event, command=original.command, tags=original.tags)
        command_index = len(reconstructed)
        reconstructed.append(event)
        if event.command and event.session_id is not None:
            commands_by_session[str(event.session_id)] = command_index
        cell_id = _running_cell_id(event.output)
        if event.command and cell_id is not None:
            commands_by_cell[cell_id] = command_index
    return [replace(event, sequence=sequence) for sequence, event in enumerate(reconstructed)]


def _with_completion(
    original: NormalizedToolEvent,
    completion: NormalizedToolEvent,
) -> NormalizedToolEvent:
    return replace(
        original,
        exit_code=completion.exit_code,
        succeeded=completion.succeeded,
        timed_out=completion.timed_out,
        output=completion.output,
        output_chars=completion.output_chars,
        output_truncated=completion.output_truncated,
        parser_warning=completion.parser_warning or original.parser_warning,
    )


def _running_cell_id(text: str) -> str | None:
    match = re.search(r"Script running with cell ID ([^\s]+)", text)
    return match.group(1) if match else None


def _truncate_output(text: str) -> str:
    if len(text) <= MAX_COMMAND_OUTPUT_CHARS:
        return text
    omitted = len(text) - MAX_COMMAND_OUTPUT_CHARS
    while True:
        marker = f"\n[... truncated {omitted} chars ...]\n"
        retained = MAX_COMMAND_OUTPUT_CHARS - len(marker)
        if retained <= 0:
            return marker[:MAX_COMMAND_OUTPUT_CHARS]
        head = retained // 2
        tail = retained - head
        next_omitted = len(text) - head - tail
        if next_omitted == omitted:
            return f"{text[:head]}{marker}{text[-tail:]}"
        omitted = next_omitted


def _timed_out(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in TIMEOUT_MARKERS)


def _exit_code(text: str) -> int | None:
    match = re.search(r"(?:Process exited with code|Exit code) (-?\d+)", text)
    return int(match.group(1)) if match else None


def _running_session_id(text: str) -> int | None:
    match = re.search(r"Process running with session ID (\d+)", text)
    return int(match.group(1)) if match else None


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
