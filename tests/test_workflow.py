from __future__ import annotations

from symnav_bench.batch_plan import plan_trial_slots
from symnav_bench.cells.attempt import SlotResult
from symnav_bench.report.study_dataset import StudyDataset
from symnav_bench.run_spec import AgentSpec
from symnav_bench.study import AgentConfiguration, StudyManifest, StudyProtocol, SymnavRevision
from symnav_bench.suite import SuiteManifest, TaskManifestEntry
from symnav_bench.workflow import select_batches


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


def study_fixture(task_count: int = 2) -> tuple[StudyManifest, SuiteManifest]:
    study = StudyManifest(
        schema_version=1,
        id="study",
        protocol=StudyProtocol(
            deep_swe_sha="a" * 40,
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
