from __future__ import annotations

import base64
from pathlib import Path
from typing import Mapping

from symnav_bench.run_spec import AgentSpec


def validate_auth(specs: list[AgentSpec], env: Mapping[str, str]) -> None:
    agents = {spec.agent for spec in specs}
    if "codex" in agents and not env.get("CODEX_AUTH_JSON_B64"):
        raise RuntimeError("codex agent requires CODEX_AUTH_JSON_B64")
    if "claude" in agents and not (env.get("CLAUDE_CODE_OAUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")):
        raise RuntimeError("claude agent requires CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY")


def write_codex_auth(env: Mapping[str, str], home: Path) -> None:
    encoded = env.get("CODEX_AUTH_JSON_B64")
    if not encoded:
        return
    target = home / ".codex" / "auth.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(encoded))
