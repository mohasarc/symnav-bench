from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, cast

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


def classify_attempt(
    result: Mapping[str, Any],
    pier_error: Exception | None,
) -> AttemptDisposition:
    rewards = _verifier_rewards(result)
    if rewards:
        passed = all(_is_full_reward(value) for value in rewards.values())
        return AttemptDisposition(
            outcome="passed" if passed else "failed",
            scored_failure_reason=None if passed else "verifier",
            retry_reason=None,
            detail=None,
        )

    exception = _exception_detail(result, pier_error)
    normalized = " ".join(exception.values()).lower()
    detail = ": ".join(value for value in exception.values() if value) or "missing verifier reward"
    if _contains(normalized, "contextwindow", "context window", "context_length", "token limit"):
        return AttemptDisposition("failed", "context_window", None, detail)
    if _contains(normalized, "agenttimeout", "agent timeout", "agent timed out"):
        return AttemptDisposition("failed", "agent_timeout", None, detail)

    reason = _retry_reason(normalized, pier_error is not None)
    return AttemptDisposition("retryable_error", None, reason, detail)


def _verifier_rewards(result: Mapping[str, Any]) -> dict[str, Any]:
    verifier = result.get("verifier_result")
    if not isinstance(verifier, Mapping):
        return {}
    reward = verifier.get("reward")
    if isinstance(reward, (int, float)) and not isinstance(reward, bool):
        return {"reward": reward}
    rewards = verifier.get("rewards")
    if not isinstance(rewards, Mapping):
        return {}
    return {str(key): value for key, value in rewards.items()}


def _is_full_reward(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 1.0


def _exception_detail(
    result: Mapping[str, Any],
    pier_error: Exception | None,
) -> dict[str, str]:
    info = result.get("exception_info")
    if isinstance(info, Mapping):
        return {
            "type": str(
                info.get("exception_type")
                or info.get("type")
                or info.get("name")
                or ""
            ),
            "message": str(info.get("message") or info.get("detail") or ""),
        }
    if isinstance(info, str):
        return {"type": "", "message": info}
    if pier_error is not None:
        return {"type": type(pier_error).__name__, "message": str(pier_error)}
    return {"type": "", "message": "missing verifier reward"}


def _retry_reason(normalized: str, has_pier_error: bool) -> RetryReason:
    if _contains(
        normalized,
        "usagelimit",
        "rate limit",
        "ratelimit",
        "quota",
        "limit reached",
        "too many requests",
    ):
        return "quota"
    if _contains(
        normalized,
        "provider",
        "model unavailable",
        "modelunavailable",
        "apierror",
        "authentication",
        "service unavailable",
        "overloaded",
        "outage",
    ):
        return "provider"
    if _contains(normalized, "network", "connection", "connecterror", "dns", "socket"):
        return "network"
    if _contains(normalized, "verifier", "grading", "grader"):
        return "verifier"
    if _contains(
        normalized,
        "nonzeroagentexit",
        "agent process",
        "agentprocess",
        "agent exited",
        "agent crash",
    ):
        return "agent_process"
    if _contains(normalized, "runner", "pier") or has_pier_error:
        return "runner"
    return cast(RetryReason, "unknown")


def _contains(value: str, *needles: str) -> bool:
    return any(needle in value for needle in needles)
