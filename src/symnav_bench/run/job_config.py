from __future__ import annotations

import yaml
from pathlib import Path

from symnav_bench.run_spec import AgentSpec, Condition


def build_job_yaml(spec: AgentSpec, condition: Condition, task: str, tasks_dir: Path) -> str:
    agent = _agent_block(spec, condition)
    payload = {
        "agent": agent,
        "model": spec.model,
        "effort": spec.effort,
        "task": {
            "name": task,
            "path": str(tasks_dir / task),
        },
    }
    return yaml.safe_dump(payload, sort_keys=True)


def _agent_block(spec: AgentSpec, condition: Condition) -> dict[str, object]:
    if spec.agent == "claude" and condition.kind == "stock":
        return {"import_path": "datacurve_pier.agents", "name": "ClaudeCode"}
    if spec.agent == "claude":
        return {
            "import_path": "symnav_bench.agents.claude",
            "name": "SymnavClaudeCode",
            "kwargs": {"symnav_sha": condition.symnav_sha},
        }
    if condition.kind == "stock":
        return {"import_path": "symnav_bench.agents.codex", "name": "StockCodex"}
    return {
        "import_path": "symnav_bench.agents.codex",
        "name": "SymnavCodex",
        "kwargs": {"symnav_sha": condition.symnav_sha},
    }
