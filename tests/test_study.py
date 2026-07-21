from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from symnav_bench.study import StudyManifest

COMMITTED_V1_MANIFEST = Path(__file__).parent / "fixtures" / "studies" / "deepswe-v1-manifest.yml"
COMMITTED_V1_FINGERPRINT = "4695372f68fe8178dec2d1bd09e7864a1bcd251a6036cd6d300f370d115f6419"
COMMITTED_V1_DEEP_SWE_SHA = "6db64a40f3318d8659238ff34a8cc4b491c49205"


def test_committed_v1_manifest_loads_with_unchanged_fingerprint() -> None:
    study = StudyManifest.load(COMMITTED_V1_MANIFEST)

    assert study.schema_version == 1
    assert study.id == "deepswe-ts-codex-terra-medium-pr94-smoke"
    assert study.protocol_fingerprint() == COMMITTED_V1_FINGERPRINT
    assert study.protocol.conditions == ("stock", "symnav")
    assert study.protocol.repetitions == 1


def test_committed_v1_manifest_normalizes_to_deepswe_benchmark() -> None:
    study = StudyManifest.load(COMMITTED_V1_MANIFEST)

    assert study.protocol.benchmark.name == "deepswe"
    assert study.protocol.benchmark.source_revision == COMMITTED_V1_DEEP_SWE_SHA
    assert study.protocol.benchmark.tiers is None


def test_loads_pinned_study_with_multiple_configurations(tmp_path: Path) -> None:
    study_path = write_study(tmp_path / "study.yaml", study_data())

    study = StudyManifest.load(study_path)

    assert study.id == "typescript-primary"
    assert study.protocol.repetitions == 4
    assert study.protocol.wall_clock_seconds == 9_000
    assert study.protocol.conditions == ("stock", "symnav")
    assert study.protocol.symnav.sha == "b" * 40
    assert study.protocol.symnav.evaluation_sequence == 12
    assert [configuration.id for configuration in study.configurations] == [
        "codex-terra-medium",
        "claude-opus-high",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("deep_swe_sha", "main"),
        ("symnav.sha", "refs/pull/94/head"),
        ("symnav.base_sha", "origin/main"),
    ],
)
def test_rejects_mutable_execution_revisions(tmp_path: Path, field: str, value: str) -> None:
    data = study_data()
    set_protocol_field(data["protocol"], field, value)
    data["protocol_fingerprint"] = fingerprint(data["protocol"])

    with pytest.raises(ValueError, match="immutable git sha"):
        StudyManifest.load(write_study(tmp_path / "study.yaml", data))


def test_appending_configuration_preserves_protocol_fingerprint(tmp_path: Path) -> None:
    original_data = study_data()
    original_data["configurations"] = original_data["configurations"][:1]
    original = StudyManifest.load(write_study(tmp_path / "original.yaml", original_data))
    appended = StudyManifest.load(write_study(tmp_path / "appended.yaml", study_data()))

    assert original.protocol_fingerprint() == appended.protocol_fingerprint()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("deep_swe_sha", "d" * 40),
        ("symnav.sha", "e" * 40),
        ("repetitions", 5),
        ("wall_clock_seconds", 8_000),
        ("scoring_policy", "another-policy"),
        ("randomization_seed", 99),
    ],
)
def test_rejects_protocol_edits_under_existing_study_id(
    tmp_path: Path, field: str, value: object
) -> None:
    data = study_data()
    set_protocol_field(data["protocol"], field, value)

    with pytest.raises(ValueError, match="protocol fingerprint"):
        StudyManifest.load(write_study(tmp_path / "study.yaml", data))


def test_v2_deepswe_manifest_loads_and_round_trips_fingerprint(tmp_path: Path) -> None:
    data = study_data_v2({"name": "deepswe", "source": {"revision": "a" * 40}})

    study = StudyManifest.load(write_study(tmp_path / "study.yaml", data))

    assert study.schema_version == 2
    assert study.protocol.benchmark.name == "deepswe"
    assert study.protocol.benchmark.source_revision == "a" * 40
    assert study.protocol.benchmark.tiers is None
    assert study.protocol_fingerprint() == data["protocol_fingerprint"]


def test_v2_swe_polybench_manifest_loads_tiers_in_declaration_order(tmp_path: Path) -> None:
    data = study_data_v2(
        {"name": "swe-polybench", "source": {"revision": "a" * 40}, "tiers": ["high", "mid"]}
    )

    study = StudyManifest.load(write_study(tmp_path / "study.yaml", data))

    assert study.protocol.benchmark.name == "swe-polybench"
    assert study.protocol.benchmark.tiers == ("high", "mid")
    assert study.protocol_fingerprint() == data["protocol_fingerprint"]


