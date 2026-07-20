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


def patch_codex_nvm_install(module_path: Path | None = None) -> None:
    path = module_path if module_path is not None else Path(pier_codex.__file__)
    source = path.read_text(encoding="utf-8")
    if PATCHED_INSTALL_LINES in source:
        return
    if UNPATCHED_INSTALL_LINES not in source:
        raise RuntimeError(
            f"codex nvm install snippet not found in {path}; "
            "pier changed — re-verify the patch against the pinned version"
        )
    path.write_text(
        source.replace(UNPATCHED_INSTALL_LINES, PATCHED_INSTALL_LINES, 1),
        encoding="utf-8",
    )
