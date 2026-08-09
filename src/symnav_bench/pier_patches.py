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


PORTABLE_NODE_URL = (
    "https://unofficial-builds.nodejs.org/download/release/v22.23.2/"
    "node-v22.23.2-linux-x64-glibc-217.tar.gz"
)
UNPATCHED_NODE_INSTALL = "  nvm install 22 && nvm alias default 22 && npm -v &&"
# Kept free of double quotes: this text is spliced into a double-quoted string
# literal inside pier's own source file.
PATCHED_NODE_INSTALL = (
    "  { nvm install 22 && nvm alias default 22 && node -e '' 2>/dev/null; }"
    " || { curl -fsSL " + PORTABLE_NODE_URL + " -o /tmp/node-portable.tar.gz"
    " && mkdir -p /opt/node"
    " && tar -xzf /tmp/node-portable.tar.gz -C /opt/node --strip-components=1"
    " && export PATH=/opt/node/bin:$PATH; } && npm -v &&"
)


UNPATCHED_RUNTIME_SOURCING = "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi"
# Sourcing nvm is not enough on images that fell back to the portable node:
# nvm's node cannot run there, so codex lives under /opt/node/bin and would not
# be on PATH when the agent is invoked.
PATCHED_RUNTIME_SOURCING = (
    "if [ -s ~/.nvm/nvm.sh ]; then NVM_DIR=$HOME/.nvm . ~/.nvm/nvm.sh; fi;"
    " if [ -d /opt/node/bin ]; then PATH=/opt/node/bin:$PATH; export PATH; fi"
)


UNPATCHED_APT_INSTALL = "  apt-get update && apt-get install -y curl ripgrep;"
APT_INSTALL = "apt-get -o APT::Get::AllowUnauthenticated=true install -y"
PATCHED_APT_INSTALL = (
    "  (apt-get update || { "
    "sed -i"
    " -e 's|http://deb.debian.org/debian|http://archive.debian.org/debian|g'"
    " -e 's|http://security.debian.org/debian-security|http://archive.debian.org/debian-security|g'"
    " -e '/-updates/d' /etc/apt/sources.list"
    " && apt-get -o Acquire::Check-Valid-Until=false update; })"
    f" && {APT_INSTALL} curl"
    f" && {{ {APT_INSTALL} ripgrep || echo 'ripgrep unavailable' >&2; }};"
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
    source = source.replace(UNPATCHED_APT_INSTALL, PATCHED_APT_INSTALL)
    source = source.replace(UNPATCHED_NODE_INSTALL, PATCHED_NODE_INSTALL)
    path.write_text(source, encoding="utf-8")
