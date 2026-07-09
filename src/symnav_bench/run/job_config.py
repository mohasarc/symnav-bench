from __future__ import annotations

import yaml
from pathlib import Path

from symnav_bench.run_spec import AgentSpec, Condition


def build_job_yaml(spec: AgentSpec, condition: Condition, task: str, tasks_dir: Path) -> str:
    agent = _agent_block(spec, condition)
    payload = {
        "agents": [agent],
        "tasks": [{"path": str(tasks_dir / task)}],
    }
    return yaml.safe_dump(payload, sort_keys=True)


def _agent_block(spec: AgentSpec, condition: Condition) -> dict[str, object]:
    if spec.agent == "claude" and condition.kind == "stock":
        return _agent_config(
            spec,
            {"name": "claude-code"},
        )
    if spec.agent == "claude":
        return _agent_config(
            spec,
            {"import_path": "symnav_bench.agents.claude:SymnavClaudeCode"},
            symnav_sha=condition.symnav_sha,
        )
    if condition.kind == "stock":
        return _agent_config(
            spec,
            {"import_path": "symnav_bench.agents.codex:StockCodex"},
        )
    return _agent_config(
        spec,
        {"import_path": "symnav_bench.agents.codex:SymnavCodex"},
        symnav_sha=condition.symnav_sha,
    )


def _agent_config(
    spec: AgentSpec,
    base: dict[str, object],
    symnav_sha: str | None = None,
) -> dict[str, object]:
    kwargs = {"reasoning_effort": spec.effort}
    if symnav_sha is not None:
        kwargs["symnav_sha"] = symnav_sha
    config: dict[str, object] = {**base, "model_name": spec.model, "kwargs": kwargs}
    if spec.agent == "codex":
        config["env"] = {"CODEX_FORCE_AUTH_JSON": "true"}
    return config
