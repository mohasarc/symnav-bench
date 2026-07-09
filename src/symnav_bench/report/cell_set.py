from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from symnav_bench.cells.cell import Cell


@dataclass(frozen=True)
class ArmKey:
    agent: str
    model: str
    effort: str
    condition_label: str

    @property
    def label(self) -> str:
        return f"{self.agent}:{self.model}:{self.effort}:{self.condition_label}"


@dataclass(frozen=True)
class CellSet:
    cells: list[Cell]
    warnings: tuple[str, ...] = ()

    @classmethod
    def load(cls, cells_dir: Path) -> "CellSet":
        by_identity: dict[tuple[str, str, str, str, int], Cell] = {}
        warnings: list[str] = []
        for path in sorted(cells_dir.glob("*/cell.json"), key=lambda item: item.stat().st_mtime):
            cell = Cell.load(path)
            key = (
                cell.identity.spec.key,
                cell.identity.condition_label,
                cell.identity.task,
                str(cell.identity.rep),
                0,
            )
            if key in by_identity:
                warnings.append(f"duplicate cell identity; latest wins: {cell.identity.dirname()}")
            p2p = cell.rewards.get("p2p")
            if cell.solved and isinstance(p2p, (int, float)) and p2p < 1.0:
                warnings.append(f"{cell.identity.dirname()} has f2p=1.0 but p2p={p2p}")
            by_identity[key] = cell
        return cls(cells=list(by_identity.values()), warnings=tuple(warnings))

    def arms(self) -> dict[ArmKey, list[Cell]]:
        groups: dict[ArmKey, list[Cell]] = {}
        for cell in self.cells:
            key = ArmKey(
                agent=cell.identity.spec.agent,
                model=cell.identity.spec.model,
                effort=cell.identity.spec.effort,
                condition_label=cell.identity.condition_label,
            )
            groups.setdefault(key, []).append(cell)
        return groups
