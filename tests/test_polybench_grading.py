from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from symnav_bench.benchmark_sources.grading import grade_script_source
from symnav_bench.benchmark_sources.grading.grade_script import (
    TestOutcomes,
    parse_test_log,
    rewards,
)

LOGS_DIR = Path(__file__).parent / "fixtures" / "polybench_logs"

VSCODE_F2P = (
    "SuggestModel - TriggerAndCancelOracle Trigger (full) completions when "
    "(incomplete) completions are already active #99504"
)
MUI_PREFIX = "test/integration/MenuList.spec.js->"


def fixture_log(name: str) -> str:
    return (LOGS_DIR / name).read_text(encoding="utf-8")


def test_mocha_parser_reads_passes_and_failures() -> None:
    outcomes = parse_test_log("mocha", fixture_log("mocha_vscode_pass.log"))

    assert VSCODE_F2P in outcomes.passed
    assert "SuggestModel - Context Context - shouldAutoTrigger" in outcomes.passed
    assert len(outcomes.passed) == 4
    assert outcomes.failed == frozenset()
    assert outcomes.skipped == frozenset()

    failing = parse_test_log("mocha", fixture_log("mocha_vscode_f2p_failure.log"))

    assert VSCODE_F2P in failing.failed
    assert len(failing.passed) == 2


def test_mocha_filename_parser_prefixes_names_with_the_test_file() -> None:
    outcomes = parse_test_log("mocha-filename", fixture_log("mocha_filename_mui.log"))

    assert outcomes.passed == frozenset(
        {
            MUI_PREFIX + "<MenuList> integration keyboard controls and tabIndex "
            "manipulation should focus the third item",
            MUI_PREFIX + "<MenuList> integration keyboard controls and tabIndex "
            "manipulation should have the first item tabIndexed",
        }
    )
    assert outcomes.failed == frozenset(
        {
            MUI_PREFIX + "<MenuList> integration keyboard controls and tabIndex "
            "manipulation - preselected item should select/focus the second item"
        }
    )


def test_jest_tailwind_parser_joins_file_and_title() -> None:
    outcomes = parse_test_log(
        "jest-tailwind", fixture_log("jest_tailwind_p2p_regression.log")
    )

    assert outcomes.passed == frozenset(
        {
            "/testbed/__tests__/sanity.test.js->generates the right CSS with "
            "implicit screen utilities",
            "/testbed/__tests__/configFunction.test.js->a default value can be provided",
        }
    )
    assert outcomes.failed == frozenset(
        {"/testbed/__tests__/configFunction.test.js->it can accept a config file"}
    )


def test_jest_parser_joins_file_and_full_name_and_marks_pending_skipped() -> None:
    outcomes = parse_test_log("jest", fixture_log("jest_code_server.log"))

    assert outcomes.passed == frozenset(
        {
            "/testbed/test/unit/register.test.ts->register when navigator and "
            "serviceWorker are NOT defined should log an error",
            "/testbed/test/unit/health.test.ts->/healthz",
        }
    )
    assert outcomes.skipped == frozenset(
        {
            "/testbed/test/unit/register.test.ts->register when navigator and "
            "serviceWorker are defined should skip registration"
        }
    )


def test_bazel_angular_parser_reads_target_lines_and_strips_colors() -> None:
    outcomes = parse_test_log("bazel-angular", fixture_log("bazel_angular.log"))

    assert outcomes.passed == frozenset(
        {
            "/packages/compiler-cli/ngcc/test:test",
            "/packages/compiler/test/selector:selector",
        }
    )
    assert outcomes.failed == frozenset(
        {"/packages/core/test/bundling/injection:symbol_test"}
    )


@pytest.mark.parametrize("parser", ["mocha", "mocha-filename", "jest", "jest-tailwind"])
def test_log_without_report_parses_to_empty_outcomes(parser: str) -> None:
    outcomes = parse_test_log(parser, fixture_log("no_report.log"))

    assert outcomes == TestOutcomes.of()


def test_unknown_parser_is_rejected() -> None:
    with pytest.raises(ValueError, match="cucumber"):
        parse_test_log("cucumber", "")


def test_all_passing_buckets_reach_full_reward() -> None:
    outcomes = TestOutcomes.of(passed=("f1", "f2", "p1"))

    assert rewards(outcomes, ("f1", "f2"), ("p1",)) == {
        "reward": 1,
        "f2p_total": 2,
        "f2p_passed": 2,
        "p2p_total": 1,
        "p2p_passed": 1,
        "f2p": 1.0,
        "p2p": 1.0,
        "partial": 1.0,
    }


def test_one_f2p_failure_zeroes_reward_but_keeps_fractions() -> None:
    outcomes = TestOutcomes.of(passed=("f1", "p1"), failed=("f2",))

    result = rewards(outcomes, ("f1", "f2"), ("p1",))

    assert result["reward"] == 0
    assert result["f2p"] == 0.5
    assert result["p2p"] == 1.0
    assert result["partial"] == 2 / 3


