from __future__ import annotations

import pytest

from symnav_bench.benchmark_sources.swe_polybench_source import (
    PolybenchChangeShape,
    fit_tier,
    parse_polybench_rows,
)


def change_shape(
    *,
    is_no_nodes: bool = False,
    is_single_func: bool = False,
    is_single_class: bool = False,
    num_func_changes: int = 2,
    num_class_changes: int = 1,
    modified_nodes: int = 2,
) -> PolybenchChangeShape:
    return PolybenchChangeShape(
        is_no_nodes=is_no_nodes,
        is_single_func=is_single_func,
        is_single_class=is_single_class,
        num_func_changes=num_func_changes,
        num_class_changes=num_class_changes,
        modified_nodes=modified_nodes,
    )


def dataset_row(**overrides: str) -> dict[str, str]:
    row = {
        "instance_id": "microsoft__vscode-106767",
        "repo": "microsoft/vscode",
        "pull_number": "106767",
        "base_commit": "c" * 40,
        "patch": "diff --git a/src/main.ts b/src/main.ts",
        "test_patch": "diff --git a/test.ts b/test.ts",
        "problem_statement": "statement",
        "language": "TypeScript",
        "Dockerfile": "FROM node:18",
        "P2P": "['suite keeps the old case', 'suite keeps another case']",
        "F2P": "['suite renders the fixed case']",
        "F2F": "[]",
        "test_command": "yarn test --run suite",
        "task_category": "Bug Fix",
        "is_no_nodes": "False",
        "is_single_func": "False",
        "is_single_class": "False",
        "num_func_changes": "2",
        "num_class_changes": "1",
        "modified_nodes": '["a.ts->program->f1", "a.ts->program->f2"]',
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        (change_shape(is_single_func=True, modified_nodes=9), "low"),
        (change_shape(is_single_class=True, num_func_changes=9), "low"),
        (
            change_shape(
                is_no_nodes=True,
                modified_nodes=9,
                num_func_changes=9,
                num_class_changes=9,
            ),
            "low",
        ),
        (change_shape(modified_nodes=6, num_func_changes=1, num_class_changes=0), "high"),
        (change_shape(modified_nodes=2, num_func_changes=3, num_class_changes=1), "high"),
        (change_shape(modified_nodes=5, num_func_changes=2, num_class_changes=1), "mid"),
    ],
)
def test_fit_tier_assigns_exactly_one_tier_per_branch(
    shape: PolybenchChangeShape, expected: str
) -> None:
    assert fit_tier(shape) == expected


def test_parse_rows_keeps_only_typescript_rows() -> None:
    rows = [
        dataset_row(instance_id="ts-1", language="TypeScript"),
        dataset_row(instance_id="js-1", language="JavaScript"),
        dataset_row(instance_id="java-1", language="Java"),
        dataset_row(instance_id="py-1", language="Python"),
    ]

    instances = parse_polybench_rows(rows)

    assert [instance.instance_id for instance in instances] == ["ts-1"]


def test_parse_rows_reads_instance_fields_and_change_shape() -> None:
    instance = parse_polybench_rows([dataset_row()])[0]

    assert instance.instance_id == "microsoft__vscode-106767"
    assert instance.repo == "microsoft/vscode"
    assert instance.base_commit == "c" * 40
    assert instance.problem_statement == "statement"
    assert instance.test_patch == "diff --git a/test.ts b/test.ts"
    assert instance.f2p == ("suite renders the fixed case",)
    assert instance.p2p == ("suite keeps the old case", "suite keeps another case")
    assert instance.test_command == "yarn test --run suite"
    assert instance.dockerfile == "FROM node:18"
    assert instance.change_shape == change_shape(
        num_func_changes=2, num_class_changes=1, modified_nodes=2
    )


@pytest.mark.parametrize(
    "column",
    [
        "is_no_nodes",
        "is_single_func",
        "is_single_class",
        "num_func_changes",
        "num_class_changes",
        "modified_nodes",
    ],
)
def test_missing_change_shape_column_errors_naming_the_instance(column: str) -> None:
    row = dataset_row()
    del row[column]

    with pytest.raises(ValueError, match="microsoft__vscode-106767") as error:
        parse_polybench_rows([row])
    assert column in str(error.value)


@pytest.mark.parametrize(
    "column",
    [
        "is_no_nodes",
        "is_single_func",
        "is_single_class",
        "num_func_changes",
        "num_class_changes",
        "modified_nodes",
    ],
)
def test_empty_change_shape_value_errors_naming_the_instance(column: str) -> None:
    row = dataset_row(**{column: ""})

    with pytest.raises(ValueError, match="microsoft__vscode-106767"):
        parse_polybench_rows([row])


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("is_single_func", "yes"),
        ("num_func_changes", "two"),
        ("modified_nodes", "not a list"),
        ("modified_nodes", "3"),
        ("F2P", "not a list"),
        ("P2P", "['name', 3]"),
    ],
)
def test_malformed_row_value_errors_naming_the_instance(column: str, value: str) -> None:
    row = dataset_row(**{column: value})

    with pytest.raises(ValueError, match="microsoft__vscode-106767"):
        parse_polybench_rows([row])


def test_f2f_column_present_absent_or_populated_is_tolerated() -> None:
    with_empty_f2f = dataset_row()
    without_f2f = dataset_row()
    del without_f2f["F2F"]
    with_populated_f2f = dataset_row(F2F="['suite stays broken']")

    parsed = [
        parse_polybench_rows([row])
        for row in (with_empty_f2f, without_f2f, with_populated_f2f)
    ]

    assert parsed[0] == parsed[1] == parsed[2]
