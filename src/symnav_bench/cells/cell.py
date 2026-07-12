from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from symnav_bench.cell_identity import CellIdentity
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
        from symnav_bench.cells.legacy import load_v1_cell

        return load_v1_cell(cell_json)

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
