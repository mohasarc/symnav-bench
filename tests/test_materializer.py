from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import pytest
from pier.models.task.config import TaskConfig
from pier.models.task.paths import TaskPaths

from symnav_bench.benchmark_sources.pier_task_writer import (
    MaterializedTaskSpec,
    write_pier_task_dir,
)
from symnav_bench.suite import directory_checksum

PINNED_IMAGE = (
    "ghcr.io/timesler/swe-polybench.eval.x86_64.mui__material-ui-7444@sha256:" + "a" * 64
)


def task_spec(**overrides: object) -> MaterializedTaskSpec:
    values: dict[str, object] = {
        "benchmark": "swe-polybench",
        "slug": "mui__material-ui-7444",
        "instruction": "Fix the MenuList focus handling.",
        "docker_image": PINNED_IMAGE,
        "workdir": "/testbed",
        "base_commit": "b" * 40,
        "test_patch": "diff --git a/test/a.js b/test/a.js\n",
        "f2p": ("suite renders the fixed case",),
        "p2p": ("suite keeps the old case", "suite keeps another case"),
        "test_command": (
            "yarn cross-env NODE_ENV=test mocha test/integration/MenuList.spec.js "
            "--reporter /testbed/custom-reporter.js --exit"
        ),
        "log_parser": "mocha-filename",
        "grade_script": "print('grade')\n",
    }
    values.update(overrides)
    return MaterializedTaskSpec(**values)  # type: ignore[arg-type]


MULTI_SWE_IMAGE = "docker.io/mswebench/vuejs_m_core@sha256:" + "b" * 64


def multi_swe_overrides() -> dict[str, object]:
    return {
        "benchmark": "multi-swe-bench",
        "slug": "vuejs__core-11899",
        "instruction": "fix(suspense): nested suspense",
        "docker_image": MULTI_SWE_IMAGE,
        "workdir": "/home/core",
        "test_command": "bash /home/run.sh",
        "log_parser": "vitest-vuejs",
    }


BENCHMARK_SPEC_OVERRIDES = [
    pytest.param({}, id="swe-polybench"),
    pytest.param(multi_swe_overrides(), id="multi-swe-bench"),
]


def write_task(tmp_path: Path, **overrides: object) -> Path:
    return write_pier_task_dir(task_spec(**overrides), tmp_path / "task")


def read_task_toml(task_dir: Path) -> dict[str, object]:
    return tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("overrides", BENCHMARK_SPEC_OVERRIDES)
