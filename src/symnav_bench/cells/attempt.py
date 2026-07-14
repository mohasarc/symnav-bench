from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, cast

from symnav_bench.batch_plan import TrialSlot
from symnav_bench.cells.trajectory import AdoptionSummary
from symnav_bench.run.job_config import HarnessIdentity


ATTEMPT_SCHEMA_VERSION = 3
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
class AttemptArtifact:
    archive: str
    internal_path: str
    sha256: str


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
    adoption: AdoptionSummary
    written_at: str
    artifact: AttemptArtifact | None = None

    @classmethod
    def load(cls, path: Path) -> "AttemptRecord":
        data = json.loads(path.read_text(encoding="utf-8"))
        rewards = dict(data.get("rewards", {}))
        disposition = _canonical_disposition(
            AttemptDisposition(**data["disposition"]),
            rewards,
            data.get("exception"),
        )
        return cls(
            schema_version=int(data["schema_version"]),
            identity=AttemptIdentity(**data["identity"]),
            slot=TrialSlot(**data["slot"]),
            disposition=disposition,
            rewards=rewards,
            usage=dict(data.get("usage", {})),
            timing=dict(data.get("timing", {})),
            agent_version=data.get("agent_version"),
            harness=HarnessIdentity(**data["harness"]),
            exception=data.get("exception"),
            command_counts=dict(data.get("command_counts", {})),
            adoption=_load_adoption(data.get("adoption")),
            written_at=str(data["written_at"]),
            artifact=(
                AttemptArtifact(**data["artifact"])
                if isinstance(data.get("artifact"), Mapping)
                else None
            ),
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _load_adoption(value: Any) -> AdoptionSummary:
    if isinstance(value, Mapping):
        return AdoptionSummary(
            used_symnav=bool(value.get("used_symnav", False)),
            read_symnav_skill=bool(value.get("read_symnav_skill", False)),
            symnav_calls=int(value.get("symnav_calls", 0)),
            symnav_calls_per_agent_step=float(value.get("symnav_calls_per_agent_step", 0.0)),
            symnav_failures=int(value.get("symnav_failures", 0)),
            symnav_timeouts=int(value.get("symnav_timeouts", 0)),
            first_symnav_step=(
                int(value["first_symnav_step"])
                if value.get("first_symnav_step") is not None
                else None
            ),
            search_calls=int(value.get("search_calls", 0)),
            read_calls=int(value.get("read_calls", 0)),
            patch_calls=int(value.get("patch_calls", 0)),
            command_counts={
                str(command): int(count)
                for command, count in _mapping(value.get("command_counts")).items()
            },
        )
    return AdoptionSummary(False, False, 0, 0.0, 0, 0, None, 0, 0, 0, {})


def _mapping(value: Any) -> Mapping[Any, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class SlotResult:
    slot: TrialSlot
    scored_attempt: AttemptRecord | None
    attempts: tuple[AttemptRecord, ...]
    warnings: tuple[str, ...]


def select_slot_result(
    slot: TrialSlot,
    attempts: Sequence[AttemptRecord],
) -> SlotResult:
    mismatched = [attempt.identity.attempt_id for attempt in attempts if attempt.slot.slot_id != slot.slot_id]
    if mismatched:
        raise ValueError(f"attempts do not belong to slot {slot.slot_id}: {', '.join(mismatched)}")
    ordered = tuple(sorted(attempts, key=lambda attempt: (attempt.written_at, attempt.identity.attempt_id)))
    scored = [attempt for attempt in ordered if attempt.disposition.outcome != "retryable_error"]
    selected = scored[0] if scored else None
    warnings = ()
    if selected is not None and len(scored) > 1:
        warnings = tuple(
            f"slot {slot.slot_id} has multiple scored attempts; "
            f"keeping {selected.identity.attempt_id} and ignoring {duplicate.identity.attempt_id}"
            for duplicate in scored[1:]
        )
    return SlotResult(
        slot=slot,
        scored_attempt=selected,
        attempts=ordered,
        warnings=warnings,
    )


def classify_attempt(
    result: Mapping[str, Any],
    pier_error: Exception | None,
) -> AttemptDisposition:
    rewards = _verifier_rewards(result)
    if rewards and all(_is_full_reward(value) for value in rewards.values()):
        return AttemptDisposition("passed", None, None, None)

    exception = _exception_detail(result, pier_error)
    normalized = " ".join(exception.values()).lower()
    detail = ": ".join(value for value in exception.values() if value) or "missing verifier reward"
    if _contains(normalized, "contextwindow", "context window", "context_length", "token limit"):
        return AttemptDisposition("failed", "context_window", None, detail)
    if _contains(normalized, "agenttimeout", "agent timeout", "agent timed out"):
        return AttemptDisposition("failed", "agent_timeout", None, detail)

    if _has_recorded_exception(result, pier_error):
        reason = _retry_reason(normalized, pier_error is not None)
        return AttemptDisposition("retryable_error", None, reason, detail)

    if rewards:
        return AttemptDisposition("failed", "verifier", None, detail)

    reason = _retry_reason(normalized, pier_error is not None)
    return AttemptDisposition("retryable_error", None, reason, detail)


def _has_recorded_exception(
    result: Mapping[str, Any],
    pier_error: Exception | None,
) -> bool:
    if pier_error is not None:
        return True
    info = result.get("exception_info")
    return bool(info) if isinstance(info, (Mapping, str)) else False


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
    nested_reward = rewards.get("reward")
    if isinstance(nested_reward, (int, float)) and not isinstance(nested_reward, bool):
        return {"reward": nested_reward}
    return {str(key): value for key, value in rewards.items()}


def _canonical_disposition(
    disposition: AttemptDisposition,
    rewards: Mapping[str, Any],
    exception: Any = None,
) -> AttemptDisposition:
    reward = rewards.get("reward")
    reward_is_number = isinstance(reward, (int, float)) and not isinstance(reward, bool)
    if reward_is_number and reward == 1.0:
        return AttemptDisposition("passed", None, None, disposition.detail)
    if disposition.outcome != "retryable_error":
        demoted = _crash_retry_disposition(exception, disposition.detail)
        if demoted is not None:
            return demoted
    if disposition.scored_failure_reason == "verifier" and reward_is_number:
        return AttemptDisposition("failed", "verifier", None, disposition.detail)
    return disposition


def _crash_retry_disposition(
    exception: Any,
    detail: str | None,
) -> AttemptDisposition | None:
    if not isinstance(exception, Mapping):
        return None
    text = " ".join(
        str(value)
        for value in (
            exception.get("exception_type"),
            exception.get("type"),
            exception.get("name"),
            exception.get("message"),
            exception.get("detail"),
            exception.get("exception_message"),
        )
        if value
    ).lower()
    if not text:
        return None
    if _contains(text, "contextwindow", "context window", "context_length", "token limit"):
        return None
    if _contains(text, "agenttimeout", "agent timeout", "agent timed out"):
        return None
    return AttemptDisposition("retryable_error", None, _retry_reason(text, False), detail)


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
            "message": str(
                info.get("message")
                or info.get("detail")
                or info.get("exception_message")
                or ""
            ),
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
        "usage limit",
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
