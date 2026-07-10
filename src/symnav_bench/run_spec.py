from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast


AgentName = Literal["claude", "codex"]
ConditionKind = Literal["stock", "symnav"]
SymnavSkillVariant = Literal["all", "overview", "resolve", "def", "refs", "context", "graph"]
SYMNAV_SKILL_VARIANTS: tuple[SymnavSkillVariant, ...] = (
    "all",
    "overview",
    "resolve",
    "def",
    "refs",
    "context",
    "graph",
)


@dataclass(frozen=True)
class AgentSpec:
    agent: AgentName
    model: str
    effort: str

    @classmethod
    def parse(cls, spec: str) -> "AgentSpec":
        parts = spec.split(":")
        if len(parts) != 3:
            raise ValueError(f"bad agent spec {spec!r}: expected agent:model:effort")
        agent, model, effort = parts
        if agent not in ("claude", "codex"):
            raise ValueError(f"bad agent spec {spec!r}: unknown agent {agent!r}")
        if not model or not effort:
            raise ValueError(f"bad agent spec {spec!r}: model and effort are required")
        return cls(agent=agent, model=model, effort=effort)

    @property
    def key(self) -> str:
        return f"{self.agent}-{self.model}-{self.effort}"


@dataclass(frozen=True)
class Condition:
    kind: ConditionKind
    symnav_sha: str | None = None
    symnav_skill_variant: SymnavSkillVariant = "all"

    def __post_init__(self) -> None:
        if self.kind == "stock" and self.symnav_sha is not None:
            raise ValueError("stock condition cannot carry a symnav sha")
        if self.kind == "stock" and self.symnav_skill_variant != "all":
            raise ValueError("stock condition cannot carry a symnav skill variant")
        if self.kind == "symnav" and not self.symnav_sha:
            raise ValueError("symnav condition requires a sha")

    @property
    def label(self) -> str:
        if self.kind == "stock":
            return "stock"
        assert self.symnav_sha is not None
        prefix = "symnav" if self.symnav_skill_variant == "all" else f"symnav-{self.symnav_skill_variant}"
        return f"{prefix}@{self.symnav_sha[:12]}"


def parse_conditions(value: str, symnav_sha: str | None) -> list[Condition]:
    conditions: list[Condition] = []
    for raw in value.split(","):
        item = raw.strip()
        if item == "stock":
            conditions.append(Condition("stock"))
        elif item == "symnav":
            conditions.append(Condition("symnav", symnav_sha))
        elif item.startswith("symnav-"):
            variant = item.removeprefix("symnav-")
            if variant == "ref":
                variant = "refs"
            if variant not in SYMNAV_SKILL_VARIANTS or variant == "all":
                raise ValueError(f"unknown condition {item!r}")
            conditions.append(Condition("symnav", symnav_sha, cast(SymnavSkillVariant, variant)))
        else:
            raise ValueError(f"unknown condition {item!r}")
    return conditions
