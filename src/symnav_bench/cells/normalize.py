from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from symnav_bench.batch_plan import TrialSlot
from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.attempt import (
    ATTEMPT_SCHEMA_VERSION,
    AttemptIdentity,
    AttemptRecord,
    classify_attempt,
)
from symnav_bench.cells.cell import Cell, CellStatus
from symnav_bench.cells.trajectory import (
    NormalizedToolEvent,
    extract_tool_events,
    summarize_adoption,
    write_tool_events_jsonl,
)
from symnav_bench.run.job_config import HarnessIdentity


@dataclass(frozen=True)
class HarnessMeta:
    image_version: str
    pier_version: str
    deep_swe_ref: str
    symnav_ref: str | None

    def to_json(self) -> dict[str, str | None]:
        return {
            "image_version": self.image_version,
            "pier_version": self.pier_version,
            "deep_swe_ref": self.deep_swe_ref,
            "symnav_ref": self.symnav_ref,
        }


def normalize_attempt(
    trial_dir: Path | None,
    slot: TrialSlot,
    identity: AttemptIdentity,
    harness: HarnessIdentity,
    pier_error: Exception | None,
    out_dir: Path,
) -> AttemptRecord:
    if identity.slot_id != slot.slot_id:
        raise ValueError("attempt identity slot does not match trial slot")
    attempt_dir = out_dir / slot.slot_id / "attempts" / identity.attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)
    result = _read_json(trial_dir / "result.json") if trial_dir else {}
    trajectory = _read_json(trial_dir / "agent" / "trajectory.json") if trial_dir else {}
    events = extract_tool_events(trajectory)
    write_tool_events_jsonl(events, attempt_dir / "tool-events.jsonl")
    if trial_dir:
        _copy_raw_trial_files(trial_dir, attempt_dir / "raw")
        _copy_captured_workspace_artifacts(trial_dir, attempt_dir / "raw" / "workspace")
        _write_workspace_artifacts(trial_dir, attempt_dir / "raw" / "workspace")
    attempt = AttemptRecord(
        schema_version=ATTEMPT_SCHEMA_VERSION,
        identity=identity,
        slot=slot,
        disposition=classify_attempt(result, pier_error),
        rewards=_rewards(result),
        usage=_usage(result),
        timing=_timing(result),
        agent_version=_agent_version(result),
        harness=harness,
        exception=_exception(result, pier_error),
        command_counts=_command_counts(events),
        adoption=summarize_adoption(events, _agent_steps(result)),
        written_at=datetime.now(UTC).isoformat(),
    )
    attempt_json = attempt.to_json()
    attempt_json.update(
        {
            "protocol_fingerprint": _environment_value("SYMNAV_BENCH_PROTOCOL_FINGERPRINT"),
            "suite_fingerprint": _environment_value("SYMNAV_BENCH_SUITE_FINGERPRINT"),
            "batch_id": _environment_value("SYMNAV_BENCH_BATCH_ID"),
        }
    )
    (attempt_dir / "attempt.json").write_text(
        json.dumps(attempt_json, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return attempt


def _environment_value(name: str) -> str | None:
    import os

    return os.environ.get(name)


def normalize_trial(
    trial_dir: Path | None,
    identity: CellIdentity,
    harness: HarnessMeta,
    status: CellStatus,
    error: str | None,
    out_dir: Path,
) -> Cell:
    cell_dir = out_dir / identity.dirname()
    if cell_dir.exists():
        shutil.rmtree(cell_dir)
    cell_dir.mkdir(parents=True)
    result = _read_json(trial_dir / "result.json") if trial_dir else {}
    trajectory = _read_json(trial_dir / "agent" / "trajectory.json") if trial_dir else {}
    events = extract_tool_events(trajectory)
    write_tool_events_jsonl(events, cell_dir / "tool-events.jsonl")
    if trial_dir:
        _copy_raw_trial_files(trial_dir, cell_dir / "raw")
        _copy_captured_workspace_artifacts(trial_dir, cell_dir / "raw" / "workspace")
        _write_workspace_artifacts(trial_dir, cell_dir / "raw" / "workspace")
    if not result and status != "error":
        status = "error"
        error = error or "missing or empty trial result"
    cell = Cell(
        identity=identity,
        status=status,
        error=error,
        solved=_solved(result),
        rewards=_rewards(result),
        usage=_usage(result),
        timing=_timing(result),
        agent_version=_agent_version(result),
        harness=harness.to_json(),
        command_counts=_command_counts(events),
        written_at=datetime.now(UTC).isoformat(),
    )
    (cell_dir / "cell.json").write_text(
        json.dumps(cell.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return cell


def _copy_raw_trial_files(trial_dir: Path, raw_dir: Path) -> None:
    for path in _raw_trial_paths(trial_dir):
        relative = path.relative_to(trial_dir)
        target = raw_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _raw_trial_paths(trial_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for name in ("result.json", "exception.txt", "trial.log"):
        path = trial_dir / name
        if path.is_file():
            paths.append(path)
    for name in ("trajectory.json", "codex.txt", "claude-code.txt"):
        path = trial_dir / "agent" / name
        if path.is_file():
            paths.append(path)
    for name in ("verifier", "steps"):
        paths.extend(_raw_files_under(trial_dir / name))
    return paths


def _raw_files_under(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    try:
        return [path for path in directory.rglob("*") if path.is_file()]
    except OSError:
        return []


def _copy_captured_workspace_artifacts(trial_dir: Path, workspace_dir: Path) -> None:
    source = trial_dir / "agent" / "workspace"
    if not source.exists():
        return
    for path in _raw_files_under(source):
        relative = path.relative_to(source)
        target = workspace_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _write_workspace_artifacts(trial_dir: Path, workspace_dir: Path) -> None:
    for workspace in _git_workspaces_under(trial_dir):
        relative = workspace.relative_to(trial_dir)
        target = workspace_dir / ("root" if str(relative) == "." else _safe_relative_name(relative))
        target.mkdir(parents=True, exist_ok=True)
        _write_git_command(workspace, ["git", "status", "--short"], target / "status-short.txt")
        _write_git_command(workspace, ["git", "diff", "--stat"], target / "diff-stat.txt")
        _write_git_command(workspace, ["git", "diff"], target / "diff.patch")
        _write_git_command(workspace, ["git", "diff", "--cached"], target / "diff-cached.patch")


def _git_workspaces_under(trial_dir: Path) -> list[Path]:
    try:
        git_paths = [
            path
            for path in trial_dir.rglob(".git")
            if _is_workspace_git_marker(path) and not _is_raw_support_path(trial_dir, path)
        ]
    except OSError:
        return []
    return sorted({path.parent for path in git_paths})


def _is_workspace_git_marker(path: Path) -> bool:
    return path.is_dir() or path.is_file()


def _is_raw_support_path(trial_dir: Path, path: Path) -> bool:
    return any(part in {"agent", "verifier", "steps"} for part in path.relative_to(trial_dir).parts)


def _safe_relative_name(relative: Path) -> str:
    return "__".join(part for part in relative.parts if part not in {"", "."})


def _write_git_command(workspace: Path, command: list[str], target: Path) -> None:
    result = subprocess.run(command, cwd=workspace, text=True, capture_output=True, check=False)
    content = result.stdout
    if result.stderr:
        content += ("\n" if content else "") + result.stderr
    if result.returncode != 0:
        content += f"\n[exit_code={result.returncode}]\n"
    target.write_text(content, encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _rewards(result: dict[str, Any]) -> dict[str, Any]:
    verifier = result.get("verifier_result")
    if not isinstance(verifier, dict):
        return {}
    rewards = verifier.get("rewards")
    return dict(rewards) if isinstance(rewards, dict) else {}


def _solved(result: dict[str, Any]) -> bool:
    return _rewards(result).get("f2p") == 1.0


def _usage(result: dict[str, Any]) -> dict[str, Any]:
    agent_result = result.get("agent_result")
    if not isinstance(agent_result, dict):
        return {}
    return {
        "n_input_tokens": agent_result.get("n_input_tokens"),
        "n_cache_tokens": agent_result.get("n_cache_tokens"),
        "n_output_tokens": agent_result.get("n_output_tokens"),
        "cost_usd_imputed": agent_result.get("cost_usd"),
        "peak_context_tokens": agent_result.get("peak_context_tokens"),
        "n_agent_steps": agent_result.get("n_agent_steps"),
    }


def _timing(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key.endswith("_seconds") or key in {"started_at", "finished_at", "phase_timings"}
    }


def _agent_version(result: dict[str, Any]) -> str | None:
    agent_info = result.get("agent_info")
    if not isinstance(agent_info, dict):
        return None
    version = agent_info.get("version")
    return str(version) if version is not None else None


def _agent_steps(result: dict[str, Any]) -> int | None:
    value = _usage(result).get("n_agent_steps")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _exception(
    result: dict[str, Any],
    pier_error: Exception | None,
) -> dict[str, Any] | None:
    info = result.get("exception_info")
    exception = dict(info) if isinstance(info, dict) else None
    if isinstance(info, str):
        exception = {"message": info}
    if pier_error is not None:
        pier_exception = {
            "exception_type": type(pier_error).__name__,
            "message": str(pier_error),
        }
        if exception is None:
            exception = pier_exception
        else:
            exception["pier_error"] = pier_exception
    return exception


def _command_counts(events: list[NormalizedToolEvent]) -> dict[str, Any]:
    symnav: dict[str, int] = {}
    symnav_failures: dict[str, int] = {}
    counts = {"search": 0, "read": 0, "other": 0, "timeouts": 0, "failures": 0}
    for event in events:
        if event.timed_out:
            counts["timeouts"] += 1
        if event.succeeded is False:
            counts["failures"] += 1
        for tag in event.tags:
            if tag.startswith("symnav:"):
                subcommand = tag.removeprefix("symnav:")
                symnav[subcommand] = symnav.get(subcommand, 0) + 1
                if event.succeeded is False:
                    symnav_failures[subcommand] = symnav_failures.get(subcommand, 0) + 1
            elif tag in counts:
                counts[tag] += 1
    return {
        "symnav": symnav,
        "symnav_failures": symnav_failures,
        "symnav_skill_reads": _symnav_skill_reads(events),
        **counts,
    }


def _symnav_skill_reads(events: list[NormalizedToolEvent]) -> int:
    return sum(
        1
        for event in events
        if event.kind == "skill" and "skill:symnav" in event.tags
    )
