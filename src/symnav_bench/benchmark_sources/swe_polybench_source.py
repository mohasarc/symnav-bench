from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from symnav_bench.study import FitTier


TYPESCRIPT_LANGUAGE = "TypeScript"
HIGH_TIER_MODIFIED_NODES = 6
HIGH_TIER_DECLARATION_CHANGES = 4


@dataclass(frozen=True)
class PolybenchChangeShape:
    is_no_nodes: bool
    is_single_func: bool
    is_single_class: bool
    num_func_changes: int
    num_class_changes: int
    modified_nodes: int


@dataclass(frozen=True)
class PolybenchInstance:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    test_patch: str
    f2p: tuple[str, ...]
    p2p: tuple[str, ...]
    test_command: str
    dockerfile: str
    change_shape: PolybenchChangeShape


def fit_tier(shape: PolybenchChangeShape) -> FitTier:
    if shape.is_no_nodes or shape.is_single_func or shape.is_single_class:
        return "low"
    if shape.modified_nodes >= HIGH_TIER_MODIFIED_NODES:
        return "high"
    if shape.num_func_changes + shape.num_class_changes >= HIGH_TIER_DECLARATION_CHANGES:
        return "high"
    return "mid"


def parse_polybench_rows(rows: Iterable[dict[str, Any]]) -> tuple[PolybenchInstance, ...]:
    return tuple(
        parse_polybench_row(row)
        for row in rows
        if row.get("language") == TYPESCRIPT_LANGUAGE
    )


def parse_polybench_row(row: dict[str, Any]) -> PolybenchInstance:
    instance_id = row.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        raise ValueError("swe-polybench row is missing instance_id")
    return PolybenchInstance(
        instance_id=instance_id,
        repo=row_string(row, "repo", instance_id),
        base_commit=row_string(row, "base_commit", instance_id),
        problem_statement=row_string(row, "problem_statement", instance_id),
        test_patch=row_string(row, "test_patch", instance_id),
        f2p=row_name_list(row, "F2P", instance_id),
        p2p=row_name_list(row, "P2P", instance_id),
        test_command=row_string(row, "test_command", instance_id),
        dockerfile=row_string(row, "Dockerfile", instance_id),
        change_shape=parse_change_shape(row, instance_id),
    )


def parse_change_shape(row: dict[str, Any], instance_id: str) -> PolybenchChangeShape:
    return PolybenchChangeShape(
        is_no_nodes=row_boolean(row, "is_no_nodes", instance_id),
        is_single_func=row_boolean(row, "is_single_func", instance_id),
        is_single_class=row_boolean(row, "is_single_class", instance_id),
        num_func_changes=row_integer(row, "num_func_changes", instance_id),
        num_class_changes=row_integer(row, "num_class_changes", instance_id),
        modified_nodes=len(row_name_list(row, "modified_nodes", instance_id)),
    )


def row_string(row: dict[str, Any], column: str, instance_id: str) -> str:
    value = row.get(column)
    if not isinstance(value, str) or not value:
        raise row_error(column, instance_id, "a non-empty string")
    return value


def row_boolean(row: dict[str, Any], column: str, instance_id: str) -> bool:
    value = row.get(column)
    if value == "True":
        return True
    if value == "False":
        return False
    raise row_error(column, instance_id, "'True' or 'False'")


def row_integer(row: dict[str, Any], column: str, instance_id: str) -> int:
    value = row.get(column)
    if not isinstance(value, str) or not value.isdigit():
        raise row_error(column, instance_id, "a non-negative integer")
    return int(value)


def row_name_list(row: dict[str, Any], column: str, instance_id: str) -> tuple[str, ...]:
    value = row.get(column)
    if not isinstance(value, str) or not value:
        raise row_error(column, instance_id, "a list literal")
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        raise row_error(column, instance_id, "a list literal") from None
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise row_error(column, instance_id, "a list of strings")
    return tuple(parsed)


def row_error(column: str, instance_id: str, expectation: str) -> ValueError:
    return ValueError(
        f"swe-polybench instance {instance_id!r}: column {column!r} must be {expectation}"
    )
