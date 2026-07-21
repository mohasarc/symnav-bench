from __future__ import annotations

from pathlib import Path

import pytest

from symnav_bench.pier_patches import (
    PATCHED_INSTALL_LINES,
    UNPATCHED_INSTALL_LINES,
    patch_codex_nvm_install,
)

UNPATCHED_SNIPPET = """
class Codex:
    def install(self, version_spec):
        agent_run = (
            "set -eu; "
            "if ldd --version 2>&1 | grep -qi musl || [ -f /etc/alpine-release ]; then"
            f"  npm install -g @openai/codex{version_spec};"
            " else"
            "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash &&"
            \'  export NVM_DIR="$HOME/.nvm" &&\'
            \'  \\\\. "$NVM_DIR/nvm.sh" || true &&\'
            "  nvm install 22 && nvm alias default 22 && npm -v &&"
            f"  npm install -g @openai/codex{version_spec};"
            " fi && "
            "codex --version"
        )
        return agent_run
"""


def write_codex_module(tmp_path: Path, content: str) -> Path:
    module = tmp_path / "codex.py"
    module.write_text(content, encoding="utf-8")
    return module


def test_hoists_nvm_dir_export_before_installer(tmp_path: Path) -> None:
    module = write_codex_module(tmp_path, UNPATCHED_SNIPPET)

    patch_codex_nvm_install(module)

    patched = module.read_text(encoding="utf-8")
    compile(patched, str(module), "exec")
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


def test_installed_pier_module_carries_the_expected_snippet(tmp_path: Path) -> None:
    import pier.agents.installed.codex as codex_module

    source = Path(codex_module.__file__).read_text(encoding="utf-8")
    assert UNPATCHED_INSTALL_LINES in source or PATCHED_INSTALL_LINES in source

    copy = write_codex_module(tmp_path, source)
    patch_codex_nvm_install(copy)
    compile(copy.read_text(encoding="utf-8"), str(copy), "exec")


def test_dockerfile_applies_the_patch() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "patch_codex_nvm_install" in dockerfile


def test_runtime_nvm_sourcing_pins_nvm_dir(tmp_path: Path) -> None:
    module = write_codex_module(
        tmp_path,
        UNPATCHED_SNIPPET
        + '\nCHECK = "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; codex --version"\n'
        + 'PREFIX = "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "\n',
    )

    patch_codex_nvm_install(module)

    patched = module.read_text(encoding="utf-8")
    compile(patched, str(module), "exec")
    assert "then . ~/.nvm/nvm.sh; fi" not in patched
    assert patched.count("NVM_DIR=$HOME/.nvm . ~/.nvm/nvm.sh; fi") == 2
