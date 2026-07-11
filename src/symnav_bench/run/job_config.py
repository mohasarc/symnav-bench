from __future__ import annotations

from dataclasses import asdict, dataclass
import yaml
from pathlib import Path

from symnav_bench.agent_integrations import AgentIntegrationBundle
from symnav_bench.run_spec import AgentSpec, Condition
from symnav_bench.study import AgentConfiguration
from symnav_bench.suite import TaskManifestEntry


@dataclass(frozen=True)
class HarnessIdentity:
    image_reference: str
    image_digest: str
    symnav_bench_sha: str
    pier_version: str
    deep_swe_sha: str
    symnav_sha: str | None
    agent_name: str
    agent_version: str
    bundle_id: str | None
    bundle_hash: str | None
    task_checksum: str
    prompt_rule_hash: str
    requested_model: str
    requested_effort: str

    def to_json(self) -> dict[str, str | None]:
        return asdict(self)


def build_job_yaml(
    configuration: AgentConfiguration | AgentSpec,
    condition: Condition,
    task: TaskManifestEntry | str,
    tasks_dir: Path,
    integration: AgentIntegrationBundle | None = None,
    wall_clock_seconds: int | None = None,
) -> str:
    spec = configuration.spec if isinstance(configuration, AgentConfiguration) else configuration
    agent_version = configuration.agent_version if isinstance(configuration, AgentConfiguration) else None
    agent = _agent_block(spec, condition, integration, agent_version, wall_clock_seconds)
    task_name = task.slug if isinstance(task, TaskManifestEntry) else task
    payload = {
        "agents": [agent],
        "tasks": [{"path": str(tasks_dir / task_name)}],
    }
    if isinstance(configuration, AgentConfiguration) and isinstance(task, TaskManifestEntry):
        payload["symnav_bench"] = _job_identity(
            configuration,
            condition,
            task,
            integration,
        )
    return yaml.safe_dump(payload, sort_keys=True)


def _agent_block(
    spec: AgentSpec,
    condition: Condition,
    integration: AgentIntegrationBundle | None,
    agent_version: str | None,
    wall_clock_seconds: int | None,
) -> dict[str, object]:
    if spec.agent == "claude" and condition.kind == "stock":
        return _agent_config(
            spec,
            (
                {"import_path": "symnav_bench.agents.claude:StockClaudeCode"}
                if integration is not None
                else {"name": "claude-code"}
            ),
            integration=integration,
            agent_version=agent_version,
            wall_clock_seconds=wall_clock_seconds,
        )
    if spec.agent == "claude":
        return _agent_config(
            spec,
            {"import_path": "symnav_bench.agents.claude:SymnavClaudeCode"},
            symnav_sha=condition.symnav_sha,
            symnav_skill_variant=condition.symnav_skill_variant if integration is None else "all",
            integration=integration,
            agent_version=agent_version,
            wall_clock_seconds=wall_clock_seconds,
        )
    if condition.kind == "stock":
        return _agent_config(
            spec,
            {"import_path": "symnav_bench.agents.codex:StockCodex"},
            integration=integration,
            agent_version=agent_version,
            wall_clock_seconds=wall_clock_seconds,
        )
    return _agent_config(
        spec,
        {"import_path": "symnav_bench.agents.codex:SymnavCodex"},
        symnav_sha=condition.symnav_sha,
        symnav_skill_variant=condition.symnav_skill_variant if integration is None else "all",
        integration=integration,
        agent_version=agent_version,
        wall_clock_seconds=wall_clock_seconds,
    )


def _agent_config(
    spec: AgentSpec,
    base: dict[str, object],
    symnav_sha: str | None = None,
    symnav_skill_variant: str = "all",
    integration: AgentIntegrationBundle | None = None,
    agent_version: str | None = None,
    wall_clock_seconds: int | None = None,
) -> dict[str, object]:
    kwargs = {"reasoning_effort": spec.effort}
    if symnav_sha is not None:
        kwargs["symnav_sha"] = symnav_sha
    if symnav_skill_variant != "all":
        kwargs["symnav_skill_variant"] = symnav_skill_variant
    if integration is not None:
        kwargs["integration_bundle"] = integration.job_payload()
    if agent_version is not None:
        kwargs["version"] = agent_version
    config: dict[str, object] = {**base, "model_name": spec.model, "kwargs": kwargs}
    if wall_clock_seconds is not None:
        config["override_timeout_sec"] = wall_clock_seconds
    if spec.agent == "codex":
        config["env"] = {"CODEX_FORCE_AUTH_JSON": "true"}
    return config


def _job_identity(
    configuration: AgentConfiguration,
    condition: Condition,
    task: TaskManifestEntry,
    integration: AgentIntegrationBundle | None,
) -> dict[str, object]:
    treatment = condition.kind == "symnav"
    return {
        "agent": configuration.spec.agent,
        "agent_version": configuration.agent_version,
        "bundle_hash": integration.content_hash if treatment and integration else None,
        "bundle_id": integration.id if treatment and integration else None,
        "effort": configuration.spec.effort,
        "model": configuration.spec.model,
        "symnav_sha": condition.symnav_sha,
        "task_checksum": task.checksum,
    }
