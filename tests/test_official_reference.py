from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from symnav_bench.report.official_reference import import_official_reference
from symnav_bench.report.official_reference import matching_official_configuration
from symnav_bench.report.statistics import compare_condition_to_stock
from symnav_bench.suite import SuiteManifest
from symnav_bench.suite import TaskManifestEntry


def test_imports_pinned_mini_swe_agent_typescript_snapshot(tmp_path: Path) -> None:
    source, checksum = write_snapshot(tmp_path / "official.json")

    snapshot = import_official_reference(
        source,
        expected_sha256=checksum,
        suite=suite(),
    )

    assert snapshot.source_url == "https://example.test/deepswe-results.json"
    assert snapshot.source_sha256 == checksum
    assert snapshot.fetched_at == "2026-07-12T08:30:00+00:00"
    assert snapshot.harness == "mini-swe-agent"
    assert len(snapshot.configurations) == 1
    configuration = snapshot.configurations[0]
    assert configuration.source_kind == "external"
    assert configuration.task_scores == {"alpha": 0.75, "beta": 0.25}
    assert configuration.performance_score == 0.5
    assert configuration.repetition_scores == (1.0, 0.5, 0.5, 0.0)


def test_rejects_unpinned_or_changed_source(tmp_path: Path) -> None:
    source, checksum = write_snapshot(tmp_path / "official.json")

    with pytest.raises(ValueError, match="checksum"):
        import_official_reference(
            source,
            expected_sha256="0" * 64,
            suite=suite(),
        )
    assert checksum != "0" * 64


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"harness": "other"}, "mini-swe-agent"),
        ({"fetched_at": "yesterday"}, "timestamp"),
        ({"source_url": ""}, "source URL"),
    ],
)
def test_requires_snapshot_provenance(
    tmp_path: Path,
    mutation: dict[str, str],
    message: str,
) -> None:
    source, checksum = write_snapshot(tmp_path / "official.json", mutation=mutation)

    with pytest.raises(ValueError, match=message):
        import_official_reference(source, expected_sha256=checksum, suite=suite())


def test_requires_exact_suite_task_set(tmp_path: Path) -> None:
    source, checksum = write_snapshot(
        tmp_path / "official.json",
        task_scores={"alpha": 0.75, "extra": 0.25},
    )

    with pytest.raises(ValueError, match="task set"):
        import_official_reference(source, expected_sha256=checksum, suite=suite())


def test_matches_external_rows_by_model_and_effort(tmp_path: Path) -> None:
    source, checksum = write_snapshot(tmp_path / "official.json")
    snapshot = import_official_reference(
        source,
        expected_sha256=checksum,
        suite=suite(),
    )

    assert matching_official_configuration(
        snapshot,
        model="terra",
        effort="medium",
    ) is snapshot.configurations[0]
    assert matching_official_configuration(
        snapshot,
        model="terra",
        effort="high",
    ) is None


def test_external_reference_cannot_be_used_as_stock(tmp_path: Path) -> None:
    source, checksum = write_snapshot(tmp_path / "official.json")
    snapshot = import_official_reference(
        source,
        expected_sha256=checksum,
        suite=suite(),
    )
    external = snapshot.configurations[0]

    with pytest.raises(TypeError, match="external"):
        compare_condition_to_stock(external, external, seed=1)


def suite() -> SuiteManifest:
    return SuiteManifest(
        deep_swe_sha="a" * 40,
        tasks=(
            TaskManifestEntry("alpha", "typescript", "1" * 64),
            TaskManifestEntry("beta", "typescript", "2" * 64),
        ),
        fingerprint="3" * 64,
    )


def write_snapshot(
    path: Path,
    *,
    mutation: dict[str, str] | None = None,
    task_scores: dict[str, float] | None = None,
) -> tuple[Path, str]:
    value = {
        "source_url": "https://example.test/deepswe-results.json",
        "fetched_at": "2026-07-12T08:30:00+00:00",
        "harness": "mini-swe-agent",
        "configurations": [
            {
                "model": "terra",
                "effort": "medium",
                "task_scores": task_scores or {"alpha": 0.75, "beta": 0.25},
                "performance_score": 0.5,
                "repetition_scores": [1.0, 0.5, 0.5, 0.0],
            }
        ],
    }
    value.update(mutation or {})
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()
