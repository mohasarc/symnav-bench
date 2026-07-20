from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Iterator, Mapping

from symnav_bench.cells.trajectory import (
    _exec_source,
    _nested_calls,
    _observation_text,
    _primary_command,
)

ATTEMPT_VIEW_SCHEMA_VERSION = 1
MAX_OUTPUT_CHARS = 6000
MAX_MESSAGE_CHARS = 40000


def build_attempt_view(
    trajectory: Mapping[str, Any],
    summary: Mapping[str, Any],
    verifier: Mapping[str, Any] | None,
) -> dict[str, Any]:
    steps = [_step_view(step) for step in _iter_steps(trajectory)]
    patches = [
        tool["command"]
        for step in steps
        for tool in step["tools"]
        if tool["tool"] == "apply_patch" and tool["command"]
    ]
    system_messages = [step["text"] for step in steps if step["source"] == "system" and step["text"]]
    identity = summary.get("identity") or {}
    slot = summary.get("slot") or {}
    disposition = summary.get("disposition") or {}
    agent = trajectory.get("agent") or {}
    return {
        "schema_version": ATTEMPT_VIEW_SCHEMA_VERSION,
        "attempt_id": identity.get("attempt_id"),
        "slot_id": slot.get("slot_id") or identity.get("slot_id"),
        "task": slot.get("task"),
        "condition": slot.get("condition"),
        "repetition": slot.get("repetition"),
        "configuration_id": slot.get("configuration_id"),
        "outcome": disposition.get("outcome"),
        "scored_failure_reason": disposition.get("scored_failure_reason"),
        "retry_reason": disposition.get("retry_reason"),
        "detail": disposition.get("detail"),
        "rewards": summary.get("rewards") or {},
        "usage": summary.get("usage") or {},
        "timing": summary.get("timing") or {},
        "harness": summary.get("harness") or {},
        "adoption": summary.get("adoption") or {},
        "agent": {
            "name": agent.get("name"),
            "version": agent.get("version"),
            "model": agent.get("model_name"),
            "cwd": (agent.get("extra") or {}).get("cwd"),
            "git": (agent.get("extra") or {}).get("git"),
        },
        "totals": _totals(trajectory.get("final_metrics") or {}),
        "steps": steps,
        "patches": patches,
        "environment": {"system_messages": system_messages},
        "verifier": verifier or {},
    }


def build_trajectory_views(study_dir: Path, raw_dir: Path, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    trajectories = _index_trajectories(raw_dir)
    written: list[str] = []
    for summary_path in sorted((study_dir / "attempts").rglob("*.json")):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        attempt_id = (summary.get("identity") or {}).get("attempt_id")
        if not attempt_id:
            continue
        trajectory_path = trajectories.get(attempt_id)
        if trajectory_path is None:
            continue
        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
        verifier = _verifier_summary(trajectory_path.parent.parent / "verifier")
        view = build_attempt_view(trajectory, summary, verifier)
        (out_dir / f"{attempt_id}.json").write_text(
            json.dumps(view, sort_keys=True) + "\n", encoding="utf-8"
        )
        written.append(attempt_id)
    return written


def _index_trajectories(raw_dir: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in raw_dir.rglob("trajectory.json"):
        if path.parent.name != "agent":
            continue
        attempt_id = _attempt_id_from_path(path)
        if attempt_id and attempt_id not in index:
            index[attempt_id] = path
    return index


def _attempt_id_from_path(path: Path) -> str | None:
    parts = path.parts
    for index in range(len(parts) - 1, 0, -1):
        if parts[index - 1] == "attempts" and _looks_like_id(parts[index]):
            return parts[index]
    return None


def _looks_like_id(value: str) -> bool:
    return len(value) >= 24 and all(character in "0123456789abcdef" for character in value)


def _verifier_summary(verifier_dir: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    reward_path = verifier_dir / "reward.json"
    if reward_path.is_file():
        try:
            summary["reward"] = json.loads(reward_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    ctrf_path = verifier_dir / "ctrf.json"
    if ctrf_path.is_file():
        summary["tests"] = _ctrf_tests(ctrf_path)
    return summary


def _ctrf_tests(ctrf_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(ctrf_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    tests = ((data.get("results") or {}).get("tests")) or []
    passed = [test.get("name") for test in tests if isinstance(test, dict) and test.get("status") == "passed"]
    failed = [test.get("name") for test in tests if isinstance(test, dict) and test.get("status") == "failed"]
    return {"passed": len(passed), "failed": failed}


def _iter_steps(trajectory: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    steps = trajectory.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, Mapping):
                yield step


def _step_view(step: Mapping[str, Any]) -> dict[str, Any]:
    metrics = step.get("metrics") or {}
    extra = metrics.get("extra") or {}
    return {
        "i": step.get("step_id"),
        "t": step.get("timestamp"),
        "source": step.get("source"),
        "text": _truncate(_string(step.get("message")), MAX_MESSAGE_CHARS),
        "model": step.get("model_name"),
        "tokens": {
            "prompt": metrics.get("prompt_tokens"),
            "completion": metrics.get("completion_tokens"),
            "cached": metrics.get("cached_tokens"),
            "reasoning": extra.get("reasoning_output_tokens"),
        },
        "tools": _tool_views(step),
    }


def _tool_views(step: Mapping[str, Any]) -> list[dict[str, Any]]:
    calls = step.get("tool_calls")
    if not isinstance(calls, list):
        return []
    views: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, Mapping):
            continue
        output = _truncate(_clean_content(_observation_text(step, call)), MAX_OUTPUT_CHARS)
        source = _exec_source(call.get("arguments"))
        try:
            nested = _nested_calls(source)
        except ValueError:
            nested = []
        if nested:
            for index, (tool, args) in enumerate(nested):
                command = _primary_command(tool, args)
                if tool == "apply_patch" and not command:
                    command = _extract_patch(source)
                views.append(
                    {
                        "tool": tool,
                        "command": command,
                        "output": output if index == len(nested) - 1 else "",
                    }
                )
        elif "tools.apply_patch" in source:
            views.append({"tool": "apply_patch", "command": _extract_patch(source), "output": output})
        else:
            views.append(
                {
                    "tool": _string(call.get("function_name")) or "call",
                    "command": source or _string(call.get("arguments")),
                    "output": output,
                }
            )
    return views


def _extract_patch(source: str) -> str:
    match = re.search(r"\*\*\* Begin Patch(.*?)\*\*\* End Patch", source, re.DOTALL)
    if not match:
        return source
    body = "*** Begin Patch" + match.group(1) + "*** End Patch"
    return (
        body.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\'", "'")
    )


def _totals(final_metrics: Mapping[str, Any]) -> dict[str, Any]:
    extra = final_metrics.get("extra") or {}
    return {
        "prompt_tokens": final_metrics.get("total_prompt_tokens"),
        "completion_tokens": final_metrics.get("total_completion_tokens"),
        "cached_tokens": final_metrics.get("total_cached_tokens"),
        "reasoning_tokens": extra.get("reasoning_output_tokens"),
        "cost_usd": final_metrics.get("total_cost_usd"),
        "steps": final_metrics.get("total_steps"),
        "peak_context_tokens": extra.get("peak_context_tokens"),
    }


def _clean_content(raw: str) -> str:
    text = _string(raw).strip()
    if text.startswith("[") and "'text'" in text:
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return raw
        if isinstance(parsed, list):
            chunks = [
                item["text"]
                for item in parsed
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            if chunks:
                return "\n".join(chunks)
    return raw


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated {len(text) - limit} chars]"
