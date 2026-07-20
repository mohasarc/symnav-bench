from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MaterializedTaskSpec:
    benchmark: str
    slug: str
    instruction: str
    docker_image: str
    workdir: str
    base_commit: str
    test_patch: str
    f2p: tuple[str, ...]
    p2p: tuple[str, ...]
    test_command: str
    log_parser: str
    grade_script: str
    wall_clock_seconds: int | None = None


def write_pier_task_dir(spec: MaterializedTaskSpec, dest: Path) -> Path:
    environment_dir = dest / "environment"
    tests_dir = dest / "tests"
    environment_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    write_text(dest / "task.toml", task_toml(spec))
    write_text(dest / "instruction.md", spec.instruction)
    write_script(dest / "pre_artifacts.sh", pre_artifacts_script(spec))
    write_text(environment_dir / "Dockerfile", f"FROM {spec.docker_image}\n")
    write_text(tests_dir / "Dockerfile", verifier_dockerfile(spec))
    write_script(tests_dir / "test.sh", verifier_script(spec))
    write_script(tests_dir / "run_tests.sh", run_tests_script(spec))
    write_text(tests_dir / "grade.py", spec.grade_script)
    write_text(tests_dir / "config.json", grading_config(spec))
    write_text(tests_dir / "test.patch", spec.test_patch)
    return dest


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def write_script(path: Path, content: str) -> None:
    write_text(path, content)
    path.chmod(0o755)


def toml_string(value: str) -> str:
    return json.dumps(value)


def task_toml(spec: MaterializedTaskSpec) -> str:
    agent_section = (
        ""
        if spec.wall_clock_seconds is None
        else f"\n[agent]\ntimeout_sec = {float(spec.wall_clock_seconds)}\n"
    )
    return (
        'schema_version = "1.1"\n'
        'artifacts = ["/logs/artifacts/model.patch"]\n'
        "\n"
        "[task]\n"
        f"name = {toml_string(spec.benchmark + '/' + spec.slug)}\n"
        'description = ""\n'
        "\n"
        "[metadata]\n"
        f"task_id = {toml_string(spec.slug)}\n"
        'language = "typescript"\n'
        f"benchmark = {toml_string(spec.benchmark)}\n"
        f"base_commit_hash = {toml_string(spec.base_commit)}\n"
        "\n"
        "[verifier]\n"
        'environment_mode = "separate"\n'
        "timeout_sec = 1800.0\n"
        f"{agent_section}"
        "\n"
        "[environment]\n"
        "build_timeout_sec = 1800.0\n"
        f"docker_image = {toml_string(spec.docker_image)}\n"
        'os = "linux"\n'
        "cpus = 2\n"
        "memory_mb = 8192\n"
        "storage_mb = 20480\n"
        "allow_internet = false\n"
        f"workdir = {toml_string(spec.workdir)}\n"
    )


def pre_artifacts_script(spec: MaterializedTaskSpec) -> str:
    return (
        "#!/bin/bash\n"
        "set -uo pipefail\n"
        f"cd {spec.workdir} || exit 0\n"
        "mkdir -p /logs/artifacts\n"
        f"git config --global --add safe.directory {spec.workdir} 2>/dev/null || true\n"
        "git add -N . 2>/dev/null || true\n"
        f"git diff --binary {spec.base_commit} > /logs/artifacts/model.patch"
        " 2>/dev/null || true\n"
        'echo "[pre_artifacts] captured'
        ' $(wc -c < /logs/artifacts/model.patch) bytes"\n'
    )


def verifier_dockerfile(spec: MaterializedTaskSpec) -> str:
    copies = "".join(
        f"COPY {name} /tests/{name}\n"
        for name in ("test.sh", "run_tests.sh", "grade.py", "config.json", "test.patch")
    )
    return (
        f"FROM {spec.docker_image}\n"
        f"{copies}"
        "RUN chmod +x /tests/test.sh /tests/run_tests.sh\n"
    )


def verifier_script(spec: MaterializedTaskSpec) -> str:
    return (
        "#!/bin/bash\n"
        "set -uo pipefail\n"
        "trap 'if [ ! -f /logs/verifier/reward.json ]"
        " && [ ! -f /logs/verifier/reward.txt ];"
        " then mkdir -p /logs/verifier; echo -1 > /logs/verifier/reward.txt; fi' EXIT\n"
        "mkdir -p /logs/verifier\n"
        f"cd {spec.workdir} || exit 6\n"
        "python3 /tests/grade.py prepare || exit $?\n"
        "[ -f /logs/verifier/reward.json ] && exit 0\n"
        "RUN_LOG=/logs/verifier/run.log\n"
        ': > "$RUN_LOG"\n'
        "set +e\n"
        'bash /tests/run_tests.sh 2>&1 | tee -a "$RUN_LOG"\n'
        "status=${PIPESTATUS[0]}\n"
        "set -e\n"
        'echo "Container exited with status code: $status" | tee -a "$RUN_LOG"\n'
        'echo "===== grade ====="\n'
        "python3 /tests/grade.py grade\n"
    )


def run_tests_script(spec: MaterializedTaskSpec) -> str:
    return (
        "#!/bin/bash\n"
        "set -uxo pipefail\n"
        f"cd {spec.workdir}\n"
        f"{spec.test_command}\n"
    )


def grading_config(spec: MaterializedTaskSpec) -> str:
    config = {
        "base_commit": spec.base_commit,
        "benchmark": spec.benchmark,
        "docker_image": spec.docker_image,
        "f2p": list(spec.f2p),
        "log_parser": spec.log_parser,
        "p2p": list(spec.p2p),
        "test_command": spec.test_command,
        "workdir": spec.workdir,
    }
    return json.dumps(config, indent=1, sort_keys=True) + "\n"
