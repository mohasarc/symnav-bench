from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.cell import CELL_SCHEMA_VERSION, Cell
from symnav_bench.run_spec import AgentSpec


def load_v1_cell(path: Path) -> Cell:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema_version = data.get("schema_version", CELL_SCHEMA_VERSION)
    if schema_version != CELL_SCHEMA_VERSION:
        raise ValueError(f"unsupported legacy cell schema version {schema_version}")
    return cell_from_v1_mapping(data)


def cell_from_v1_mapping(data: dict[str, Any]) -> Cell:
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
    return Cell(
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
