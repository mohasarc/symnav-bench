from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from symnav_bench.report.official_reference import OfficialReferenceSnapshot
from symnav_bench.report.official_reference import import_official_reference
from symnav_bench.report.study_dataset import StudyDataset


OFFICIAL_REFERENCE_FILE = "official-reference.json"
OFFICIAL_REFERENCE_CHECKSUM_FILE = "official-reference.sha256"
COMPATIBLE_STUDIES_FILE = "compatible-studies.json"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class CompatibleStudyPin:
    path: str
    study_id: str
    protocol_fingerprint: str
    suite_fingerprint: str


@dataclass(frozen=True)
class ReportInputs:
    official_reference: OfficialReferenceSnapshot | None
    compatible_studies: tuple[StudyDataset, ...]


def load_report_inputs(dataset: StudyDataset) -> ReportInputs:
    if dataset.source_dir is None:
        return ReportInputs(None, ())
    return ReportInputs(
        official_reference=_load_official_reference(dataset),
        compatible_studies=_load_compatible_studies(dataset),
    )


def _load_official_reference(
    dataset: StudyDataset,
) -> OfficialReferenceSnapshot | None:
    assert dataset.source_dir is not None
    source = dataset.source_dir / OFFICIAL_REFERENCE_FILE
    checksum_path = dataset.source_dir / OFFICIAL_REFERENCE_CHECKSUM_FILE
    if not source.exists() and not checksum_path.exists():
        return None
    if not source.is_file() or not checksum_path.is_file():
        raise ValueError(
            f"{OFFICIAL_REFERENCE_FILE} and {OFFICIAL_REFERENCE_CHECKSUM_FILE} "
            "must be published together"
        )
    checksum = checksum_path.read_text(encoding="utf-8").strip().split(maxsplit=1)[0]
    if SHA256.fullmatch(checksum) is None:
        raise ValueError(f"{OFFICIAL_REFERENCE_CHECKSUM_FILE} must contain a SHA256 checksum")
    return import_official_reference(
        source,
        expected_sha256=checksum,
        suite=dataset.suite,
    )


def _load_compatible_studies(dataset: StudyDataset) -> tuple[StudyDataset, ...]:
    assert dataset.source_dir is not None
    path = dataset.source_dir / COMPATIBLE_STUDIES_FILE
    if not path.exists():
        return ()
    raw = _mapping(json.loads(path.read_text(encoding="utf-8")), COMPATIBLE_STUDIES_FILE)
    if raw.get("schema_version") != 1:
        raise ValueError(f"unsupported {COMPATIBLE_STUDIES_FILE} schema version")
    values = raw.get("studies")
    if not isinstance(values, list):
        raise ValueError(f"{COMPATIBLE_STUDIES_FILE} studies must be a list")
    pins = tuple(_compatible_study_pin(value) for value in values)
    if len({pin.study_id for pin in pins}) != len(pins):
        raise ValueError(f"{COMPATIBLE_STUDIES_FILE} study IDs must be unique")
    return tuple(_load_compatible_study(dataset, pin) for pin in pins)


def _compatible_study_pin(value: object) -> CompatibleStudyPin:
    raw = _mapping(value, "compatible study")
    return CompatibleStudyPin(
        path=_string(raw.get("path"), "compatible study path"),
        study_id=_string(raw.get("study_id"), "compatible study ID"),
        protocol_fingerprint=_checksum(
            raw.get("protocol_fingerprint"),
            "compatible study protocol fingerprint",
        ),
        suite_fingerprint=_checksum(
            raw.get("suite_fingerprint"),
            "compatible study suite fingerprint",
        ),
    )


def _load_compatible_study(
    current: StudyDataset,
    pin: CompatibleStudyPin,
) -> StudyDataset:
    assert current.source_dir is not None
    relative = Path(pin.path)
    if relative.is_absolute():
        raise ValueError("compatible study path must be relative to study root")
    candidate = StudyDataset.load(current.source_dir / relative)
    if candidate.manifest.id != pin.study_id:
        raise ValueError(f"compatible study ID does not match pin {pin.study_id}")
    if candidate.manifest.protocol_fingerprint() != pin.protocol_fingerprint:
        raise ValueError(f"compatible study {pin.study_id} protocol fingerprint does not match pin")
    if candidate.suite.fingerprint != pin.suite_fingerprint:
        raise ValueError(f"compatible study {pin.study_id} suite fingerprint does not match pin")
    if candidate.suite.fingerprint != current.suite.fingerprint:
        raise ValueError(f"compatible study {pin.study_id} suite does not match current study")
    return candidate


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _checksum(value: object, label: str) -> str:
    checksum = _string(value, label)
    if SHA256.fullmatch(checksum) is None:
        raise ValueError(f"{label} must be a SHA256 checksum")
    return checksum