def test_p2p_regression_zeroes_reward_despite_full_f2p() -> None:
    outcomes = TestOutcomes.of(passed=("f1",), failed=("p1",))

    result = rewards(outcomes, ("f1",), ("p1",))

    assert result["reward"] == 0
    assert result["f2p"] == 1.0
    assert result["p2p"] == 0.0


def test_absent_and_skipped_tests_count_as_failed() -> None:
    outcomes = TestOutcomes.of(passed=("f1",), skipped=("p1",))

    result = rewards(outcomes, ("f1", "f-absent"), ("p1",))

    assert result["reward"] == 0
    assert result["f2p_passed"] == 1
    assert result["p2p_passed"] == 0


def test_duplicate_report_entries_merge_worst_status_wins() -> None:
    outcomes = TestOutcomes.of(passed=("f1",), failed=("f1",))

    assert rewards(outcomes, ("f1",), ())["reward"] == 0


def test_empty_f2p_bucket_scores_zero() -> None:
    outcomes = TestOutcomes.of(passed=("p1",))

    result = rewards(outcomes, (), ("p1",))

    assert result["reward"] == 0
    assert result["f2p"] == 0.0
    assert result["p2p"] == 1.0
    assert result["partial"] == 1.0


def test_empty_p2p_bucket_passes_vacuously() -> None:
    outcomes = TestOutcomes.of(passed=("f1",))

    result = rewards(outcomes, ("f1",), ())

    assert result["reward"] == 1
    assert result["p2p"] == 1.0


def test_apply_failed_scores_zero_passes_with_marker() -> None:
    outcomes = TestOutcomes.of(passed=("f1", "p1"))

    result = rewards(outcomes, ("f1",), ("p1",), apply_failed=True)

    assert result == {
        "reward": 0,
        "f2p_total": 1,
        "f2p_passed": 0,
        "p2p_total": 1,
        "p2p_passed": 0,
        "f2p": 0.0,
        "p2p": 0.0,
        "partial": 0.0,
        "apply_failed": 1,
    }


def grading_dirs(
    tmp_path: Path, config: dict[str, object], run_log: str | None
) -> dict[str, str]:
    tests_dir = tmp_path / "tests"
    verifier_dir = tmp_path / "verifier"
    tests_dir.mkdir(exist_ok=True)
    verifier_dir.mkdir(exist_ok=True)
    (tests_dir / "grade.py").write_text(grade_script_source(), encoding="utf-8")
    (tests_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    if run_log is not None:
        (verifier_dir / "run.log").write_text(run_log, encoding="utf-8")
    return {
        "TESTS_DIR": str(tests_dir),
        "VERIFIER_DIR": str(verifier_dir),
        "ARTIFACTS_DIR": str(tmp_path / "artifacts"),
        "APP_DIR": str(tmp_path / "app"),
        "HOME": str(tmp_path),
        "PATH": os.environ["PATH"],
    }


def run_grade_script(env: dict[str, str], subcommand: str) -> None:
    subprocess.run(
        [sys.executable, env["TESTS_DIR"] + "/grade.py", subcommand],
        env=env,
        check=True,
        capture_output=True,
    )


def grading_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "base_commit": "b" * 40,
        "benchmark": "swe-polybench",
        "docker_image": "ghcr.io/example@sha256:" + "a" * 64,
        "f2p": [VSCODE_F2P],
        "log_parser": "mocha",
        "p2p": ["SuggestModel - Context Context - shouldAutoTrigger"],
        "test_command": "true",
        "workdir": "/testbed",
    }
    config.update(overrides)
    return config


def test_grade_subcommand_writes_reward_json_from_run_log(tmp_path: Path) -> None:
    env = grading_dirs(tmp_path, grading_config(), fixture_log("mocha_vscode_pass.log"))

    run_grade_script(env, "grade")

    reward = json.loads((tmp_path / "verifier" / "reward.json").read_text())
    assert reward["reward"] == 1
    assert reward["f2p"] == 1.0
    assert reward["p2p"] == 1.0
    assert reward["partial"] == 1.0


def test_grade_subcommand_scores_missing_run_log_as_all_failed(tmp_path: Path) -> None:
    env = grading_dirs(tmp_path, grading_config(), run_log=None)

    run_grade_script(env, "grade")

    reward = json.loads((tmp_path / "verifier" / "reward.json").read_text())
    assert reward["reward"] == 0
    assert reward["f2p"] == 0.0
    assert reward["p2p"] == 0.0


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return completed.stdout


