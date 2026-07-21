from __future__ import annotations

import ast
import csv
import sys
import tempfile
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symnav_bench.benchmark_sources import BenchmarkTaskSource
from symnav_bench.benchmark_sources.grading import grade_script_source
from symnav_bench.benchmark_sources.pier_task_writer import (
    MaterializedTaskSpec,
    write_pier_task_dir,
)
from symnav_bench.container_registry import (
    GHCR_HOST,
    GHCR_TOKEN_URL,
    RegistryDigestResolver,
    resolve_ghcr_image_digest,
)
from symnav_bench.dataset_fetch import fetch_dataset_files, list_dataset_files
from symnav_bench.study import BenchmarkSelection, FitTier
from symnav_bench.suite import (
    SuiteManifest,
    TaskManifestEntry,
    directory_checksum,
    suite_fingerprint,
)


DATASET_REPO_ID = "AmazonScience/SWE-PolyBench"
TYPESCRIPT_LANGUAGE = "TypeScript"
HIGH_TIER_MODIFIED_NODES = 6
HIGH_TIER_DECLARATION_CHANGES = 4
EVAL_IMAGE_REGISTRY = "ghcr.io"
EVAL_IMAGE_TAG = "latest"

REPO_LOG_PARSERS = {
    "microsoft/vscode": "mocha",
    "angular/angular": "bazel-angular",
    "mui/material-ui": "mocha-filename",
    "tailwindlabs/tailwindcss": "jest-tailwind",
    "coder/code-server": "jest",
}


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


RowLoader = Callable[[str], Iterable[dict[str, Any]]]
ImageResolver = Callable[[str], str | None]
WorkdirResolver = Callable[[str], str]


class SwePolybenchTaskSource(BenchmarkTaskSource):
    def __init__(
        self,
        selection: BenchmarkSelection,
        load_rows: RowLoader | None = None,
        resolve_image: ImageResolver | None = None,
        suite: SuiteManifest | None = None,
        resolve_workdir: WorkdirResolver | None = None,
    ) -> None:
        super().__init__(selection)
        self.load_rows = load_rows
        self.resolve_image = resolve_image
        self.suite = suite
        self.resolve_workdir = resolve_workdir

    def workdir_resolver(self) -> WorkdirResolver:
        if self.resolve_workdir is not None:
            return self.resolve_workdir
        registry = RegistryDigestResolver(GHCR_TOKEN_URL, GHCR_HOST)
        return lambda image: ghcr_image_working_dir(image, registry)

    def resolve(self) -> SuiteManifest:
        if not self.selection.tiers:
            raise ValueError("swe-polybench selection requires fit tiers")
        selected = select_instances(self.load_instances(), self.selection.tiers)
        images = self.resolve_images(selected)
        available = [
            instance for instance in selected if images[instance.instance_id] is not None
        ]
        excluded = [
            instance.instance_id
            for instance in selected
            if images[instance.instance_id] is None
        ]
        if excluded:
            print(
                f"swe-polybench: excluded {len(excluded)} of {len(selected)} selected "
                "tasks with no published eval image:",
                file=sys.stderr,
            )
            for instance_id in excluded:
                print(f"  {instance_id}", file=sys.stderr)
        if not available:
            raise ValueError(
                "swe-polybench tier selection matched no tasks with published "
                "eval images"
            )
        resolve_workdir = self.workdir_resolver()
        tasks = tuple(
            resolved_task_entry(
                instance,
                require_image(images, instance.instance_id),
                resolve_workdir,
            )
            for instance in available
        )
        return SuiteManifest(
            benchmark="swe-polybench",
            source_revision=self.selection.source_revision,
            tasks=tasks,
            fingerprint=suite_fingerprint(
                "swe-polybench", self.selection.source_revision, tasks
            ),
        )

    def ensure_tasks_dir(self, slugs: Sequence[str], workdir: Path) -> Path:
        if self.suite is None:
            raise ValueError(
                "swe-polybench task materialization requires the declared suite "
                "for checksum verification"
            )
        declared = {task.slug: task for task in self.suite.tasks}
        for slug in slugs:
            if slug not in declared:
                raise ValueError(f"task {slug!r} is not part of the declared suite")
        instances = {
            instance.instance_id: instance for instance in self.load_instances()
        }
        for slug in slugs:
            instance = instances.get(slug)
            if instance is None:
                raise ValueError(
                    f"task {slug!r} is missing from the pinned dataset revision"
                )
            image = self.image_resolver()(slug)
            if image is None:
                raise ValueError(f"eval image for task {slug!r} is no longer published")
            task_dir = materialize_instance(
                instance,
                image,
                workdir / slug,
                image_working_dir(instance, image, self.workdir_resolver()),
            )
            if directory_checksum(task_dir) != declared[slug].checksum:
                raise ValueError(
                    f"materialized task {slug!r} does not match the declared suite "
                    "(dataset content or eval image changed since declaration)"
                )
        return workdir

    def load_instances(self) -> tuple[PolybenchInstance, ...]:
        load_rows = self.load_rows if self.load_rows is not None else load_dataset_rows
        return parse_polybench_rows(load_rows(self.selection.source_revision))

    def image_resolver(self) -> ImageResolver:
        return self.resolve_image if self.resolve_image is not None else resolve_eval_image

    def resolve_images(
        self, instances: Sequence[PolybenchInstance]
    ) -> dict[str, str | None]:
        resolve_image = self.image_resolver()
        return {
            instance.instance_id: resolve_image(instance.instance_id)
            for instance in instances
        }


