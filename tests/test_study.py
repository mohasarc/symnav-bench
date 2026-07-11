from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from symnav_bench.study import StudyManifest


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
