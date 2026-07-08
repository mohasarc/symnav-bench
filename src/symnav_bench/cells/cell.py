from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from symnav_bench.cell_identity import CellIdentity
from symnav_bench.run_spec import AgentSpec


CELL_SCHEMA_VERSION = 1
CellStatus = Literal["completed", "limited", "error"]


@dataclass(frozen=True)
class Cell:
    identity: CellIdentity
    status: CellStatus
    error: str | None
    solved: bool
    rewards: dict[str, Any]
    usage: dict[str, Any]
    timing: dict[str, Any]
    agent_version: str | None
    harness: dict[str, Any]
    command_counts: dict[str, Any]
    written_at: str | None = None

    @classmethod
    def load(cls, cell_json: Path) -> "Cell":
        data = json.loads(cell_json.read_text(encoding="utf-8"))
        identity_data = data["identity"]
        identity = CellIdentity(
            spec=AgentSpec(
                agent=identity_data["agent"],
                model=identity_data["model"],
                effort=identity_data["effort"],
            ),
            condition_label=identity_data["condition"],
            task=identity_data["task"],
            rep=int(identity_data["rep"]),
        )
        return cls(
            identity=identity,
            status=data["status"],
            error=data.get("error"),
            solved=bool(data.get("solved", False)),
            rewards=dict(data.get("rewards", {})),
            usage=dict(data.get("usage", {})),
            timing=dict(data.get("timing", {})),
            agent_version=data.get("agent_version"),
            harness=dict(data.get("harness", {})),
            command_counts=dict(data.get("command_counts", {})),
            written_at=data.get("written_at"),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": CELL_SCHEMA_VERSION,
            "identity": self.identity.to_json(),
            "status": self.status,
            "error": self.error,
            "solved": self.solved,
            "rewards": self.rewards,
            "usage": self.usage,
            "timing": self.timing,
            "agent_version": self.agent_version,
            "harness": self.harness,
            "command_counts": self.command_counts,
            "written_at": self.written_at,
        }