def test_v2_multi_swe_bench_manifest_loads_without_tiers(tmp_path: Path) -> None:
    data = study_data_v2({"name": "multi-swe-bench", "source": {"revision": "a" * 40}})

    study = StudyManifest.load(write_study(tmp_path / "study.yaml", data))

    assert study.protocol.benchmark.name == "multi-swe-bench"
    assert study.protocol.benchmark.tiers is None
    assert study.protocol_fingerprint() == data["protocol_fingerprint"]


@pytest.mark.parametrize(
    ("benchmark", "match"),
    [
        ({"name": "swe-bench", "source": {"revision": "a" * 40}}, "unknown benchmark"),
        (
            {"name": "swe-polybench", "source": {"revision": "a" * 40}, "tiers": []},
            "tiers",
        ),
        (
            {"name": "swe-polybench", "source": {"revision": "a" * 40}, "tiers": ["high", "epic"]},
            "fit tier",
        ),
        (
            {"name": "swe-polybench", "source": {"revision": "a" * 40}, "tiers": ["high", "high"]},
            "unique",
        ),
        (
            {"name": "deepswe", "source": {"revision": "a" * 40}, "tiers": ["high"]},
            "tiers",
        ),
        (
            {"name": "deepswe", "source": {"revision": "a" * 40}, "tiers": None},
            "tiers",
        ),
        (
            {"name": "multi-swe-bench", "source": {"revision": "a" * 40}, "tiers": ["high"]},
            "tiers",
        ),
        ({"name": "deepswe", "source": {"revision": "main"}}, "immutable git sha"),
    ],
)
def test_rejects_invalid_v2_benchmark_blocks(
    tmp_path: Path, benchmark: dict, match: str
) -> None:
    data = study_data_v2(benchmark)

    with pytest.raises(ValueError, match=match):
        StudyManifest.load(write_study(tmp_path / "study.yaml", data))


def test_rejects_v2_manifest_with_top_level_deep_swe_sha(tmp_path: Path) -> None:
    data = study_data_v2({"name": "deepswe", "source": {"revision": "a" * 40}})
    data["protocol"]["deep_swe_sha"] = "a" * 40
    data["protocol_fingerprint"] = fingerprint(data["protocol"])

    with pytest.raises(ValueError, match="deep_swe_sha"):
        StudyManifest.load(write_study(tmp_path / "study.yaml", data))


def test_rejects_v1_manifest_with_benchmark_block(tmp_path: Path) -> None:
    data = study_data()
    data["protocol"]["benchmark"] = {"name": "deepswe", "source": {"revision": "a" * 40}}
    data["protocol_fingerprint"] = fingerprint(data["protocol"])

    with pytest.raises(ValueError, match="benchmark"):
        StudyManifest.load(write_study(tmp_path / "study.yaml", data))


def test_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    data = study_data()
    data["schema_version"] = 3

    with pytest.raises(ValueError, match="schema version"):
        StudyManifest.load(write_study(tmp_path / "study.yaml", data))


def study_data_v2(benchmark: dict) -> dict:
    data = study_data()
    data["schema_version"] = 2
    del data["protocol"]["deep_swe_sha"]
    data["protocol"]["benchmark"] = benchmark
    data["protocol_fingerprint"] = fingerprint(data["protocol"])
    return data


def study_data() -> dict:
    protocol = {
        "deep_swe_sha": "a" * 40,
        "symnav": {
            "sha": "b" * 40,
            "kind": "pull_request",
            "evaluation_sequence": 12,
            "base_ref": "main",
            "base_sha": "c" * 40,
            "pull_request": 94,
        },
        "repetitions": 4,
        "wall_clock_seconds": 9_000,
        "randomization_seed": 20260712,
        "conditions": ["stock", "symnav"],
        "scoring_policy": "deepswe-pass-fraction-v1",
        "practical_uplift_points": 5.0,
    }
    return {
        "schema_version": 1,
        "id": "typescript-primary",
        "protocol_fingerprint": fingerprint(protocol),
        "protocol": protocol,
        "configurations": [
            {
                "id": "codex-terra-medium",
                "agent": "codex",
                "model": "gpt-5.6-terra",
                "effort": "medium",
                "agent_version": "0.31.0",
            },
            {
                "id": "claude-opus-high",
                "agent": "claude",
                "model": "claude-opus-4-1",
                "effort": "high",
                "agent_version": "1.0.80",
            },
        ],
    }


def fingerprint(protocol: dict) -> str:
    canonical = json.dumps(protocol, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def set_protocol_field(protocol: dict, field: str, value: object) -> None:
    target = protocol
    parts = field.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def write_study(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(copy.deepcopy(data), sort_keys=False), encoding="utf-8")
    return path
