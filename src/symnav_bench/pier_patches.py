from __future__ import annotations

from pathlib import Path

import pier.agents.installed.codex as pier_codex

UNPATCHED_INSTALL_LINES = (
    '            "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash &&"\n'
    '            \'  export NVM_DIR="$HOME/.nvm" &&\'\n'
)
PATCHED_INSTALL_LINES = (
    '            \'  export NVM_DIR="$HOME/.nvm" &&\'\n'
    '            "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash &&"\n'
)


UNPATCHED_RUNTIME_SOURCING = "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi"
PATCHED_RUNTIME_SOURCING = (
    'if [ -s ~/.nvm/nvm.sh ]; then NVM_DIR="$HOME/.nvm" . ~/.nvm/nvm.sh; fi'
)


def patch_codex_nvm_install(module_path: Path | None = None) -> None:
    path = module_path if module_path is not None else Path(pier_codex.__file__)
    source = path.read_text(encoding="utf-8")
    if PATCHED_INSTALL_LINES not in source:
        if UNPATCHED_INSTALL_LINES not in source:
            raise RuntimeError(
                f"codex nvm install snippet not found in {path}; "
                "pier changed — re-verify the patch against the pinned version"
            )
        source = source.replace(UNPATCHED_INSTALL_LINES, PATCHED_INSTALL_LINES, 1)
    source = source.replace(UNPATCHED_RUNTIME_SOURCING, PATCHED_RUNTIME_SOURCING)
    path.write_text(source, encoding="utf-8")
