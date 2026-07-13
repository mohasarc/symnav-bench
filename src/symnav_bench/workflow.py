from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import hashlib
import tarfile
from typing import Literal
from typing import Sequence
from typing import TextIO

from symnav_bench.batch_plan import BatchPlan
from symnav_bench.batch_plan import plan_balanced_batches, plan_trial_slots
from symnav_bench.report.study_dataset import StudyDataset
from symnav_bench.cells.attempt import AttemptRecord
from symnav_bench.study import StudyManifest
from symnav_bench.suite import SuiteManifest


RunMode = Literal["run-next", "run-all", "resume"]


@dataclass(frozen=True)
class BatchSelection:
    study_id: str
    configuration_id: str
    mode: RunMode
    batches: tuple[BatchPlan, ...]


@dataclass(frozen=True)
class ArtifactPointer:
    archive: str
    internal_path: str
    sha256: str


def merge_attempt_artifacts(
    study_dir: Path,
    artifact_dirs: Sequence[Path],
) -> list[AttemptRecord]:
    merged: list[AttemptRecord] = []
    for artifact_dir in artifact_dirs:
        for source in sorted(artifact_dir.rglob("attempt.json")):
            raw = json.loads(source.read_text(encoding="utf-8"))
            slot_id = str(raw["identity"]["slot_id"])
            attempt_id = str(raw["identity"]["attempt_id"])
            target = study_dir / "attempts" / slot_id / f"{attempt_id}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not _same_attempt_content(target, source):
                    raise FileExistsError(f"attempt already exists with different content: {target}")
            else:
                shutil.copy2(source, target)
            merged.append(AttemptRecord.load(source))
    return sorted(merged, key=lambda attempt: attempt.identity.attempt_id)


def _same_attempt_content(existing: Path, incoming: Path) -> bool:
    existing_data = json.loads(existing.read_text(encoding="utf-8"))
    incoming_data = json.loads(incoming.read_text(encoding="utf-8"))
    if not isinstance(existing_data, dict) or not isinstance(incoming_data, dict):
        return existing_data == incoming_data
    existing_data.pop("artifact", None)
    incoming_data.pop("artifact", None)
    return existing_data == incoming_data


def build_raw_archive(
    artifact_dirs: Sequence[Path],
    archive_path: Path,
) -> dict[str, ArtifactPointer]:
    if archive_path.exists():
        raise FileExistsError(f"archive already exists: {archive_path}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    internal_paths: dict[str, str] = {}
    with tarfile.open(archive_path, "w:gz") as archive:
        for artifact_dir in artifact_dirs:
            attempt_path = next(iter(sorted(artifact_dir.rglob("attempt.json"))), None)
            if attempt_path is None:
                continue
            raw = json.loads(attempt_path.read_text(encoding="utf-8"))
            attempt_id = str(raw["identity"]["attempt_id"])
            internal_path = f"attempts/{attempt_id}"
            internal_paths[attempt_id] = internal_path
            for source in sorted(path for path in artifact_dir.rglob("*") if path.is_file()):
                if _is_secret_path(source.relative_to(artifact_dir)):
                    continue
                archive.add(source, arcname=f"{internal_path}/{source.relative_to(artifact_dir).as_posix()}")
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    return {
        attempt_id: ArtifactPointer(archive_path.name, internal_path, checksum)
        for attempt_id, internal_path in internal_paths.items()
    }


def _is_secret_path(path: Path) -> bool:
    normalized = path.as_posix().lower()
    return any(
        marker in normalized
        for marker in (".env", "secret", "credential", "auth.json", "token")
    )


def write_github_matrix(batch: BatchPlan, out: TextIO) -> None:
    if len(batch.slots) > 256:
        raise ValueError("GitHub matrix cannot exceed 256 cells")
    json.dump(
        {
            "include": [
                {
                    "study_id": slot.study_id,
                    "configuration_id": slot.configuration_id,
                    "batch_id": batch.batch_id,
                    "slot_id": slot.slot_id,
                    "condition": slot.condition,
                    "task": slot.task,
                    "repetition": slot.repetition,
                }
                for slot in batch.slots
            ]
        },
        out,
        separators=(",", ":"),
        sort_keys=True,
    )
    out.write("\n")


def select_batches(
    study: StudyManifest,
    suite: SuiteManifest,
    existing: StudyDataset | None,
    *,
    configuration_id: str,
    mode: RunMode,
) -> BatchSelection:
    if configuration_id not in {item.id for item in study.configurations}:
        raise ValueError(f"unknown configuration {configuration_id!r}")
    configuration_slots = [
        slot
        for slot in plan_trial_slots(study, suite)
        if slot.configuration_id == configuration_id
    ]
    completed = (
        {
            result.slot.slot_id
            for result in existing.slots
            if result.scored_attempt is not None
        }
        if existing is not None
        else set()
    )
    pending_slots = [slot for slot in configuration_slots if slot.slot_id not in completed]
    try:
        pending = tuple(
            plan_balanced_batches(
                pending_slots,
                randomization_seed=study.protocol.randomization_seed,
            )
        )
    except ValueError:
        planned = plan_balanced_batches(
            configuration_slots,
            randomization_seed=study.protocol.randomization_seed,
        )
        pending = tuple(
            BatchPlan(
                study_id=batch.study_id,
                configuration_id=batch.configuration_id,
                batch_id=batch.batch_id,
                index=batch.index,
                slots=tuple(slot for slot in batch.slots if slot.slot_id not in completed),
            )
            for batch in planned
            if any(slot.slot_id not in completed for slot in batch.slots)
        )
    selected = pending[:1] if mode == "run-next" else pending
    return BatchSelection(study.id, configuration_id, mode, selected)