def select_instances(
    instances: Iterable[PolybenchInstance], tiers: Sequence[FitTier]
) -> tuple[PolybenchInstance, ...]:
    wanted = set(tiers)
    selected = sorted(
        (instance for instance in instances if fit_tier(instance.change_shape) in wanted),
        key=lambda instance: instance.instance_id,
    )
    if not selected:
        raise ValueError(
            f"swe-polybench tier selection {sorted(wanted)} matched no tasks"
        )
    return tuple(selected)


def require_image(images: dict[str, str | None], instance_id: str) -> str:
    image = images[instance_id]
    if image is None:
        raise ValueError(f"eval image for task {instance_id!r} is no longer published")
    return image


def eval_image_repository(instance_id: str) -> str:
    return "timesler/swe-polybench.eval.x86_64." + instance_id.lower()


def resolve_eval_image(instance_id: str) -> str | None:
    repository = eval_image_repository(instance_id)
    digest = resolve_ghcr_image_digest(repository, EVAL_IMAGE_TAG)
    if digest is None:
        return None
    return f"{EVAL_IMAGE_REGISTRY}/{repository}@{digest}"


def log_parser_for(instance: PolybenchInstance) -> str:
    parser = REPO_LOG_PARSERS.get(instance.repo)
    if parser is None:
        raise ValueError(
            f"swe-polybench instance {instance.instance_id!r}: no log parser "
            f"registered for repo {instance.repo!r}"
        )
    return parser


def ghcr_image_working_dir(image: str, registry: RegistryDigestResolver) -> str:
    reference = image.removeprefix(f"{EVAL_IMAGE_REGISTRY}/")
    repository, _, digest = reference.partition("@")
    return registry.image_working_dir(repository, digest)


def image_working_dir(
    instance: PolybenchInstance, image: str, resolve_workdir: WorkdirResolver
) -> str:
    working_dir = resolve_workdir(image)
    if not working_dir:
        raise ValueError(
            f"swe-polybench instance {instance.instance_id!r}: eval image "
            f"{image!r} declares no working dir"
        )
    return working_dir


def materialize_instance(
    instance: PolybenchInstance,
    docker_image: str,
    task_dir: Path,
    working_dir: str,
) -> Path:
    spec = MaterializedTaskSpec(
        benchmark="swe-polybench",
        slug=instance.instance_id,
        instruction=instance.problem_statement,
        docker_image=docker_image,
        workdir=working_dir,
        base_commit=instance.base_commit,
        test_patch=instance.test_patch,
        f2p=instance.f2p,
        p2p=instance.p2p,
        test_command=instance.test_command,
        log_parser=log_parser_for(instance),
        grade_script=grade_script_source(),
    )
    return write_pier_task_dir(spec, task_dir)


def resolved_task_entry(
    instance: PolybenchInstance, image: str, resolve_workdir: WorkdirResolver
) -> TaskManifestEntry:
    with tempfile.TemporaryDirectory(prefix="swe-polybench-resolve-") as scratch:
        task_dir = materialize_instance(
            instance,
            image,
            Path(scratch) / instance.instance_id,
            image_working_dir(instance, image, resolve_workdir),
        )
        checksum = directory_checksum(task_dir)
    return TaskManifestEntry(
        slug=instance.instance_id,
        language="typescript",
        checksum=checksum,
        tier=fit_tier(instance.change_shape),
    )


def load_dataset_rows(revision: str) -> Iterator[dict[str, Any]]:
    csv.field_size_limit(sys.maxsize)
    with tempfile.TemporaryDirectory(prefix="swe-polybench-") as download_dir:
        csv_paths = [
            path
            for path in list_dataset_files(DATASET_REPO_ID, revision)
            if path.endswith(".csv")
        ]
        if not csv_paths:
            raise ValueError(
                f"no csv data files found in {DATASET_REPO_ID} at revision {revision}"
            )
        files = fetch_dataset_files(
            DATASET_REPO_ID, revision, csv_paths, Path(download_dir)
        )
        for file in files:
            with file.open(newline="", encoding="utf-8") as handle:
                yield from csv.DictReader(handle)


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
