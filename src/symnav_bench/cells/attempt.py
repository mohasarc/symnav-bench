from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from symnav_bench.batch_plan import TrialSlot
from symnav_bench.run.job_config import HarnessIdentity


ATTEMPT_SCHEMA_VERSION = 2
AttemptOutcome = Literal["passed", "failed", "retryable_error"]
ScoredFailureReason = Literal["verifier", "context_window", "agent_timeout"]
RetryReason = Literal[
    "provider",
    "quota",
    "network",
    "verifier",
    "agent_process",
    "runner",
    "unknown",
]


@dataclass(frozen=True)
class AttemptIdentity:
    slot_id: str
    attempt_id: str
    github_run_id: str | None
    github_run_attempt: int | None
    github_job: str | None


@dataclass(frozen=True)
class AttemptDisposition:
    outcome: AttemptOutcome
    scored_failure_reason: ScoredFailureReason | None
    retry_reason: RetryReason | None
    detail: str | None


@dataclass(frozen=True)
class AttemptRecord:
    schema_version: int
    identity: AttemptIdentity
    slot: TrialSlot
    disposition: AttemptDisposition
    rewards: dict[str, Any]
    usage: dict[str, Any]
    timing: dict[str, Any]
    agent_version: str | None
    harness: HarnessIdentity
    exception: dict[str, Any] | None
    command_counts: dict[str, Any]
    written_at: str

    @classmethod
    def load(cls, path: Path) -> "AttemptRecord":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            schema_version=int(data["schema_version"]),
            identity=AttemptIdentity(**data["identity"]),
            slot=TrialSlot(**data["slot"]),
            disposition=AttemptDisposition(**data["disposition"]),
            rewards=dict(data.get("rewards", {})),
            usage=dict(data.get("usage", {})),
            timing=dict(data.get("timing", {})),
            agent_version=data.get("agent_version"),
            harness=HarnessIdentity(**data["harness"]),
            exception=data.get("exception"),
            command_counts=dict(data.get("command_counts", {})),
            written_at=str(data["written_at"]),
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SlotResult:
    slot: TrialSlot
    scored_attempt: AttemptRecord | None
    attempts: tuple[AttemptRecord, ...]
    warnings: tuple[str, ...]
