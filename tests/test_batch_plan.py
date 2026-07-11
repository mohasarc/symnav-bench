from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import yaml

from symnav_bench.batch_plan import plan_balanced_batches, plan_trial_slots
from symnav_bench.cli import main
from symnav_bench.run_spec import AgentSpec
from symnav_bench.study import (
    AgentConfiguration,
    StudyManifest,
    StudyProtocol,
    SymnavRevision,
)
from symnav_bench.suite import SuiteManifest, TaskManifestEntry


def test_expands_every_configuration_task_condition_and_repetition() -> None:
    study = make_study(configuration_count=2, repetitions=4)
    suite = make_suite(3)

    slots = plan_trial_slots(study, suite)

    assert len(slots) == 2 * 3 * 2 * 4
    assert len({slot.slot_id for slot in slots}) == len(slots)
    assert Counter(slot.configuration_id for slot in slots) == {
        "configuration-0": 24,
        "configuration-1": 24,
    }


def test_slot_ids_are_stable_across_planner_instances() -> None:
    study = make_study(configuration_count=1, repetitions=4)
    suite = make_suite(5)

    first = plan_trial_slots(study, suite)
    second = plan_trial_slots(study, suite)

    assert first == second
    assert [slot.slot_id for slot in first] == [slot.slot_id for slot in second]


def test_seeded_batches_shuffle_blocks_and_keep_conditions_adjacent() -> None:
    study = make_study(configuration_count=1, repetitions=4)
    slots = plan_trial_slots(study, make_suite(35))

    first = plan_balanced_batches(slots, randomization_seed=21)
    repeated = plan_balanced_batches(slots, randomization_seed=21)
    changed = plan_balanced_batches(slots, randomization_seed=22)

    assert first == repeated
    assert [slot.slot_id for batch in first for slot in batch.slots] != [
        slot.slot_id for batch in changed for slot in batch.slots
    ]
    for batch in first:
        assert len(batch.slots) <= 256
        assert Counter(slot.condition for slot in batch.slots) == {
            "stock": len(batch.slots) // 2,
            "symnav": len(batch.slots) // 2,
        }
        for index in range(0, len(batch.slots), 2):
            stock, symnav = batch.slots[index : index + 2]
            assert (stock.task, stock.repetition) == (symnav.task, symnav.repetition)
            assert (stock.condition, symnav.condition) == ("stock", "symnav")


def test_primary_typescript_study_splits_into_two_balanced_batches() -> None:
    study = make_study(configuration_count=1, repetitions=4)
    slots = plan_trial_slots(study, make_suite(35))

    batches = plan_balanced_batches(
        slots,
        randomization_seed=study.protocol.randomization_seed,
    )

    assert len(slots) == 280
    assert [len(batch.slots) for batch in batches] == [140, 140]
    assert [batch.index for batch in batches] == [0, 1]
    assert len({batch.batch_id for batch in batches}) == 2


def test_plan_study_json_emits_suite_slots_batches_and_zero_coverage(
    tmp_path: Path, capsys
) -> None:
    tasks_dir = tmp_path / "tasks"
    write_task(tasks_dir / "zeta")
    write_task(tasks_dir / "alpha")
    study_path = write_cli_study(tmp_path / "study.yaml")

    assert (
        main(
            [
                "plan-study",
                "--study",
                str(study_path),
                "--tasks-dir",
                str(tasks_dir),
                "--json",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)

    assert plan["study_id"] == "cli-study"
    assert plan["protocol_fingerprint"] == fingerprint(plan["protocol"])
    assert [task["slug"] for task in plan["suite"]["tasks"]] == ["alpha", "zeta"]
    assert [configuration["id"] for configuration in plan["configurations"]] == [
        "codex-terra-medium"
    ]
    assert len(plan["slots"]) == 16
    assert len(plan["batches"]) == 1
    assert plan["coverage"] == {"completed": 0, "fraction": 0.0, "total": 16}


def make_study(configuration_count: int, repetitions: int) -> StudyManifest:
    configurations = tuple(
        AgentConfiguration(
            id=f"configuration-{index}",
            spec=AgentSpec("codex", f"model-{index}", "medium"),
            agent_version="1.0.0",
        )
        for index in range(configuration_count)
    )
    return StudyManifest(
        schema_version=1,
        id="study",
        protocol=StudyProtocol(
            deep_swe_sha="a" * 40,
            symnav=SymnavRevision(
                sha="b" * 40,
                kind="main",
                evaluation_sequence=1,
                base_ref="main",
                base_sha="b" * 40,
                pull_request=None,
            ),
            repetitions=repetitions,
            wall_clock_seconds=9_000,
            randomization_seed=42,
            conditions=("stock", "symnav"),
            scoring_policy="deepswe-pass-fraction-v1",
            practical_uplift_points=5.0,
        ),
        configurations=configurations,
    )


def make_suite(task_count: int) -> SuiteManifest:
    return SuiteManifest(
        deep_swe_sha="a" * 40,
        tasks=tuple(
            TaskManifestEntry(
                slug=f"task-{index:02d}",
                language="typescript",
                checksum=f"{index:064x}",
            )
            for index in range(task_count)
        ),
        fingerprint="c" * 64,
    )


def write_task(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "task.toml").write_text(
        '[metadata]\nlanguage = "typescript"\n', encoding="utf-8"
    )
    (path / "prompt.md").write_text("Fix it", encoding="utf-8")


def write_cli_study(path: Path) -> Path:
    protocol = {
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
    data = {
        "schema_version": 1,
        "id": "cli-study",
        "protocol_fingerprint": fingerprint(protocol),
        "protocol": protocol,
        "configurations": [
            {
                "id": "codex-terra-medium",
                "agent": "codex",
                "model": "gpt-5.6-terra",
                "effort": "medium",
                "agent_version": "0.31.0",
            }
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def fingerprint(value: dict) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
