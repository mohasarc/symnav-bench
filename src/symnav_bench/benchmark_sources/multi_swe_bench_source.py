from __future__ import annotations

import json
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
    RegistryDigestResolver,
    docker_hub_digest_resolver,
)
from symnav_bench.dataset_fetch import fetch_dataset_files, list_dataset_files
from symnav_bench.study import BenchmarkSelection
from symnav_bench.suite import (
    SuiteManifest,
    TaskManifestEntry,
    directory_checksum,
    suite_fingerprint,
)


DATASET_REPO_ID = "ByteDance-Seed/Multi-SWE-bench"
TYPESCRIPT_DATA_PREFIX = "ts/"
DOCKER_HUB_NAMESPACE = "mswebench"
EVAL_IMAGE_REGISTRY = "docker.io"
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


def resolve_eval_image(
    instance: MultiSweInstance, registry: RegistryDigestResolver
) -> str | None:
    repository = eval_image_repository(instance)
    digest = registry.resolve(repository, eval_image_tag(instance))
    if digest is None:
        return None
    return f"{EVAL_IMAGE_REGISTRY}/{repository}@{digest}"


RowLoader = Callable[[str], Iterable[dict[str, Any]]]
ImageResolver = Callable[[MultiSweInstance], str | None]


class MultiSweBenchTaskSource(BenchmarkTaskSource):
    def __init__(
        self,
        selection: BenchmarkSelection,
        load_rows: RowLoader | None = None,
        resolve_image: ImageResolver | None = None,
        suite: SuiteManifest | None = None,
    ) -> None:
        super().__init__(selection)
        self.load_rows = load_rows
        self.resolve_image = resolve_image
        self.suite = suite

    def resolve(self) -> SuiteManifest:
        loaded = sorted(
            self.load_instances(), key=lambda instance: instance.instance_id
        )
        instances = [instance for instance in loaded if instance.f2p]
        ungradeable = [instance.instance_id for instance in loaded if not instance.f2p]
        if ungradeable:
            print(
                f"multi-swe-bench: excluded {len(ungradeable)} of {len(loaded)} "
                "tasks with no fail-to-pass tests:",
                file=sys.stderr,
            )
            for instance_id in ungradeable:
                print(f"  {instance_id}", file=sys.stderr)
        images = self.resolve_images(instances)
        available = [
            instance for instance in instances if images[instance.instance_id] is not None
        ]
        excluded = [
            instance.instance_id
            for instance in instances
            if images[instance.instance_id] is None
        ]
        if excluded:
            print(
                f"multi-swe-bench: excluded {len(excluded)} of {len(instances)} "
                "tasks with no published eval image:",
                file=sys.stderr,
            )
            for instance_id in excluded:
                print(f"  {instance_id}", file=sys.stderr)
        if not available:
            raise ValueError(
                "multi-swe-bench typescript set matched no tasks with published "
                "eval images"
            )
        tasks = tuple(
            resolved_task_entry(instance, require_image(images, instance.instance_id))
            for instance in available
        )
        return SuiteManifest(
            benchmark="multi-swe-bench",
            source_revision=self.selection.source_revision,
            tasks=tasks,
            fingerprint=suite_fingerprint(
                "multi-swe-bench", self.selection.source_revision, tasks
            ),
        )

    def ensure_tasks_dir(self, slugs: Sequence[str], workdir: Path) -> Path:
        if self.suite is None:
            raise ValueError(
                "multi-swe-bench task materialization requires the declared suite "
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
            image = self.image_resolver()(instance)
            if image is None:
                raise ValueError(f"eval image for task {slug!r} is no longer published")
            task_dir = materialize_instance(instance, image, workdir / slug)
            if directory_checksum(task_dir) != declared[slug].checksum:
                raise ValueError(
                    f"materialized task {slug!r} does not match the declared suite "
                    "(dataset content or eval image changed since declaration)"
                )
        return workdir

    def load_instances(self) -> tuple[MultiSweInstance, ...]:
        load_rows = self.load_rows if self.load_rows is not None else load_dataset_rows
        return parse_multi_swe_rows(load_rows(self.selection.source_revision))

    def image_resolver(self) -> ImageResolver:
        if self.resolve_image is not None:
            return self.resolve_image
        registry = docker_hub_digest_resolver()
        return lambda instance: resolve_eval_image(instance, registry)

    def resolve_images(
        self, instances: Sequence[MultiSweInstance]
    ) -> dict[str, str | None]:
        resolve_image = self.image_resolver()
        return {
            instance.instance_id: resolve_image(instance) for instance in instances
        }


def require_image(images: dict[str, str | None], instance_id: str) -> str:
    image = images[instance_id]
    if image is None:
        raise ValueError(f"eval image for task {instance_id!r} is no longer published")
    return image


def materialize_instance(
    instance: MultiSweInstance, docker_image: str, task_dir: Path
) -> Path:
    profile = execution_profile_for(instance)
    spec = MaterializedTaskSpec(
        benchmark="multi-swe-bench",
        slug=instance.instance_id,
        instruction=instance.problem_statement,
        docker_image=docker_image,
        workdir=profile.workdir,
        base_commit=instance.base_commit,
        test_patch=instance.test_patch,
        f2p=instance.f2p,
        p2p=instance.p2p,
        test_command=profile.test_command,
        log_parser=profile.log_parser,
        grade_script=grade_script_source(),
    )
    return write_pier_task_dir(spec, task_dir)


def resolved_task_entry(instance: MultiSweInstance, image: str) -> TaskManifestEntry:
    with tempfile.TemporaryDirectory(prefix="multi-swe-bench-resolve-") as scratch:
        task_dir = materialize_instance(
            instance, image, Path(scratch) / instance.instance_id
        )
        checksum = directory_checksum(task_dir)
    return TaskManifestEntry(
        slug=instance.instance_id,
        language="typescript",
        checksum=checksum,
    )


def load_dataset_rows(revision: str) -> Iterator[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="multi-swe-bench-") as download_dir:
        jsonl_paths = [
            path
            for path in list_dataset_files(DATASET_REPO_ID, revision)
            if path.startswith(TYPESCRIPT_DATA_PREFIX) and path.endswith(".jsonl")
        ]
        if not jsonl_paths:
            raise ValueError(
                f"no typescript jsonl data files found in {DATASET_REPO_ID} "
                f"at revision {revision}"
            )
        files = fetch_dataset_files(
            DATASET_REPO_ID, revision, jsonl_paths, Path(download_dir)
        )
        for file in files:
            with file.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        yield json.loads(line)


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
        f2p=row_test_names(row, "f2p_tests", instance_id),
        p2p=row_test_names(row, "p2p_tests", instance_id),
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
    row: dict[str, Any], column: str, instance_id: str
) -> tuple[str, ...]:
    value = row.get(column)
    if not isinstance(value, dict):
        raise row_error(column, instance_id, "a mapping of test names")
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
