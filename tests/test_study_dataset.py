from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from symnav_bench.report.study_dataset import StudyDataset
from symnav_bench.report.study_dataset import compute_configuration_metrics
from symnav_bench.report.render import write_report


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


def test_primary_coverage_and_binary_score_require_four_trials_in_both_conditions(
    tmp_path: Path,
) -> None:
    study_dir = write_study_directory(tmp_path, tasks=("task-a", "task-b"))
    outcomes = {
        "task-a": ["passed", "passed", "passed", "failed"],
        "task-b": ["passed", "failed", "failed", "failed"],
    }
    write_metric_attempts(study_dir, outcomes, outcomes)

    dataset = StudyDataset.load(study_dir)
    stock_key = next(key for key in dataset.configurations() if key.condition == "stock")
    metrics = compute_configuration_metrics(dataset, stock_key)

    assert metrics.coverage.complete_tasks == 2
    assert metrics.coverage.total_tasks == 2
    assert metrics.coverage.provisional is False
    assert metrics.coverage.pilot is False
    assert [task.pass_fraction for task in metrics.tasks] == [0.75, 0.25]
    assert metrics.performance_score == 0.5
    assert metrics.repetition_scores == (1.0, 0.5, 0.5, 0.0)
    assert sum(metrics.repetition_scores) / 4 == metrics.performance_score


def test_incomplete_tasks_are_provisional_pilots_and_do_not_become_zero(
    tmp_path: Path,
) -> None:
    study_dir = write_study_directory(tmp_path, tasks=("task-a", "task-b"))
    stock = {
        "task-a": ["passed", "passed", "passed", "failed"],
        "task-b": ["failed", "failed", "failed"],
    }
    symnav = {
        "task-a": ["passed", "passed", "passed", "failed"],
        "task-b": ["failed", "failed", "failed", "failed"],
    }
    write_metric_attempts(study_dir, stock, symnav)

    dataset = StudyDataset.load(study_dir)
    stock_key = next(key for key in dataset.configurations() if key.condition == "stock")
    metrics = compute_configuration_metrics(dataset, stock_key)

    assert metrics.coverage.complete_tasks == 1
    assert metrics.coverage.provisional is True
    assert metrics.coverage.pilot is True
    assert len(metrics.coverage.unresolved_slot_ids) == 1
    assert metrics.performance_score == 0.75
    assert metrics.repetition_scores == (1.0, 1.0, 1.0, 0.0)


def test_partial_rewards_are_averaged_within_task_then_across_tasks(
    tmp_path: Path,
) -> None:
    study_dir = write_study_directory(tmp_path, tasks=("task-a", "task-b"))
    outcomes = {
        "task-a": ["passed"] * 4,
        "task-b": ["failed"] * 4,
    }
    write_metric_attempts(study_dir, outcomes, outcomes)
    for path in study_dir.glob("**/attempt.json"):
        attempt = json.loads(path.read_text(encoding="utf-8"))
        if attempt["slot"]["condition"] != "stock":
            continue
        if attempt["slot"]["task"] == "task-a":
            attempt["rewards"] = {"f2p": 1.0, "p2p": 0.8, "partial": 0.6}
        elif attempt["slot"]["repetition"] == 1:
            attempt["rewards"] = {"f2p": 0.0, "p2p": 0.2, "partial": 0.4}
        else:
            attempt["rewards"] = {}
        path.write_text(json.dumps(attempt), encoding="utf-8")

    dataset = StudyDataset.load(study_dir)
    stock_key = next(key for key in dataset.configurations() if key.condition == "stock")
    metrics = compute_configuration_metrics(dataset, stock_key)

    assert metrics.mean_f2p == 0.5
    assert metrics.mean_p2p == 0.5
    assert metrics.mean_partial == 0.5


def test_efficiency_includes_failed_trials_and_preserves_distributions(
    tmp_path: Path,
) -> None:
    study_dir = write_study_directory(tmp_path, tasks=("task-a", "task-b"))
    stock = {
        "task-a": ["passed"] * 4,
        "task-b": ["failed"] * 4,
    }
    write_metric_attempts(study_dir, stock, stock)
    costs = {
        "task-a": [1.0, 2.0, 3.0, 4.0],
        "task-b": [10.0, 20.0, 30.0, 40.0],
    }
    for path in study_dir.glob("**/attempt.json"):
        attempt = json.loads(path.read_text(encoding="utf-8"))
        if attempt["slot"]["condition"] != "stock":
            continue
        task = attempt["slot"]["task"]
        repetition = attempt["slot"]["repetition"]
        cost = costs[task][repetition - 1]
        attempt["usage"] = {
            "cost_usd_imputed": cost,
            "n_output_tokens": cost * 10,
            "n_agent_steps": cost * 2,
        }
        attempt["timing"] = {"duration_seconds": cost * 3}
        path.write_text(json.dumps(attempt), encoding="utf-8")

    dataset = StudyDataset.load(study_dir)
    stock_key = next(key for key in dataset.configurations() if key.condition == "stock")
    metrics = compute_configuration_metrics(dataset, stock_key)

    task_a, task_b = metrics.tasks
    assert (task_a.mean_cost, task_a.median_cost) == (2.5, 2.5)
    assert (task_b.mean_cost, task_b.median_cost) == (25.0, 25.0)
    assert task_b.mean_output_tokens == 250.0
    assert task_b.mean_steps == 50.0
    assert task_b.mean_duration_seconds == 75.0
    assert metrics.total_cost == 110.0
    assert metrics.cost_per_success == 27.5


