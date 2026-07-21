from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Literal, cast

from symnav_bench.suite import SuiteManifest


@dataclass(frozen=True)
class OfficialReferenceConfiguration:
    model: str
    effort: str
    task_scores: dict[str, float]
    performance_score: float
    repetition_scores: tuple[float, ...] | None
    source_kind: Literal["external"] = "external"


@dataclass(frozen=True)
class OfficialReferenceSnapshot:
    source_url: str
    source_sha256: str
    fetched_at: str
    harness: Literal["mini-swe-agent"]
    configurations: tuple[OfficialReferenceConfiguration, ...]


def import_official_reference(
    source: Path,
    *,
    expected_sha256: str,
    suite: SuiteManifest,
) -> OfficialReferenceSnapshot:
    if suite.benchmark != "deepswe":
        raise ValueError(
            "official reference scores exist only for deepswe; "
            f"suite benchmark is {suite.benchmark}"
        )
    content = source.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"official reference checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    raw = _mapping(json.loads(content), "official snapshot")
    source_url = _string(raw.get("source_url"), "source URL")
    fetched_at = _timestamp(raw.get("fetched_at"))
    if raw.get("harness") != "mini-swe-agent":
        raise ValueError("official reference harness must be mini-swe-agent")
    values = raw.get("configurations")
    if not isinstance(values, list) or not values:
        raise ValueError("official reference configurations must be a non-empty list")
    configurations = tuple(
        _configuration(_mapping(value, "official configuration"), suite)
        for value in values
    )
    identities = [(item.model, item.effort) for item in configurations]
    if len(identities) != len(set(identities)):
        raise ValueError("official reference model and effort pairs must be unique")
    return OfficialReferenceSnapshot(
        source_url=source_url,
        source_sha256=actual_sha256,
        fetched_at=fetched_at,
        harness="mini-swe-agent",
        configurations=configurations,
    )


def matching_official_configuration(
    snapshot: OfficialReferenceSnapshot,
    *,
    model: str,
    effort: str,
) -> OfficialReferenceConfiguration | None:
    return next(
        (
            configuration
            for configuration in snapshot.configurations
            if configuration.model == model and configuration.effort == effort
        ),
        None,
    )


def _configuration(
    raw: dict[str, Any],
    suite: SuiteManifest,
) -> OfficialReferenceConfiguration:
    model = _string(raw.get("model"), "official model")
    effort = _string(raw.get("effort"), "official effort")
    task_values = _mapping(raw.get("task_scores"), "official task scores")
    expected_tasks = {task.slug for task in suite.tasks}
    if set(task_values) != expected_tasks:
        raise ValueError("official reference task set must exactly match suite")
    task_scores = {
        task: _score(value, f"official task score {task}")
        for task, value in task_values.items()
    }
    performance_score = _score(
        raw.get("performance_score"),
        "official performance score",
    )
    if not _same_score(performance_score, mean(task_scores.values())):
        raise ValueError("official performance score must equal mean task score")
    repetition_value = raw.get("repetition_scores")
    repetition_scores = (
        None
        if repetition_value is None
        else _repetition_scores(repetition_value, performance_score)
    )
    return OfficialReferenceConfiguration(
        model=model,
        effort=effort,
        task_scores=task_scores,
        performance_score=performance_score,
        repetition_scores=repetition_scores,
    )


def _repetition_scores(value: object, performance_score: float) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("official repetition scores must contain four values")
    scores = tuple(
        _score(item, "official repetition score") for item in value
    )
    if not _same_score(mean(scores), performance_score):
        raise ValueError("official repetition scores must average to performance score")
    return scores


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object")
    return cast(dict[str, Any], value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _timestamp(value: object) -> str:
    timestamp = _string(value, "retrieval timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("retrieval timestamp must be ISO 8601") from error
    if parsed.tzinfo is None:
        raise ValueError("retrieval timestamp must include timezone")
    return timestamp


def _score(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    score = float(value)
    if not 0 <= score <= 1:
        raise ValueError(f"{name} must be between zero and one")
    return score


def _same_score(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-12
