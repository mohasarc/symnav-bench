from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import TextIO

from symnav_bench.build_identity import build_version_text
from symnav_bench.batch_plan import BatchPlan, TrialSlot, plan_balanced_batches, plan_trial_slots
from symnav_bench.cells.attempt import AttemptRecord
from symnav_bench.deepswe import TASK_SLUGS, configured_tasks_dir, ensure_deepswe_tasks
from symnav_bench.run.auth import validate_auth
from symnav_bench.run.config import RunConfig
from symnav_bench.run.runner import CellRunner, subprocess_pier_run
from symnav_bench.run.symnav_ref import resolve_symnav_ref
from symnav_bench.run_spec import AgentSpec, parse_conditions
from symnav_bench.study import StudyManifest, protocol_mapping
from symnav_bench.suite import SuiteManifest, build_suite_manifest
from symnav_bench.tasks import list_tasks


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list-tasks":
            return list_tasks_command(args)
        if args.command == "run":
            return run_command(args)
        if args.command == "report":
            return report_command(args)
        if args.command == "plan-study":
            return plan_study_command(args)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="symnav-bench")
    parser.add_argument("--version", action="version", version=build_version_text())
    subcommands = parser.add_subparsers(dest="command")

    list_parser = subcommands.add_parser("list-tasks")
    list_parser.add_argument("--tasks-dir", type=Path)

    run_parser = subcommands.add_parser("run")
    run_parser.add_argument("--agent", action="append", required=True)
    run_parser.add_argument("--conditions", default="symnav,stock")
    run_parser.add_argument("--tasks", required=True)
    run_parser.add_argument("--tasks-dir", type=Path)
    run_parser.add_argument("--results-dir", type=Path, required=True)
    run_parser.add_argument("--symnav-ref", default="main")
    run_parser.add_argument("--reps", type=int, default=1)
    run_parser.add_argument("--rep-start", type=int, default=0)
    run_parser.add_argument("--parallel", type=int, default=1)
    run_parser.add_argument("--timeout-multiplier", type=float)
    run_parser.add_argument("--max-limit-wait-minutes", type=int, default=240)
    run_parser.add_argument("--deep-swe-ref", default=os.environ.get("DEEPSWE_REF", "unknown"))

    report_parser = subcommands.add_parser("report")
    report_parser.add_argument("--cells", type=Path, required=True)
    report_parser.add_argument("--out", type=Path, required=True)
    report_parser.add_argument("--compare", default="")

    plan_study_parser = subcommands.add_parser("plan-study")
    plan_study_parser.add_argument("--study", type=Path, required=True)
    plan_study_parser.add_argument("--tasks-dir", type=Path, required=True)
    plan_study_parser.add_argument("--json", action="store_true")
    return parser


def list_tasks_command(args: argparse.Namespace) -> int:
    tasks_dir = args.tasks_dir or configured_tasks_dir()
    tasks = list_tasks(tasks_dir) if tasks_dir and tasks_dir.exists() else list(TASK_SLUGS)
    for task in tasks:
        print(task)
    return 0


def run_command(args: argparse.Namespace) -> int:
    symnav_sha = resolve_symnav_ref(args.symnav_ref)
    specs = [AgentSpec.parse(value) for value in args.agent]
    validate_auth(specs, os.environ)
    tasks_dir = args.tasks_dir or configured_tasks_dir() or ensure_deepswe_tasks(args.deep_swe_ref)
    tasks = list_tasks(tasks_dir) if args.tasks == "all" else split_csv(args.tasks)
    config = RunConfig(
        specs=specs,
        conditions=parse_conditions(args.conditions, symnav_sha),
        tasks=tasks,
        reps=args.reps,
        rep_start=args.rep_start,
        parallel=args.parallel,
        timeout_multiplier=args.timeout_multiplier,
        max_limit_wait=timedelta(minutes=args.max_limit_wait_minutes),
        results_dir=args.results_dir,
        tasks_dir=tasks_dir,
    )
    runner = CellRunner.from_environment(
        config=config,
        pier=subprocess_pier_run,
        image_version=os.environ.get("SYMNAV_BENCH_VERSION", __version__),
        deep_swe_ref=args.deep_swe_ref,
        symnav_ref=symnav_sha,
    )
    return run_exit_code(runner.run_all())


def report_command(args: argparse.Namespace) -> int:
    from symnav_bench.report.cell_set import CellSet
    from symnav_bench.report.comparison import planned_comparisons
    from symnav_bench.report.render import write_report

    cells = CellSet.load(args.cells)
    comparisons = planned_comparisons(cells, split_csv(args.compare) if args.compare else None)
    write_report(comparisons, cells, args.out)
    return 0


def plan_study_command(args: argparse.Namespace) -> int:
    study = StudyManifest.load(args.study)
    suite = build_suite_manifest(args.tasks_dir, study.protocol.deep_swe_sha)
    if args.json:
        write_study_plan(study, sys.stdout, suite=suite)
        return 0
    slots = plan_trial_slots(study, suite)
    print(
        f"{study.id}: {len(suite.tasks)} tasks, "
        f"{len(study.configurations)} configurations, {len(slots)} slots"
    )
    return 0


def write_study_plan(
    study: StudyManifest,
    out: TextIO,
    *,
    suite: SuiteManifest,
) -> None:
    slots = plan_trial_slots(study, suite)
    batches = [
        batch
        for configuration in study.configurations
        for batch in plan_balanced_batches(
            [slot for slot in slots if slot.configuration_id == configuration.id],
            randomization_seed=study.protocol.randomization_seed,
        )
    ]
    json.dump(
        study_plan_mapping(study, suite, slots, batches),
        out,
        indent=2,
        sort_keys=True,
    )
    out.write("\n")


def study_plan_mapping(
    study: StudyManifest,
    suite: SuiteManifest,
    slots: list[TrialSlot],
    batches: list[BatchPlan],
) -> dict:
    return {
        "study_id": study.id,
        "protocol_fingerprint": study.protocol_fingerprint(),
        "protocol": protocol_mapping(study.protocol),
        "suite": {
            "deep_swe_sha": suite.deep_swe_sha,
            "fingerprint": suite.fingerprint,
            "tasks": [asdict(task) for task in suite.tasks],
        },
        "configurations": [
            {
                "id": configuration.id,
                "agent": configuration.spec.agent,
                "model": configuration.spec.model,
                "effort": configuration.spec.effort,
                "agent_version": configuration.agent_version,
            }
            for configuration in study.configurations
        ],
        "slots": [asdict(slot) for slot in slots],
        "batches": [
            {
                "study_id": batch.study_id,
                "configuration_id": batch.configuration_id,
                "batch_id": batch.batch_id,
                "index": batch.index,
                "slot_ids": [slot.slot_id for slot in batch.slots],
            }
            for batch in batches
        ],
        "coverage": {
            "completed": 0,
            "total": len(slots),
            "fraction": 0.0,
        },
    }


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def run_exit_code(attempts: list[AttemptRecord]) -> int:
    return 1 if any(attempt.disposition.outcome == "retryable_error" for attempt in attempts) else 0


if __name__ == "__main__":
    raise SystemExit(main())
