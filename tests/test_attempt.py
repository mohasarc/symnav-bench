from __future__ import annotations

import pytest

from symnav_bench.cells.attempt import classify_attempt


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
