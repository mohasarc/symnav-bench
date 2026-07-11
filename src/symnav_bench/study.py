from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from symnav_bench.run_spec import AgentSpec


AgentName = Literal["claude", "codex"]
ConditionName = Literal[
    "stock",
    "symnav",
    "overview",
    "resolve",
    "def",
    "refs",
    "context",
    "graph",
    "overview-refs",
    "overview-context",
    "overview-def",
    "overview-graph",
    "resolve-graph",
]
SymnavRevisionKind = Literal["main", "pull_request"]


@dataclass(frozen=True)
class AgentConfiguration:
    id: str
    spec: AgentSpec
    agent_version: str


@dataclass(frozen=True)
class SymnavRevision:
    sha: str
    kind: SymnavRevisionKind
    evaluation_sequence: int
    base_ref: str
    base_sha: str
    pull_request: int | None


@dataclass(frozen=True)
class StudyProtocol:
    deep_swe_sha: str
    symnav: SymnavRevision
    repetitions: int
    wall_clock_seconds: int
    randomization_seed: int
    conditions: tuple[ConditionName, ...]
    scoring_policy: str
    practical_uplift_points: float


@dataclass(frozen=True)
class StudyManifest:
    schema_version: int
    id: str
    protocol: StudyProtocol
    configurations: tuple[AgentConfiguration, ...]

    @classmethod
    def load(cls, path: Path) -> StudyManifest:
        raise NotImplementedError

    def protocol_fingerprint(self) -> str:
        raise NotImplementedError
