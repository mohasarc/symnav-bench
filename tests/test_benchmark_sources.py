from __future__ import annotations

from pathlib import Path

import pytest

from symnav_bench.benchmark_sources import BenchmarkTaskSource, benchmark_task_source
from symnav_bench.benchmark_sources.deepswe_source import DeepsweTaskSource
from symnav_bench.study import BenchmarkSelection
from symnav_bench.suite import build_suite_manifest


DEEPSWE_SELECTION = BenchmarkSelection(name="deepswe", source_revision="a" * 40, tiers=None)


def test_factory_returns_deepswe_source_for_deepswe_selection() -> None:
    source = benchmark_task_source(DEEPSWE_SELECTION)
    assert isinstance(source, DeepsweTaskSource)
    assert isinstance(source, BenchmarkTaskSource)
    assert source.selection == DEEPSWE_SELECTION


@pytest.mark.parametrize(
    "selection",
    [
        BenchmarkSelection(name="multi-swe-bench", source_revision="b" * 40, tiers=None),
    ],
)
def test_factory_rejects_benchmarks_without_a_registered_source(
    selection: BenchmarkSelection,
) -> None:
    with pytest.raises(ValueError, match=f"no task source registered for benchmark '{selection.name}'"):
        benchmark_task_source(selection)


def test_deepswe_source_ensures_tasks_via_existing_clone_path(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        commands.append(command)
        if command[:2] == ["git", "clone"]:
            (tmp_path / "deep-swe" / ".git").mkdir(parents=True)
            (tmp_path / "deep-swe" / "tasks").mkdir()

    source = DeepsweTaskSource(DEEPSWE_SELECTION, runner=runner)
    tasks_dir = source.ensure_tasks_dir([], tmp_path / "deep-swe")

    assert tasks_dir == tmp_path / "deep-swe" / "tasks"
    assert commands[0][:3] == ["git", "clone", "--depth"]
    assert commands[1][-1] == "a" * 40
    assert commands[2][-1] == "FETCH_HEAD"


def test_deepswe_source_resolve_matches_build_suite_manifest(tmp_path, monkeypatch) -> None:
    checkout = tmp_path / "deep-swe"
    (checkout / ".git").mkdir(parents=True)
    tasks_dir = checkout / "tasks"
    write_task(tasks_dir / "alpha", "typescript", "alpha")
    write_task(tasks_dir / "zeta", "typescript", "zeta")
    monkeypatch.setenv("DEEPSWE_ROOT", str(checkout))

    source = DeepsweTaskSource(DEEPSWE_SELECTION, runner=lambda command: None)

    assert source.resolve() == build_suite_manifest(tasks_dir, "a" * 40)


def write_task(path: Path, language: str, source: str) -> None:
    (path / "nested").mkdir(parents=True)
    (path / "task.toml").write_text(
        f'[metadata]\nlanguage = "{language}"\n',
        encoding="utf-8",
    )
    (path / "nested" / "source.ts").write_text(source, encoding="utf-8")
