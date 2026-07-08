from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

from symnav_bench import __version__
from symnav_bench.report.cell_set import CellSet
from symnav_bench.report.comparison import planned_comparisons
from symnav_bench.report.render import write_report
from symnav_bench.run.auth import validate_auth
from symnav_bench.run.config import RunConfig
from symnav_bench.run.runner import CellRunner, subprocess_pier_run
from symnav_bench.run.symnav_ref import resolve_symnav_ref
from symnav_bench.run_spec import AgentSpec, parse_conditions
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
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="symnav-bench")
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command")

    list_parser = subcommands.add_parser("list-tasks")
    list_parser.add_argument("--tasks-dir", type=Path, default=default_tasks_dir())

    run_parser = subcommands.add_parser("run")
    run_parser.add_argument("--agent", action="append", required=True)
    run_parser.add_argument("--conditions", default="symnav,stock")
    run_parser.add_argument("--tasks", required=True)
    run_parser.add_argument("--tasks-dir", type=Path, default=default_tasks_dir())
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
    return parser


def default_tasks_dir() -> Path:
    return Path(os.environ.get("DEEPSWE_TASKS_DIR", "tasks"))


def list_tasks_command(args: argparse.Namespace) -> int:
    for task in list_tasks(args.tasks_dir):
        print(task)
    return 0


def run_command(args: argparse.Namespace) -> int:
    symnav_sha = resolve_symnav_ref(args.symnav_ref)
    specs = [AgentSpec.parse(value) for value in args.agent]
    validate_auth(specs, os.environ)
    tasks = list_tasks(args.tasks_dir) if args.tasks == "all" else split_csv(args.tasks)
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
        tasks_dir=args.tasks_dir,
    )
    runner = CellRunner.from_environment(
        config=config,
        pier=subprocess_pier_run,
        image_version=os.environ.get("SYMNAV_BENCH_VERSION", __version__),
        deep_swe_ref=args.deep_swe_ref,
        symnav_ref=symnav_sha,
    )
    runner.run_all()
    return 0


def report_command(args: argparse.Namespace) -> int:
    cells = CellSet.load(args.cells)
    comparisons = planned_comparisons(cells, split_csv(args.compare) if args.compare else None)
    write_report(comparisons, cells, args.out)
    return 0


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
