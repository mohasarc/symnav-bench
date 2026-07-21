from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

from symnav_bench.report.dashboard_payload import build_dashboard_payload
from symnav_bench.report.statistics import compare_condition_to_stock
from symnav_bench.report.study_dataset import ConfigurationKey
from symnav_bench.report.study_dataset import ConfigurationMetrics
from symnav_bench.report.study_dataset import Coverage
from symnav_bench.report.study_dataset import StudyDataset
from symnav_bench.report.study_dataset import TaskMetrics
from symnav_bench.study import AgentConfiguration
from symnav_bench.study import BenchmarkSelection
from symnav_bench.study import StudyManifest
from symnav_bench.study import StudyProtocol
from symnav_bench.study import SymnavRevision
from symnav_bench.run_spec import AgentSpec
from symnav_bench.suite import SuiteManifest
from symnav_bench.suite import TaskManifestEntry


GOLDEN_FIXTURES = Path(__file__).parent / "fixtures" / "golden"


def test_deepswe_payload_serializes_byte_identically_to_golden() -> None:
    dataset = study_dataset()
    stock = metrics("stock", 0.25)
    symnav = metrics("symnav", 0.75)
    comparison = compare_condition_to_stock(
        stock,
        symnav,
        seed=42,
        study_id="study",
        symnav_revision=dataset.manifest.protocol.symnav,
        suite_fingerprint=dataset.suite.fingerprint,
    )

    payload = build_dashboard_payload(dataset, (stock, symnav), (comparison,), (), None)
    serialized = json.dumps(asdict(payload), indent=2, sort_keys=True) + "\n"

    assert serialized.encode() == (GOLDEN_FIXTURES / "deepswe-dashboard-payload.json").read_bytes()


def test_builds_versioned_canonical_dashboard_payload() -> None:
    dataset = study_dataset()
    stock = metrics("stock", 0.25)
    symnav = metrics("symnav", 0.75)
    comparison = compare_condition_to_stock(
        stock,
        symnav,
        seed=42,
        study_id="study",
        symnav_revision=dataset.manifest.protocol.symnav,
        suite_fingerprint=dataset.suite.fingerprint,
    )

    payload = build_dashboard_payload(
        dataset,
        (stock, symnav),
        (comparison,),
        (),
        None,
    )

    assert payload.schema_version == 1
    assert payload.study["id"] == "study"
    assert payload.study["scoring_policy"] == "deepswe-pass-fraction-v1"
    assert "benchmark" not in payload.study
    assert payload.coverage == {
        "planned_slots": 8,
        "scored_slots": 8,
        "complete_tasks": 1,
        "total_tasks": 1,
        "provisional": False,
        "pilot": False,
    }
    assert [item["condition"] for item in payload.configurations] == ["stock", "symnav"]
    assert payload.configurations[1]["full_symnav"] is True
    assert payload.comparisons[0]["uplift"]["value"] == 0.5
    assert payload.tasks[1]["metrics"]["performance_score"] == 0.75
    assert payload.versions == ()
    assert payload.official_references == ()
    assert payload.attempts == ()
    assert payload.warnings == ()


def test_incomplete_task_values_stay_null_and_coverage_stays_visible() -> None:
    dataset = study_dataset()
    incomplete = replace(
        metrics("stock", None),
        coverage=Coverage(4, 0, 0, ("missing",), 0, 1, True, True),
        performance_score=None,
    )

    payload = build_dashboard_payload(dataset, (incomplete,), (), (), None)

    assert payload.configurations[0]["coverage"]["provisional"] is True
    assert payload.configurations[0]["coverage"]["pilot"] is True
    assert payload.tasks[0]["metrics"]["performance_score"] is None


def test_polybench_payload_carries_benchmark_header_and_tier_rows() -> None:
    dataset = benchmark_dataset("swe-polybench", tiers=("high", "mid"), task_tier="high")
    stock = metrics("stock", 0.25, tier="high")

    payload = build_dashboard_payload(dataset, (stock,), (), (), None)

    assert payload.study["benchmark"] == "swe-polybench"
    assert payload.study["benchmark_source_revision"] == "a" * 40
    assert [row["tier"] for row in payload.tasks] == ["high"]


def test_multi_swe_payload_labels_benchmark_without_tier() -> None:
    dataset = benchmark_dataset("multi-swe-bench", tiers=None, task_tier=None)
    stock = metrics("stock", 0.25)

    payload = build_dashboard_payload(dataset, (stock,), (), (), None)

    assert payload.study["benchmark"] == "multi-swe-bench"
    assert all("tier" not in row for row in payload.tasks)


def benchmark_dataset(
    benchmark: str,
    tiers: tuple[str, ...] | None,
    task_tier: str | None,
) -> StudyDataset:
    revision = SymnavRevision("b" * 40, "main", 1, "main", "b" * 40, None)
    protocol = StudyProtocol(
        BenchmarkSelection(benchmark, "a" * 40, tiers),
        revision,
        4,
        9_000,
        42,
        ("stock", "symnav"),
        "deepswe-pass-fraction-v1",
        5.0,
    )
    manifest = StudyManifest(
        2,
        "study",
        protocol,
        (AgentConfiguration("codex-terra", AgentSpec("codex", "terra", "medium"), "0.31.0"),),
    )
    task_kwargs = {"tier": task_tier} if task_tier is not None else {}
    suite = SuiteManifest(
        benchmark,
        "a" * 40,
        (TaskManifestEntry("task", "typescript", "c" * 64, **task_kwargs),),
        "d" * 64,
    )
    return StudyDataset(manifest, suite, (), ())


def study_dataset() -> StudyDataset:
    revision = SymnavRevision("b" * 40, "main", 1, "main", "b" * 40, None)
    protocol = StudyProtocol(
        BenchmarkSelection("deepswe", "a" * 40, None),
        revision,
        4,
        9_000,
        42,
        ("stock", "symnav"),
        "deepswe-pass-fraction-v1",
        5.0,
    )
    manifest = StudyManifest(
        1,
        "study",
        protocol,
        (AgentConfiguration("codex-terra", AgentSpec("codex", "terra", "medium"), "0.31.0"),),
    )
    suite = SuiteManifest(
        "deepswe",
        "a" * 40,
        (TaskManifestEntry("task", "typescript", "c" * 64),),
        "d" * 64,
    )
    return StudyDataset(manifest, suite, (), ())


def metrics(
    condition: str,
    score: float | None,
    tier: str | None = None,
) -> ConfigurationMetrics:
    task_kwargs = {"tier": tier} if tier is not None else {}
    task = TaskMetrics(
        "task",
        4 if score is not None else 0,
        score,
        score,
        1.0 if score is not None else None,
        score,
        2.0,
        2.0,
        10.0,
        3.0,
        4.0,
        None,
        **task_kwargs,
    )
    return ConfigurationMetrics(
        ConfigurationKey(
            "codex",
            "terra",
            "medium",
            "0.31.0",
            condition,
            None if condition == "stock" else "bundle",
        ),
        Coverage(4, 4, 0, (), 1, 1, False, False),
        (task,),
        score,
        (score, score, score, score) if score is not None else (),
        score,
        1.0 if score is not None else None,
        score,
        8.0,
        8.0,
        None,
    )