def test_adoption_uses_trial_rates_and_task_macro_means(tmp_path: Path) -> None:
    study_dir = write_study_directory(tmp_path, tasks=("task-a", "task-b"))
    stock = {
        "task-a": ["passed"] * 4,
        "task-b": ["passed"],
    }
    symnav = {
        "task-a": ["passed"] * 4,
        "task-b": ["passed"] * 4,
    }
    write_metric_attempts(study_dir, stock, symnav)
    for path in study_dir.glob("**/attempt.json"):
        attempt = json.loads(path.read_text(encoding="utf-8"))
        if attempt["slot"]["condition"] != "stock":
            continue
        task = attempt["slot"]["task"]
        repetition = attempt["slot"]["repetition"]
        used = task == "task-b" or repetition == 1
        calls = 8 if task == "task-b" else (4 if used else 0)
        attempt["adoption"].update(
            {
                "used_symnav": used,
                "read_symnav_skill": used,
                "symnav_calls": calls,
                "symnav_calls_per_agent_step": calls / 4,
                "first_symnav_step": 2 if used else None,
                "command_counts": {"overview": calls},
            }
        )
        path.write_text(json.dumps(attempt), encoding="utf-8")

    dataset = StudyDataset.load(study_dir)
    stock_key = next(key for key in dataset.configurations() if key.condition == "stock")
    metrics = compute_configuration_metrics(dataset, stock_key)

    task_a, task_b = metrics.tasks
    assert task_a.adoption is not None
    assert task_a.adoption.used_symnav_rate == 0.25
    assert task_a.adoption.mean_symnav_calls == 1.0
    assert task_b.adoption is not None
    assert task_b.adoption.used_symnav_rate == 1.0
    assert task_b.adoption.mean_symnav_calls == 8.0
    assert metrics.adoption is not None
    assert metrics.adoption.used_symnav_rate == 0.625
    assert metrics.adoption.mean_symnav_calls == 4.5
    assert metrics.adoption.mean_command_counts == {"overview": 4.5}


def test_study_report_exports_compatible_metrics_without_legacy_data(
    tmp_path: Path,
) -> None:
    study_dir = write_study_directory(tmp_path / "study")
    outcomes = {"task": ["passed"] * 4}
    write_metric_attempts(study_dir, outcomes, outcomes)

    write_report(StudyDataset.load(study_dir), tmp_path / "report")

    markdown = (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert "Study: `study`" in markdown
    assert "performance score" in markdown
    assert "Legacy" not in markdown
    assert (tmp_path / "report" / "configurations.csv").exists()
    assert (tmp_path / "report" / "tasks.csv").exists()


def write_study_directory(path: Path, tasks: tuple[str, ...] = ("task",)) -> Path:
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
            {"slug": task, "language": "typescript", "checksum": task_checksum(task)}
            for task in tasks
        ],
    }
    (path / "suite.json").write_text(json.dumps(suite), encoding="utf-8")
    return path


def attempt_mapping(
    condition: str,
    repetition: int,
    attempt_id: str,
    outcome: str,
    task: str = "task",
) -> dict:
    slot_id = slot_identity(condition, repetition, task)
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
            "task": task,
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
            "task_checksum": task_checksum(task),
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


def slot_identity(condition: str, repetition: int, task: str = "task") -> str:
    value = {
        "study_id": "study",
        "configuration_id": "configuration",
        "condition": condition,
        "task": task,
        "repetition": repetition,
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def fingerprint(value: dict) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def task_checksum(task: str) -> str:
    return TASK_CHECKSUM if task == "task" else hashlib.sha256(task.encode()).hexdigest()


def write_metric_attempts(
    study_dir: Path,
    stock: dict[str, list[str]],
    symnav: dict[str, list[str]],
) -> None:
    for condition, tasks in (("stock", stock), ("symnav", symnav)):
        for task, outcomes in tasks.items():
            for repetition, outcome in enumerate(outcomes, start=1):
                attempt = attempt_mapping(
                    condition,
                    repetition,
                    f"{condition}-{task}-{repetition}",
                    outcome,
                    task,
                )
                write_attempt(study_dir, "batch-1", attempt)
