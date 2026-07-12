from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_non_run_commands_skip_nested_docker_daemon(tmp_path: Path) -> None:
    marker = tmp_path / "dockerd-called"
    executable = tmp_path / "symnav-bench"
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$*"\n', encoding="utf-8")
    executable.chmod(0o755)
    dockerd = tmp_path / "dockerd-entrypoint.sh"
    dockerd.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    dockerd.chmod(0o755)
    environment = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}

    result = subprocess.run(
        ["bash", str(ROOT / "entrypoint.sh"), "batch-matrix", "--mode", "run-all"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.stdout == "batch-matrix --mode run-all\n"
    assert not marker.exists()
