from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.cell import Cell, CellStatus
from symnav_bench.cells.trajectory import ExecutedCommand, extract_commands, write_commands_jsonl


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
    commands = extract_commands(trajectory)
    write_commands_jsonl(commands, cell_dir / "commands.jsonl")
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
        command_counts=_command_counts(commands),
        written_at=datetime.now(UTC).isoformat(),
    )
    (cell_dir / "cell.json").write_text(
        json.dumps(cell.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return cell


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


def _command_counts(commands: list[ExecutedCommand]) -> dict[str, Any]:
    symnav: dict[str, int] = {}
    counts = {"search": 0, "read": 0, "other": 0, "timeouts": 0}
    for command in commands:
        if command.timed_out:
            counts["timeouts"] += 1
        for tag in command.tags:
            if tag.startswith("symnav:"):
                subcommand = tag.removeprefix("symnav:")
                symnav[subcommand] = symnav.get(subcommand, 0) + 1
            elif tag in counts:
                counts[tag] += 1
    return {"symnav": symnav, **counts}
