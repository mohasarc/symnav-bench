from __future__ import annotations

from pathlib import Path

import pytest

from symnav_bench.pier_patches import (
    PATCHED_INSTALL_LINES,
    UNPATCHED_INSTALL_LINES,
    patch_codex_nvm_install,
)

UNPATCHED_SNIPPET = """
        agent_run = (
            "set -euo pipefail; "
            "if ldd --version 2>&1 | grep -qi musl || [ -f /etc/alpine-release ]; then"
            f"  npm install -g @openai/codex{version_spec};"
            " else"
            "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash &&"
            '  export NVM_DIR="$HOME/.nvm" &&'
            '  \\\\. "$NVM_DIR/nvm.sh" || true &&'
            "  command -v nvm &>/dev/null || {{ echo 'Error: NVM failed to load' >&2; exit 1; }} &&"
            "  nvm install 22 && nvm alias default 22 && npm -v &&"
            f"  npm install -g @openai/codex{version_spec};"
            " fi && "
            "codex --version"
        )
""".format(version_spec="{version_spec}")


def write_codex_module(tmp_path: Path, content: str) -> Path:
    module = tmp_path / "codex.py"
    module.write_text(content, encoding="utf-8")
    return module


def test_hoists_nvm_dir_export_before_installer(tmp_path: Path) -> None:
    module = write_codex_module(tmp_path, UNPATCHED_SNIPPET)

    patch_codex_nvm_install(module)

    patched = module.read_text(encoding="utf-8")
    export_position = patched.index('export NVM_DIR="$HOME/.nvm"')
    installer_position = patched.index("install.sh | bash")
    assert export_position < installer_position


def test_patch_is_idempotent(tmp_path: Path) -> None:
    module = write_codex_module(tmp_path, UNPATCHED_SNIPPET)

    patch_codex_nvm_install(module)
    once = module.read_text(encoding="utf-8")
    patch_codex_nvm_install(module)

    assert module.read_text(encoding="utf-8") == once


def test_unexpected_snippet_is_a_hard_error(tmp_path: Path) -> None:
    module = write_codex_module(tmp_path, "def install():\n    return 'other'\n")

    with pytest.raises(RuntimeError, match="codex nvm install snippet"):
        patch_codex_nvm_install(module)


def test_installed_pier_module_carries_the_expected_snippet() -> None:
    import pier.agents.installed.codex as codex_module

    source = Path(codex_module.__file__).read_text(encoding="utf-8")
    assert UNPATCHED_INSTALL_LINES in source or PATCHED_INSTALL_LINES in source


def test_dockerfile_applies_the_patch() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "patch_codex_nvm_install" in dockerfile
