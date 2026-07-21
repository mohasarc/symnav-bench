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
)

LOGS_DIR = Path(__file__).parent / "fixtures" / "multi_swe_logs"

PARSE_SUITE = "tests/generators/utils/parse.tests.ts"
MUI_STYLE_TEST = (
    "/home/material-ui/packages/mui-system/src/styleFunctionSx/"
    "styleFunctionSx.test.js:styleFunctionSx system resolves system "
)


def fixture_log(name: str) -> str:
    return (LOGS_DIR / name).read_text(encoding="utf-8")


def test_jest_darkreader_parser_reads_suites_and_suite_prefixed_tests() -> None:
    outcomes = parse_test_log("jest-darkreader", fixture_log("jest_darkreader_pass.log"))

    assert outcomes.passed == frozenset(
        {
            "tests/utils/time.tests.ts",
            "tests/utils/time.tests.ts:Time parse",
            "tests/utils/time.tests.ts:Nigth check",
            "tests/config/config.tests.ts",
            "tests/config/config.tests.ts:Dark Sites list",
            PARSE_SUITE,
            PARSE_SUITE + ":Base64 in CSS",
            PARSE_SUITE + ":Implied wildcards",
        }
    )
    assert outcomes.failed == frozenset()
    assert outcomes.skipped == frozenset()


def test_jest_darkreader_parser_marks_failing_suite_and_test() -> None:
    outcomes = parse_test_log(
        "jest-darkreader", fixture_log("jest_darkreader_f2p_failure.log")
    )

    assert outcomes.failed == frozenset(
        {PARSE_SUITE, PARSE_SUITE + ":Base64 in CSS"}
    )
    assert outcomes.passed == frozenset(
        {
            "tests/utils/time.tests.ts",
            "tests/utils/time.tests.ts:Time parse",
            PARSE_SUITE + ":Implied wildcards",
        }
    )


def test_jest_darkreader_parser_rejects_test_line_without_suite() -> None:
    with pytest.raises(ValueError, match="without suite"):
        parse_test_log("jest-darkreader", "✓ orphan test (1 ms)")


def test_vitest_vuejs_parser_reads_full_test_chains_and_strips_durations() -> None:
    outcomes = parse_test_log("vitest-vuejs", fixture_log("vitest_vuejs.log"))

    assert outcomes.passed == frozenset(
        {
            "packages/runtime-core/__tests__/components/Suspense.spec.ts > Suspense "
            "> mounted/updated hooks & fallback component",
            "packages/compiler-sfc/__tests__/compileStyle.spec.ts > SFC scoped CSS "
            "> nesting selector with atrule and comment",
            "packages/server-renderer/__tests__/render.spec.ts > "
            "ssr: renderToNodeStream > components > option components returning "
            "render from setup",
        }
    )
    assert outcomes.failed == frozenset(
        {
            "packages/runtime-core/__tests__/components/Suspense.spec.ts > Suspense "
            "> nested suspense (child resolves first)"
        }
    )


def test_mocha_mui_parser_joins_file_and_full_title_from_embedded_json() -> None:
    outcomes = parse_test_log("mocha-mui", fixture_log("mocha_mui.log"))

    assert (
        "/home/material-ui/packages/mui-styles/src/createGenerateClassName/"
        "createGenerateClassNameHash.test.js:createGenerateClassNameHash "
        "classNamePrefix should work without a classNamePrefix"
    ) in outcomes.passed
    assert (
        "/home/material-ui/packages/mui-system/src/borders.test.js:borders should work"
    ) in outcomes.failed
    assert (
        "/home/material-ui/packages/mui-material/src/ImageListItemBar/"
        "ImageListItemBar.test.js:<ImageListItemBar /> props: prop: subtitle "
        "should render a subtitle"
    ) in outcomes.skipped


def test_mocha_mui_parser_lets_failure_win_over_retry_pass() -> None:
    outcomes = parse_test_log("mocha-mui", fixture_log("mocha_mui.log"))

    assert MUI_STYLE_TEST in outcomes.failed
    assert MUI_STYLE_TEST not in outcomes.passed


@pytest.mark.parametrize("parser", ["jest-darkreader", "vitest-vuejs", "mocha-mui"])
def test_log_without_test_output_parses_to_empty_outcomes(parser: str) -> None:
    log = "npm ERR! missing script\nContainer exited with status code: 1\n"

    assert parse_test_log(parser, log) == TestOutcomes.of()


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


def darkreader_config() -> dict[str, object]:
    return {
        "base_commit": "c" * 40,
        "benchmark": "multi-swe-bench",
        "docker_image": "docker.io/mswebench/darkreader_m_darkreader@sha256:" + "a" * 64,
        "f2p": [PARSE_SUITE + ":Base64 in CSS", PARSE_SUITE],
        "log_parser": "jest-darkreader",
        "p2p": ["tests/utils/time.tests.ts:Time parse", "tests/utils/time.tests.ts"],
        "test_command": "bash /home/run.sh",
        "workdir": "/home/darkreader",
    }


def test_grade_subcommand_scores_passing_multi_swe_run(tmp_path: Path) -> None:
    env = grading_dirs(
        tmp_path, darkreader_config(), fixture_log("jest_darkreader_pass.log")
    )

    run_grade_script(env, "grade")

    reward = json.loads((tmp_path / "verifier" / "reward.json").read_text())
    assert reward["reward"] == 1
    assert reward["f2p"] == 1.0
    assert reward["p2p"] == 1.0
    assert reward["partial"] == 1.0


def test_grade_subcommand_scores_f2p_failure_with_fractions(tmp_path: Path) -> None:
    env = grading_dirs(
        tmp_path, darkreader_config(), fixture_log("jest_darkreader_f2p_failure.log")
    )

    run_grade_script(env, "grade")

    reward = json.loads((tmp_path / "verifier" / "reward.json").read_text())
    assert reward["reward"] == 0
    assert reward["f2p"] == 0.0
    assert reward["p2p"] == 1.0
    assert reward["partial"] == 0.5
