from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


DATASET_REPO_ID = "ByteDance-Seed/Multi-SWE-bench"
TYPESCRIPT_DATA_PREFIX = "ts/"
DOCKER_HUB_NAMESPACE = "mswebench"
RUN_BAKED_TESTS_COMMAND = "bash /home/run.sh"


@dataclass(frozen=True)
class MultiSweInstance:
    instance_id: str
    org: str
    repo: str
    number: int
    base_commit: str
    problem_statement: str
    test_patch: str
    f2p: tuple[str, ...]
    p2p: tuple[str, ...]


@dataclass(frozen=True)
class RepoExecutionProfile:
    org: str
    repo: str
    workdir: str
    test_command: str
    log_parser: str


REPO_PROFILES: tuple[RepoExecutionProfile, ...] = (
    RepoExecutionProfile(
        org="darkreader",
        repo="darkreader",
        workdir="/home/darkreader",
        test_command=RUN_BAKED_TESTS_COMMAND,
        log_parser="jest-darkreader",
    ),
    RepoExecutionProfile(
        org="mui",
        repo="material-ui",
        workdir="/home/material-ui",
        test_command=RUN_BAKED_TESTS_COMMAND,
        log_parser="mocha-mui",
    ),
    RepoExecutionProfile(
        org="vuejs",
        repo="core",
        workdir="/home/core",
        test_command=RUN_BAKED_TESTS_COMMAND,
        log_parser="vitest-vuejs",
    ),
)


def execution_profile_for(instance: MultiSweInstance) -> RepoExecutionProfile:
    for profile in REPO_PROFILES:
        if profile.org == instance.org and profile.repo == instance.repo:
            return profile
    raise ValueError(
        f"multi-swe-bench instance {instance.instance_id!r}: no execution profile "
        f"registered for repo {instance.org}/{instance.repo}"
    )


def eval_image_repository(instance: MultiSweInstance) -> str:
    return f"{DOCKER_HUB_NAMESPACE}/{instance.org}_m_{instance.repo}"


def eval_image_tag(instance: MultiSweInstance) -> str:
    return f"pr-{instance.number}"


def parse_multi_swe_rows(rows: Iterable[dict[str, Any]]) -> tuple[MultiSweInstance, ...]:
    return tuple(parse_multi_swe_row(row) for row in rows)


def parse_multi_swe_row(row: dict[str, Any]) -> MultiSweInstance:
    instance_id = row.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        raise ValueError("multi-swe-bench row is missing instance_id")
    title = row_string(row, "title", instance_id)
    body = row_text(row, "body", instance_id)
    return MultiSweInstance(
        instance_id=instance_id,
        org=row_string(row, "org", instance_id),
        repo=row_string(row, "repo", instance_id),
        number=row_positive_integer(row, "number", instance_id),
        base_commit=row_base_commit(row, instance_id),
        problem_statement=problem_statement(title, body),
        test_patch=row_string(row, "test_patch", instance_id),
        f2p=row_test_names(row, "f2p_tests", instance_id, allow_empty=False),
        p2p=row_test_names(row, "p2p_tests", instance_id, allow_empty=True),
    )


def problem_statement(title: str, body: str) -> str:
    if not body.strip():
        return title
    return f"{title}\n\n{body}"


def row_base_commit(row: dict[str, Any], instance_id: str) -> str:
    base = row.get("base")
    if not isinstance(base, dict):
        raise row_error("base", instance_id, "a mapping with a sha")
    sha = base.get("sha")
    if not isinstance(sha, str) or not sha:
        raise row_error("base", instance_id, "a mapping with a non-empty sha")
    return sha


def row_test_names(
    row: dict[str, Any], column: str, instance_id: str, *, allow_empty: bool
) -> tuple[str, ...]:
    value = row.get(column)
    if not isinstance(value, dict):
        raise row_error(column, instance_id, "a mapping of test names")
    if not value and not allow_empty:
        raise row_error(column, instance_id, "a non-empty mapping of test names")
    return tuple(value)


def row_string(row: dict[str, Any], column: str, instance_id: str) -> str:
    value = row.get(column)
    if not isinstance(value, str) or not value:
        raise row_error(column, instance_id, "a non-empty string")
    return value


def row_text(row: dict[str, Any], column: str, instance_id: str) -> str:
    value = row.get(column)
    if not isinstance(value, str):
        raise row_error(column, instance_id, "a string")
    return value


def row_positive_integer(row: dict[str, Any], column: str, instance_id: str) -> int:
    value = row.get(column)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise row_error(column, instance_id, "a positive integer")
    return value


def row_error(column: str, instance_id: str, expectation: str) -> ValueError:
    return ValueError(
        f"multi-swe-bench instance {instance_id!r}: "
        f"column {column!r} must be {expectation}"
    )