def test_written_dir_is_a_valid_pier_task(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    task_dir = write_task(tmp_path, **overrides)

    assert TaskPaths(task_dir).is_valid()
    TaskConfig.model_validate_toml((task_dir / "task.toml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("overrides", BENCHMARK_SPEC_OVERRIDES)
def test_materialization_is_byte_deterministic(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    first = write_pier_task_dir(task_spec(**overrides), tmp_path / "first")
    second = write_pier_task_dir(task_spec(**overrides), tmp_path / "second")

    assert directory_checksum(first) == directory_checksum(second)


def test_checksum_is_sensitive_to_task_content(tmp_path: Path) -> None:
    original = write_pier_task_dir(task_spec(), tmp_path / "original")
    edited = write_pier_task_dir(
        task_spec(test_patch="diff --git a/test/b.js b/test/b.js\n"), tmp_path / "edited"
    )

    assert directory_checksum(original) != directory_checksum(edited)


def test_task_toml_pins_environment_and_verifier(tmp_path: Path) -> None:
    data = read_task_toml(write_task(tmp_path))

    environment = data["environment"]
    assert isinstance(environment, dict)
    assert "docker_image" not in environment
    assert environment["workdir"] == "/testbed"
    verifier = data["verifier"]
    assert isinstance(verifier, dict)
    assert verifier["environment_mode"] == "separate"
    metadata = data["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["language"] == "typescript"
    assert metadata["task_id"] == "mui__material-ui-7444"
    assert metadata["benchmark"] == "swe-polybench"
    assert metadata["base_commit_hash"] == "b" * 40
    assert data["artifacts"] == ["/logs/artifacts/model.patch"]
    assert "agent" not in data


def test_wall_clock_seconds_sets_agent_timeout(tmp_path: Path) -> None:
    data = read_task_toml(write_task(tmp_path, wall_clock_seconds=5400))

    agent = data["agent"]
    assert isinstance(agent, dict)
    assert agent["timeout_sec"] == 5400.0


def test_instruction_written_verbatim(tmp_path: Path) -> None:
    task_dir = write_task(tmp_path)

    written = (task_dir / "instruction.md").read_text(encoding="utf-8")
    assert written == "Fix the MenuList focus handling."


def test_environment_dockerfile_builds_from_pinned_image(tmp_path: Path) -> None:
    task_dir = write_task(tmp_path)

    dockerfile = (task_dir / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile == f"FROM {PINNED_IMAGE}\n"


def test_grading_inputs_land_in_tests_dir(tmp_path: Path) -> None:
    task_dir = write_task(tmp_path)

    config = json.loads((task_dir / "tests" / "config.json").read_text(encoding="utf-8"))
    assert config["benchmark"] == "swe-polybench"
    assert config["base_commit"] == "b" * 40
    assert config["docker_image"] == PINNED_IMAGE
    assert config["f2p"] == ["suite renders the fixed case"]
    assert config["p2p"] == ["suite keeps the old case", "suite keeps another case"]
    assert config["log_parser"] == "mocha-filename"
    assert config["workdir"] == "/testbed"
    grade = (task_dir / "tests" / "grade.py").read_text(encoding="utf-8")
    assert grade == "print('grade')\n"
    test_patch = (task_dir / "tests" / "test.patch").read_text(encoding="utf-8")
    assert test_patch == "diff --git a/test/a.js b/test/a.js\n"


def test_run_script_embeds_the_instance_test_command(tmp_path: Path) -> None:
    task_dir = write_task(tmp_path)

    run_script = (task_dir / "tests" / "run_tests.sh").read_text(encoding="utf-8")
    assert "cd /testbed" in run_script
    assert (
        "yarn cross-env NODE_ENV=test mocha test/integration/MenuList.spec.js "
        "--reporter /testbed/custom-reporter.js --exit" in run_script
    )


def test_verifier_script_prepares_runs_and_grades(tmp_path: Path) -> None:
    task_dir = write_task(tmp_path)

    test_script = (task_dir / "tests" / "test.sh").read_text(encoding="utf-8")
    assert "python3 /tests/grade.py prepare" in test_script
    assert "bash /tests/run_tests.sh" in test_script
    assert "Container exited with status code" in test_script
    assert "python3 /tests/grade.py grade" in test_script
    assert test_script.index("grade.py prepare") < test_script.index("run_tests.sh")
    assert test_script.index("run_tests.sh") < test_script.index("grade.py grade")


def test_pre_artifacts_falls_back_to_base_commit_without_baseline(
    tmp_path: Path,
) -> None:
    task_dir = write_task(tmp_path)

    pre_artifacts = (task_dir / "pre_artifacts.sh").read_text(encoding="utf-8")
    assert "cd /testbed" in pre_artifacts
    assert "symnav-bench-baseline-tree" in pre_artifacts
    assert "baseline_tree=" + "b" * 40 in pre_artifacts
    assert "/logs/artifacts/model.patch" in pre_artifacts


def test_shell_scripts_are_executable(tmp_path: Path) -> None:
    task_dir = write_task(tmp_path)

    for script in (
        task_dir / "pre_artifacts.sh",
        task_dir / "tests" / "test.sh",
        task_dir / "tests" / "run_tests.sh",
    ):
        assert os.access(script, os.X_OK)


def test_tests_dockerfile_bakes_verifier_inputs_into_pinned_image(
    tmp_path: Path,
) -> None:
    task_dir = write_task(tmp_path)

    dockerfile = (task_dir / "tests" / "Dockerfile").read_text(encoding="utf-8")
    lines = dockerfile.strip().splitlines()
    assert lines[0] == f"FROM {PINNED_IMAGE}"
    for name in ("test.sh", "run_tests.sh", "grade.py", "config.json", "test.patch"):
        assert f"COPY {name} /tests/{name}" in lines
    assert "RUN chmod +x /tests/test.sh /tests/run_tests.sh" in lines


def test_pre_artifacts_diffs_against_pre_agent_baseline(tmp_path: Path) -> None:
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        ).stdout

    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (repo / "source.txt").write_text("original\n", encoding="utf-8")
    git("add", "source.txt")
    git("commit", "-q", "-m", "base")

    (repo / "Dockerfile").write_text("FROM baked\n", encoding="utf-8")
    baseline_index = tmp_path / "baseline-index"
    subprocess.run(
        ["git", "-C", str(repo), "add", "-A"],
        check=True,
        env={**os.environ, "GIT_INDEX_FILE": str(baseline_index)},
    )
    tree = subprocess.run(
        ["git", "-C", str(repo), "write-tree"],
        check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_INDEX_FILE": str(baseline_index)},
    ).stdout.strip()
    (repo / ".git" / "symnav-bench-baseline-tree").write_text(tree, encoding="utf-8")

    (repo / "source.txt").write_text("agent fix\n", encoding="utf-8")
    (repo / "brand-new.txt").write_text("agent file\n", encoding="utf-8")

    task_dir = write_task(tmp_path, workdir=str(repo))
    logs_dir = tmp_path / "logs"
    script = (task_dir / "pre_artifacts.sh").read_text(encoding="utf-8")
    script = script.replace("/logs/artifacts", str(logs_dir / "artifacts"))
    runnable = tmp_path / "pre_artifacts.sh"
    runnable.write_text(script, encoding="utf-8")
    subprocess.run(["bash", str(runnable)], check=True, capture_output=True)

    patch = (logs_dir / "artifacts" / "model.patch").read_text(encoding="utf-8")
    assert "agent fix" in patch
    assert "brand-new.txt" in patch
    assert "Dockerfile" not in patch
