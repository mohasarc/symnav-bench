from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import sleep as real_sleep
from typing import Callable

from symnav_bench.batch_plan import TrialSlot, slot_id
from symnav_bench.cell_identity import CellIdentity
from symnav_bench.cells.attempt import AttemptIdentity, AttemptRecord
from symnav_bench.cells.normalize import HarnessMeta, normalize_attempt
from symnav_bench.run.config import RunConfig
from symnav_bench.run.job_config import HarnessIdentity, build_job_yaml
from symnav_bench.run.limits import find_limit_marker
from symnav_bench.agent_integrations import AgentIntegrationBundle, SymnavIntegrationCatalog
from symnav_bench.study import AgentConfiguration, StudyManifest
from symnav_bench.suite import TaskManifestEntry


PierRun = Callable[[Path, Path], None]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class StudyRunContext:
    configuration: AgentConfiguration
    tasks: dict[str, TaskManifestEntry]
    integration: AgentIntegrationBundle
    wall_clock_seconds: int
    deep_swe_sha: str

    @classmethod
    def from_environment(cls) -> "StudyRunContext | None":
        manifest_path = os.environ.get("SYMNAV_BENCH_STUDY_MANIFEST")
        suite_path = os.environ.get("SYMNAV_BENCH_SUITE_MANIFEST")
        symnav_checkout = os.environ.get("SYMNAV_BENCH_SYMNAV_CHECKOUT")
        configuration_id = os.environ.get("SYMNAV_BENCH_CONFIGURATION_ID")
        if not all((manifest_path, suite_path, symnav_checkout, configuration_id)):
            return None
        study = StudyManifest.load(Path(manifest_path))
        configuration = next(
            item for item in study.configurations if item.id == configuration_id
        )
        suite_data = json.loads(Path(suite_path).read_text(encoding="utf-8"))
        tasks = {
            item["slug"]: TaskManifestEntry(**item)
            for item in suite_data["tasks"]
        }
        return cls(
            configuration=configuration,
            tasks=tasks,
            integration=SymnavIntegrationCatalog.load(Path(symnav_checkout)).bundle("full"),
            wall_clock_seconds=study.protocol.wall_clock_seconds,
            deep_swe_sha=study.protocol.benchmark.source_revision,
        )


