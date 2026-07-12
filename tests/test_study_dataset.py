from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from symnav_bench.report.study_dataset import StudyDataset


PROTOCOL = {
    "deep_swe_sha": "a" * 40,
    "symnav": {
        "sha": "b" * 40,
        "kind": "main",
        "evaluation_sequence": 1,
        "base_ref": "main",
        "base_sha": "b" * 40,
        "pull_request": None,
    },
    "repetitions": 4,
    "wall_clock_seconds": 9_000,
    "randomization_seed": 42,
    "conditions": ["stock", "symnav"],
    "scoring_policy": "deepswe-pass-fraction-v1",
    "practical_uplift_points": 5.0,
}
PROTOCOL_FINGERPRINT = "1" * 64
SUITE_FINGERPRINT = "2" * 64
TASK_CHECKSUM = "3" * 64
BUNDLE_HASH = "4" * 64


@pytest.mark.parametrize(
    ("mismatch", "reason"),
    [
        ("study_id", "study ID"),
        ("protocol_fingerprint", "protocol fingerprint"),
        ("suite_fingerprint", "suite fingerprint"),
        ("task_checksum", "task checksum"),
        ("configuration", "configuration"),
        ("bundle_hash", "condition bundle hash"),
        ("agent_version", "agent version"),
        ("slot_identity", "slot identity"),
    ],
)
def test_rejects_attempts_with_named_compatibility_reason(
    tmp_path: Path,
    mismatch: str,
    reason: str,
) -> None:
    study_dir = write_study_directory(tmp_path)
    attempt = attempt_mapping("stock", 1, "attempt-1", "passed")
    mutate_mismatch(attempt, mismatch)
    write_attempt(study_dir, "batch-1", attempt)

    dataset = StudyDataset.load(study_dir)

    assert dataset.slots[0].scored_attempt is None
    assert any(reason in warning for warning in dataset.warnings)


def test_combines_batches_but_never_combines_other_studies(tmp_path: Path) -> None:
    study_dir = write_study_directory(tmp_path)
    write_attempt(
        study_dir,
        "batch-1",
        attempt_mapping("stock", 1, "attempt-stock", "passed"),
    )
    write_attempt(
        study_dir,
        "batch-2",
        attempt_mapping("symnav", 1, "attempt-symnav", "passed"),
    )
    other_study = attempt_mapping("stock", 2, "attempt-other", "passed")
    other_study["slot"]["study_id"] = "another-study"
    write_attempt(study_dir, "batch-3", other_study)

    dataset = StudyDataset.load(study_dir)

    scored = [result.scored_attempt for result in dataset.slots if result.scored_attempt]
    assert [attempt.identity.attempt_id for attempt in scored] == [
        "attempt-stock",
        "attempt-symnav",
    ]
    assert any("study ID" in warning for warning in dataset.warnings)


def test_keeps_retryable_history_and_selects_first_scored_attempt(tmp_path: Path) -> None:
    study_dir = write_study_directory(tmp_path)
    for batch, attempt_id, outcome, written_at in [
        ("batch-1", "retry", "retryable_error", "2026-01-01T00:00:00+00:00"),
        ("batch-2", "first", "failed", "2026-01-01T00:00:01+00:00"),
        ("batch-3", "later", "passed", "2026-01-01T00:00:02+00:00"),
    ]:
        attempt = attempt_mapping("stock", 1, attempt_id, outcome)
        attempt["written_at"] = written_at
        write_attempt(study_dir, batch, attempt)

    result = StudyDataset.load(study_dir).slots[0]

    assert [attempt.identity.attempt_id for attempt in result.attempts] == [
        "retry",
        "first",
        "later",
    ]
    assert result.scored_attempt is not None
    assert result.scored_attempt.identity.attempt_id == "first"


def write_study_directory(path: Path) -> Path:
    protocol = copy.deepcopy(PROTOCOL)
    protocol_fingerprint = fingerprint(protocol)
    study = {
        "schema_version": 1,
        "id": "study",
        "protocol_fingerprint": protocol_fingerprint,
        "protocol": protocol,
        "configurations": [
            {
                "id": "configuration",
                "agent": "codex",
                "model": "model",
                "effort": "medium",
                "agent_version": "0.31.0",
            }
        ],
    }
    path.mkdir(parents=True, exist_ok=True)
    (path / "study.yaml").write_text(
        yaml.safe_dump(study, sort_keys=False),
        encoding="utf-8",
    )
    suite = {
        "deep_swe_sha": "a" * 40,
        "fingerprint": SUITE_FINGERPRINT,
        "tasks": [
            {"slug": "task", "language": "typescript", "checksum": TASK_CHECKSUM}
        ],
    }
    (path / "suite.json").write_text(json.dumps(suite), encoding="utf-8")
    return path


