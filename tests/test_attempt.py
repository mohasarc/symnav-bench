from __future__ import annotations

import pytest

from symnav_bench.batch_plan import TrialSlot
from symnav_bench.cells.attempt import (
    ATTEMPT_SCHEMA_VERSION,
    AttemptArtifact,
    AttemptDisposition,
    AttemptIdentity,
    AttemptRecord,
    classify_attempt,
    select_slot_result,
)
from symnav_bench.cells.trajectory import AdoptionSummary
from symnav_bench.run.job_config import HarnessIdentity


def test_binary_verifier_reward_defines_pass_or_failure() -> None:
    assert classify_attempt(_result({"f2p": 1.0, "p2p": 1.0}), None).outcome == "passed"

    failed = classify_attempt(_result({"f2p": 1.0, "p2p": 0.5}), None)

    assert failed.outcome == "failed"
    assert failed.scored_failure_reason == "verifier"


def test_verifier_reward_wins_over_agent_exit_exception() -> None:
    disposition = classify_attempt(
        _result({"f2p": 1.0, "p2p": 1.0}, "NonZeroAgentExitCodeError"),
        RuntimeError("pier exited nonzero"),
    )

    assert disposition.outcome == "passed"
    assert disposition.retry_reason is None


@pytest.mark.parametrize("exception_type", ["ContextWindowExceededError", "AgentTimeoutError"])
def test_expected_agent_limits_are_scored_failures(exception_type: str) -> None:
    disposition = classify_attempt(_result(exception_type=exception_type), None)

    assert disposition.outcome == "failed"
    assert disposition.scored_failure_reason in {"context_window", "agent_timeout"}


@pytest.mark.parametrize(
    ("exception_type", "reason"),
    [
        ("ProviderError", "provider"),
        ("UsageLimitError", "quota"),
        ("NetworkError", "network"),
        ("VerifierTimeoutError", "verifier"),
        ("NonZeroAgentExitCodeError", "agent_process"),
        ("RunnerError", "runner"),
        ("UnexpectedThing", "unknown"),
    ],
)
def test_missing_reward_infrastructure_errors_are_retryable(
    exception_type: str,
    reason: str,
) -> None:
    disposition = classify_attempt(_result(exception_type=exception_type), None)

    assert disposition.outcome == "retryable_error"
    assert disposition.retry_reason == reason


def test_trial_presence_does_not_override_structured_exception() -> None:
    disposition = classify_attempt(
        {
            "agent_result": {"n_agent_steps": 1},
            "exception_info": {"exception_type": "UsageLimitError", "message": "limit reached"},
        },
        None,
    )

    assert disposition.outcome == "retryable_error"
    assert disposition.retry_reason == "quota"


def test_slot_selects_first_scored_attempt_and_keeps_retry_history() -> None:
    slot = _slot()
    retry = _attempt(slot, "attempt-1", "retryable_error")
    first_scored = _attempt(slot, "attempt-2", "failed")
    duplicate_scored = _attempt(slot, "attempt-3", "passed")

    result = select_slot_result(slot, [duplicate_scored, first_scored, retry])

    assert result.attempts == (retry, first_scored, duplicate_scored)
    assert result.scored_attempt == first_scored
    assert result.warnings == (
        f"slot {slot.slot_id} has multiple scored attempts; keeping attempt-2 and ignoring attempt-3",
    )


def test_missing_slot_stays_unresolved() -> None:
    result = select_slot_result(_slot(), [])

    assert result.scored_attempt is None
    assert result.attempts == ()
    assert result.warnings == ()


def test_load_preserves_workflow_artifact_pointer(tmp_path) -> None:
    attempt = _attempt(_slot(), "attempt-1", "passed")
    value = attempt.to_json()
    value["artifact"] = {
        "archive": "https://example.test/batch.tar.gz",
        "internal_path": "attempts/attempt-1",
        "sha256": "a" * 64,
    }
    path = tmp_path / "attempt.json"
    path.write_text(__import__("json").dumps(value), encoding="utf-8")

    loaded = AttemptRecord.load(path)

    assert loaded.artifact == AttemptArtifact(
        "https://example.test/batch.tar.gz",
        "attempts/attempt-1",
        "a" * 64,
    )
    assert loaded.to_json()["artifact"] == value["artifact"]


def _result(
    rewards: dict[str, float] | None = None,
    exception_type: str | None = None,
) -> dict:
    result = {}
    if rewards is not None:
        result["verifier_result"] = {"rewards": rewards}
    if exception_type is not None:
        result["exception_info"] = {
            "exception_type": exception_type,
            "message": exception_type,
        }
    return result


def _slot() -> TrialSlot:
    return TrialSlot("study", "configuration", "stock", "task", 1, "slot-1")


def _attempt(slot: TrialSlot, attempt_id: str, outcome: str) -> AttemptRecord:
    return AttemptRecord(
        schema_version=ATTEMPT_SCHEMA_VERSION,
        identity=AttemptIdentity(slot.slot_id, attempt_id, None, None, None),
        slot=slot,
        disposition=AttemptDisposition(
            outcome=outcome,
            scored_failure_reason="verifier" if outcome == "failed" else None,
            retry_reason="unknown" if outcome == "retryable_error" else None,
            detail=None,
        ),
        rewards={},
        usage={},
        timing={},
        agent_version=None,
        harness=HarnessIdentity(
            "image",
            "sha256:image",
            "a" * 40,
            "0.3.0",
            "b" * 40,
            None,
            "codex",
            "0.31.0",
            None,
            None,
            "c" * 64,
            "d" * 64,
            "model",
            "medium",
        ),
        exception=None,
        command_counts={},
        adoption=AdoptionSummary(False, False, 0, 0.0, 0, 0, None, 0, 0, 0, {}),
        written_at=f"2026-01-01T00:00:0{attempt_id[-1]}+00:00",
    )