class CellRunner:
    def __init__(
        self,
        config: RunConfig,
        harness: HarnessIdentity | HarnessMeta,
        pier: PierRun,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        study_context: StudyRunContext | None = None,
    ) -> None:
        self.config = config
        self.harness = harness
        self.pier = pier
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleep = sleeper or real_sleep
        self.study_context = study_context

    @classmethod
    def from_environment(
        cls,
        config: RunConfig,
        pier: PierRun,
        image_version: str,
        deep_swe_ref: str,
        symnav_ref: str | None,
    ) -> "CellRunner":
        return cls(
            config=config,
            harness=HarnessMeta(
                image_version=image_version,
                pier_version=_pier_version(),
                deep_swe_ref=deep_swe_ref,
                symnav_ref=symnav_ref,
            ),
            pier=pier,
            study_context=StudyRunContext.from_environment(),
        )

    def run_all(self) -> list[AttemptRecord]:
        return [self.run_cell(cell) for cell in self.config.cells()]

    def run_cell(self, identity: CellIdentity) -> AttemptRecord:
        jobs_dir = Path(tempfile.mkdtemp(prefix="symnav-bench-jobs-"))
        job_yaml = jobs_dir / "job.yaml"
        condition = next(c for c in self.config.conditions if c.label == identity.condition_label)
        configuration = self.study_context.configuration if self.study_context else identity.spec
        task = self.study_context.tasks[identity.task] if self.study_context else identity.task
        job_yaml.write_text(
            build_job_yaml(
                configuration,
                condition,
                task,
                self.config.tasks_dir,
                self.study_context.integration if self.study_context else None,
                self.study_context.wall_clock_seconds if self.study_context else None,
            ),
            encoding="utf-8",
        )
        pier_error = None
        try:
            self.pier(job_yaml, jobs_dir)
        except Exception as error:
            marker = find_limit_marker(jobs_dir)
            pier_error = RuntimeError(f"UsageLimitError: {marker[:500]}") if marker else error
        trial_dir = find_trial_dir(jobs_dir)
        slot = self._slot(identity, condition.kind, condition.symnav_skill_variant)
        return normalize_attempt(
            trial_dir or jobs_dir,
            slot,
            _attempt_identity(slot),
            self._harness_identity(identity),
            pier_error,
            self.config.results_dir,
        )

    def _slot(self, identity: CellIdentity, condition_kind: str, variant: str) -> TrialSlot:
        condition = condition_kind if condition_kind == "stock" or variant == "all" else variant
        study_id = os.environ.get("SYMNAV_BENCH_STUDY_ID", "adhoc")
        configuration_id = os.environ.get("SYMNAV_BENCH_CONFIGURATION_ID", identity.spec.key)
        repetition = identity.rep + 1
        stable_slot_id = slot_id(
            study_id,
            configuration_id,
            condition,
            identity.task,
            repetition,
        )
        return TrialSlot(
            study_id=study_id,
            configuration_id=configuration_id,
            condition=condition,
            task=identity.task,
            repetition=repetition,
            slot_id=stable_slot_id,
        )

    def _harness_identity(self, identity: CellIdentity) -> HarnessIdentity:
        if isinstance(self.harness, HarnessIdentity):
            return self.harness
        context = self.study_context
        treatment = identity.condition_label != "stock"
        return HarnessIdentity(
            image_reference=self.harness.image_version,
            image_digest=os.environ.get("SYMNAV_BENCH_IMAGE_DIGEST", "unknown"),
            symnav_bench_sha=os.environ.get("SYMNAV_BENCH_SHA", self.harness.image_version),
            pier_version=self.harness.pier_version,
            deep_swe_sha=context.deep_swe_sha if context else self.harness.deep_swe_ref,
            symnav_sha=self.harness.symnav_ref,
            agent_name=identity.spec.agent,
            agent_version=context.configuration.agent_version if context else os.environ.get(f"{identity.spec.agent.upper()}_VERSION", "unknown"),
            bundle_id=context.integration.id if context and treatment else None,
            bundle_hash=context.integration.content_hash if context and treatment else None,
            task_checksum=context.tasks[identity.task].checksum if context else "unknown",
            prompt_rule_hash="unknown",
            requested_model=identity.spec.model,
            requested_effort=identity.spec.effort,
        )


def subprocess_pier_run(job_yaml: Path, jobs_dir: Path) -> None:
    subprocess.run(build_pier_run_command(job_yaml, jobs_dir), check=True)


def build_pier_run_command(job_yaml: Path, jobs_dir: Path) -> list[str]:
    return ["pier", "run", "--config", str(job_yaml), "--jobs-dir", str(jobs_dir), "--yes"]


def find_trial_dir(jobs_dir: Path) -> Path | None:
    result_paths = [
        path
        for path in jobs_dir.rglob("result.json")
        if (path.parent / "agent").exists()
        or (path.parent / "verifier").exists()
        or (path.parent / "steps").exists()
    ]
    if not result_paths:
        return None
    return max(result_paths, key=lambda path: path.stat().st_mtime).parent


def _attempt_identity(slot: TrialSlot) -> AttemptIdentity:
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    return AttemptIdentity(
        slot_id=slot.slot_id,
        attempt_id=uuid.uuid4().hex,
        github_run_id=os.environ.get("GITHUB_RUN_ID"),
        github_run_attempt=int(run_attempt) if run_attempt and run_attempt.isdigit() else None,
        github_job=os.environ.get("GITHUB_JOB"),
    )


def _pier_version() -> str:
    try:
        import datacurve_pier
    except Exception:
        return "unknown"
    return str(getattr(datacurve_pier, "__version__", "unknown"))