def prepare_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "app"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    (repo / "source.txt").write_text("original\n", encoding="utf-8")
    git(repo, "add", "source.txt")
    git(repo, "commit", "-q", "-m", "base")
    base_commit = git(repo, "rev-parse", "HEAD").strip()

    (repo / "spec.txt").write_text("spec\n", encoding="utf-8")
    git(repo, "add", "spec.txt")
    test_patch = git(repo, "diff", "--cached")
    git(repo, "reset", "-q", "--hard", base_commit)

    (repo / "source.txt").write_text("fixed\n", encoding="utf-8")
    model_patch = git(repo, "diff")
    git(repo, "reset", "-q", "--hard", base_commit)
    return repo, base_commit, test_patch, model_patch


def test_prepare_applies_test_patch_then_model_patch(tmp_path: Path) -> None:
    repo, base_commit, test_patch, model_patch = prepare_repo(tmp_path)
    env = grading_dirs(tmp_path, grading_config(base_commit=base_commit), run_log=None)
    (Path(env["TESTS_DIR"]) / "test.patch").write_text(test_patch, encoding="utf-8")
    artifacts = Path(env["ARTIFACTS_DIR"])
    artifacts.mkdir()
    (artifacts / "model.patch").write_text(model_patch, encoding="utf-8")

    run_grade_script(env, "prepare")

    assert (repo / "spec.txt").read_text(encoding="utf-8") == "spec\n"
    assert (repo / "source.txt").read_text(encoding="utf-8") == "fixed\n"
    assert not (tmp_path / "verifier" / "reward.json").exists()


def test_prepare_grades_unappliable_model_patch_as_apply_failed(tmp_path: Path) -> None:
    repo, base_commit, test_patch, model_patch = prepare_repo(tmp_path)
    env = grading_dirs(tmp_path, grading_config(base_commit=base_commit), run_log=None)
    (Path(env["TESTS_DIR"]) / "test.patch").write_text(test_patch, encoding="utf-8")
    artifacts = Path(env["ARTIFACTS_DIR"])
    artifacts.mkdir()
    conflicting = model_patch.replace("original", "never-there")
    (artifacts / "model.patch").write_text(conflicting, encoding="utf-8")

    run_grade_script(env, "prepare")

    reward = json.loads((tmp_path / "verifier" / "reward.json").read_text())
    assert reward["reward"] == 0
    assert reward["apply_failed"] == 1
    assert (repo / "spec.txt").exists()


def test_prepare_resets_image_baked_edits_so_model_patch_applies(
    tmp_path: Path,
) -> None:
    repo, base_commit, test_patch, _ = prepare_repo(tmp_path)
    (repo / "source.txt").write_text("image-baked\nfixed\n", encoding="utf-8")
    model_patch = git(repo, "diff")
    git(repo, "reset", "-q", "--hard", base_commit)
    (repo / "source.txt").write_text("image-baked\n", encoding="utf-8")
    env = grading_dirs(tmp_path, grading_config(base_commit=base_commit), run_log=None)
    (Path(env["TESTS_DIR"]) / "test.patch").write_text(test_patch, encoding="utf-8")
    artifacts = Path(env["ARTIFACTS_DIR"])
    artifacts.mkdir()
    (artifacts / "model.patch").write_text(model_patch, encoding="utf-8")

    run_grade_script(env, "prepare")

    assert (repo / "source.txt").read_text(encoding="utf-8") == "image-baked\nfixed\n"
    assert (repo / "spec.txt").read_text(encoding="utf-8") == "spec\n"
    assert not (tmp_path / "verifier" / "reward.json").exists()


def test_prepare_without_model_patch_grades_pristine_state(tmp_path: Path) -> None:
    repo, base_commit, test_patch, _ = prepare_repo(tmp_path)
    env = grading_dirs(tmp_path, grading_config(base_commit=base_commit), run_log=None)
    (Path(env["TESTS_DIR"]) / "test.patch").write_text(test_patch, encoding="utf-8")

    run_grade_script(env, "prepare")

    assert (repo / "source.txt").read_text(encoding="utf-8") == "original\n"
    assert not (tmp_path / "verifier" / "reward.json").exists()


def test_prepare_without_patch_tool_still_scores_apply_failure(tmp_path: Path) -> None:
    repo, base_commit, test_patch, model_patch = prepare_repo(tmp_path)
    env = grading_dirs(tmp_path, grading_config(base_commit=base_commit), run_log=None)
    (Path(env["TESTS_DIR"]) / "test.patch").write_text(test_patch, encoding="utf-8")
    artifacts = Path(env["ARTIFACTS_DIR"])
    artifacts.mkdir()
    conflicting = model_patch.replace("original", "never-there")
    (artifacts / "model.patch").write_text(conflicting, encoding="utf-8")
    git_only_bin = tmp_path / "bin"
    git_only_bin.mkdir()
    git_path = subprocess.run(
        ["which", "git"], check=True, capture_output=True, text=True
    ).stdout.strip()
    (git_only_bin / "git").symlink_to(git_path)
    env["PATH"] = str(git_only_bin)

    run_grade_script(env, "prepare")

    reward = json.loads((tmp_path / "verifier" / "reward.json").read_text())
    assert reward["reward"] == 0
    assert reward["apply_failed"] == 1
