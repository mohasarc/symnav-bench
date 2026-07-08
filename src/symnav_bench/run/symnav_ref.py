from __future__ import annotations

import re
import subprocess
from typing import Callable


LsRemote = Callable[[str], str]


def resolve_symnav_ref(ref: str, ls_remote: LsRemote | None = None) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    output = (ls_remote or _git_ls_remote)(ref)
    for line in output.splitlines():
        sha = line.split()[0] if line.split() else ""
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            return sha
    raise RuntimeError(f"could not resolve symnav ref {ref!r}")


def _git_ls_remote(ref: str) -> str:
    completed = subprocess.run(
        ["git", "ls-remote", "https://github.com/mohasarc/symnav.git", ref],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout
