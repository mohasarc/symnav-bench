from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

from symnav_bench.batch_plan import plan_trial_slots
from symnav_bench.cells.attempt import SlotResult
from symnav_bench.report.study_dataset import StudyDataset
from symnav_bench.run_spec import AgentSpec
from symnav_bench.study import (
    AgentConfiguration,
    BenchmarkSelection,
    StudyManifest,
    StudyProtocol,
    SymnavRevision,
)
from symnav_bench.suite import SuiteManifest, TaskManifestEntry
from symnav_bench.workflow import build_raw_archive, merge_attempt_artifacts, select_batches


def test_run_next_selects_first_pending_balanced_batch() -> None:
    study, suite = study_fixture()

    selection = select_batches(study, suite, None, configuration_id="codex", mode="run-next")

    assert len(selection.batches) == 1
    assert {slot.condition for slot in selection.batches[0].slots} == {"stock", "symnav"}


def test_run_all_selects_every_pending_batch() -> None:
    study, suite = study_fixture(task_count=130)

    selection = select_batches(study, suite, None, configuration_id="codex", mode="run-all")

    assert len(selection.batches) == 2
    assert sum(len(batch.slots) for batch in selection.batches) == 260


def test_resume_skips_batches_without_unresolved_slots() -> None:
    study, suite = study_fixture(task_count=130)
    slots = plan_trial_slots(study, suite)
    completed = {slot.slot_id for slot in slots[:252]}
    dataset = StudyDataset(
        manifest=study,
        suite=suite,
        slots=tuple(
            SlotResult(slot, object() if slot.slot_id in completed else None, (), ())  # type: ignore[arg-type]
            for slot in slots
        ),
        warnings=(),
    )

    selection = select_batches(study, suite, dataset, configuration_id="codex", mode="resume")

    assert len(selection.batches) == 1
    assert all(slot.slot_id not in completed for slot in selection.batches[0].slots)


def test_merge_attempt_artifacts_appends_without_overwriting(tmp_path: Path) -> None:
    study_dir = tmp_path / "study"
    first = write_artifact(tmp_path / "first", "slot-a", "attempt-a")
    second = write_artifact(tmp_path / "second", "slot-a", "attempt-b")

    merged = merge_attempt_artifacts(study_dir, [first, second])

    assert [attempt.identity.attempt_id for attempt in merged] == ["attempt-a", "attempt-b"]
    assert (study_dir / "attempts/slot-a/attempt-a.json").exists()
    assert (study_dir / "attempts/slot-a/attempt-b.json").exists()
    merge_attempt_artifacts(study_dir, [first])
    assert len(list((study_dir / "attempts/slot-a").glob("*.json"))) == 2


def test_merge_attempt_artifacts_accepts_a_rerun_after_archive_pointer_enrichment(tmp_path: Path) -> None:
    study_dir = tmp_path / "study"
    artifact = write_artifact(tmp_path / "artifact", "slot-a", "attempt-a")

    merge_attempt_artifacts(study_dir, [artifact])
    target = study_dir / "attempts/slot-a/attempt-a.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    data["artifact"] = {"archive": "batch.tar.gz", "internal_path": "attempts/attempt-a", "sha256": "a" * 64}
    target.write_text(json.dumps(data), encoding="utf-8")

    merge_attempt_artifacts(study_dir, [artifact])

    assert json.loads(target.read_text(encoding="utf-8"))["artifact"]["archive"] == "batch.tar.gz"


def test_raw_archive_is_deterministic_and_maps_attempts(tmp_path: Path) -> None:
    artifact = write_artifact(tmp_path / "artifact", "slot-a", "attempt-a")
    (artifact / "raw").mkdir()
    (artifact / "raw/evidence.txt").write_text("pier evidence", encoding="utf-8")
    (artifact / "secret.env").write_text("TOKEN=secret", encoding="utf-8")

    pointers = build_raw_archive([artifact], tmp_path / "batch.tar.gz")

    pointer = pointers["attempt-a"]
    assert pointer.sha256 == hashlib.sha256((tmp_path / "batch.tar.gz").read_bytes()).hexdigest()
    with tarfile.open(tmp_path / "batch.tar.gz") as archive:
        names = archive.getnames()
    assert any(name.endswith("raw/evidence.txt") for name in names)
    assert not any(name.endswith("secret.env") for name in names)


def write_artifact(path: Path, slot_id: str, attempt_id: str) -> Path:
    path.mkdir(parents=True)
    data = {
        "schema_version": 3,
        "identity": {"slot_id": slot_id, "attempt_id": attempt_id, "github_run_id": "1", "github_run_attempt": 1, "github_job": "cell"},
        "slot": {"study_id": "study", "configuration_id": "codex", "condition": "stock", "task": "task", "repetition": 1, "slot_id": slot_id},
        "disposition": {"outcome": "passed", "scored_failure_reason": None, "retry_reason": None, "detail": None},
        "rewards": {}, "usage": {}, "timing": {}, "agent_version": "1",
        "harness": {"image_reference": "image", "image_digest": "sha256:digest", "symnav_bench_sha": "a" * 40, "pier_version": "1", "deep_swe_sha": "b" * 40, "symnav_sha": None, "agent_name": "codex", "agent_version": "1", "bundle_id": None, "bundle_hash": None, "task_checksum": "c" * 64, "prompt_rule_hash": "d" * 64, "requested_model": "terra", "requested_effort": "medium"},
        "exception": None, "command_counts": {},
        "adoption": {"used_symnav": False, "read_symnav_skill": False, "symnav_calls": 0, "symnav_calls_per_agent_step": 0, "symnav_failures": 0, "symnav_timeouts": 0, "first_symnav_step": None, "search_calls": 0, "read_calls": 0, "patch_calls": 0, "command_counts": {}},
        "written_at": "2026-01-01T00:00:00+00:00",
    }
    (path / "attempt.json").write_text(json.dumps(data), encoding="utf-8")
    return path


def study_fixture(task_count: int = 2) -> tuple[StudyManifest, SuiteManifest]:
    study = StudyManifest(
        schema_version=1,
        id="study",
        protocol=StudyProtocol(
            benchmark=BenchmarkSelection("deepswe", "a" * 40, None),
            symnav=SymnavRevision("b" * 40, "main", 1, "main", "b" * 40, None),
            repetitions=1,
            wall_clock_seconds=9000,
            randomization_seed=42,
            conditions=("stock", "symnav"),
            scoring_policy="deepswe-pass-fraction-v1",
            practical_uplift_points=5.0,
        ),
        configurations=(AgentConfiguration("codex", AgentSpec("codex", "terra", "medium"), "1"),),
    )
    suite = SuiteManifest(
        deep_swe_sha="a" * 40,
        tasks=tuple(TaskManifestEntry(f"task-{index:03d}", "typescript", f"{index:064x}") for index in range(task_count)),
        fingerprint="c" * 64,
    )
    return study, suite