def attempt_mapping(
    condition: str,
    repetition: int,
    attempt_id: str,
    outcome: str,
) -> dict:
    slot_id = slot_identity(condition, repetition)
    return {
        "schema_version": 3,
        "identity": {
            "slot_id": slot_id,
            "attempt_id": attempt_id,
            "github_run_id": None,
            "github_run_attempt": None,
            "github_job": None,
        },
        "slot": {
            "study_id": "study",
            "configuration_id": "configuration",
            "condition": condition,
            "task": "task",
            "repetition": repetition,
            "slot_id": slot_id,
        },
        "disposition": {
            "outcome": outcome,
            "scored_failure_reason": "verifier" if outcome == "failed" else None,
            "retry_reason": "provider" if outcome == "retryable_error" else None,
            "detail": None,
        },
        "rewards": {"f2p": 1.0 if outcome == "passed" else 0.0, "p2p": 1.0},
        "usage": {"cost_usd_imputed": 1.0, "n_agent_steps": 2, "n_output_tokens": 3},
        "timing": {"duration_seconds": 4.0},
        "agent_version": "0.31.0",
        "harness": {
            "image_reference": "image",
            "image_digest": "sha256:image",
            "symnav_bench_sha": "5" * 40,
            "pier_version": "0.3.0",
            "deep_swe_sha": "a" * 40,
            "symnav_sha": None if condition == "stock" else "b" * 40,
            "agent_name": "codex",
            "agent_version": "0.31.0",
            "bundle_id": None if condition == "stock" else "full",
            "bundle_hash": None if condition == "stock" else BUNDLE_HASH,
            "task_checksum": TASK_CHECKSUM,
            "prompt_rule_hash": "6" * 64,
            "requested_model": "model",
            "requested_effort": "medium",
        },
        "exception": None,
        "command_counts": {},
        "adoption": {
            "used_symnav": condition == "symnav",
            "read_symnav_skill": condition == "symnav",
            "symnav_calls": 1 if condition == "symnav" else 0,
            "symnav_calls_per_agent_step": 0.5 if condition == "symnav" else 0.0,
            "symnav_failures": 0,
            "symnav_timeouts": 0,
            "first_symnav_step": 1 if condition == "symnav" else None,
            "search_calls": 1,
            "read_calls": 2,
            "patch_calls": 1,
            "command_counts": {"overview": 1} if condition == "symnav" else {},
        },
        "written_at": "2026-01-01T00:00:00+00:00",
        "protocol_fingerprint": fingerprint(PROTOCOL),
        "suite_fingerprint": SUITE_FINGERPRINT,
    }


def write_attempt(study_dir: Path, batch: str, attempt: dict) -> None:
    path = (
        study_dir
        / "attempts"
        / batch
        / attempt["slot"]["slot_id"]
        / "attempts"
        / attempt["identity"]["attempt_id"]
        / "attempt.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(attempt), encoding="utf-8")


def mutate_mismatch(attempt: dict, mismatch: str) -> None:
    if mismatch == "study_id":
        attempt["slot"]["study_id"] = "other"
    elif mismatch == "protocol_fingerprint":
        attempt["protocol_fingerprint"] = "f" * 64
    elif mismatch == "suite_fingerprint":
        attempt["suite_fingerprint"] = "f" * 64
    elif mismatch == "task_checksum":
        attempt["harness"]["task_checksum"] = "f" * 64
    elif mismatch == "configuration":
        attempt["harness"]["requested_model"] = "other-model"
    elif mismatch == "bundle_hash":
        attempt["slot"]["condition"] = "symnav"
        attempt["harness"]["symnav_sha"] = "b" * 40
        attempt["harness"]["bundle_hash"] = None
    elif mismatch == "agent_version":
        attempt["agent_version"] = "0.30.0"
    elif mismatch == "slot_identity":
        attempt["identity"]["slot_id"] = "other-slot"


def slot_identity(condition: str, repetition: int) -> str:
    value = {
        "study_id": "study",
        "configuration_id": "configuration",
        "condition": condition,
        "task": "task",
        "repetition": repetition,
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def fingerprint(value: dict) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
