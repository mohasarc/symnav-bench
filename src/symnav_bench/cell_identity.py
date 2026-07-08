from __future__ import annotations

from dataclasses import dataclass

from symnav_bench.run_spec import AgentSpec


@dataclass(frozen=True)
class CellIdentity:
    spec: AgentSpec
    condition_label: str
    task: str
    rep: int

    def dirname(self) -> str:
        return f"{self.spec.key}-{self.condition_label}-{self.task}-rep{self.rep}"

    def to_json(self) -> dict[str, object]:
        return {
            "agent": self.spec.agent,
            "model": self.spec.model,
            "effort": self.spec.effort,
            "condition": self.condition_label,
            "task": self.task,
            "rep": self.rep,
            "dirname": self.dirname(),
        }
