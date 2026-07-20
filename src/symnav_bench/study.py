from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from symnav_bench.run_spec import AgentSpec


AgentName = Literal["claude", "codex"]
ConditionName = Literal[
    "stock",
    "symnav",
    "overview",
    "resolve",
    "def",
    "refs",
    "context",
    "graph",
    "overview-refs",
    "overview-context",
    "overview-def",
    "overview-graph",
    "resolve-graph",
]
SymnavRevisionKind = Literal["main", "pull_request"]
BenchmarkName = Literal["deepswe", "swe-polybench", "multi-swe-bench"]
FitTier = Literal["high", "mid", "low"]
BENCHMARK_NAMES: tuple[BenchmarkName, ...] = ("deepswe", "swe-polybench", "multi-swe-bench")
FIT_TIERS: tuple[FitTier, ...] = ("high", "mid", "low")
CONDITION_NAMES: tuple[ConditionName, ...] = (
    "stock",
    "symnav",
    "overview",
    "resolve",
    "def",
    "refs",
    "context",
    "graph",
    "overview-refs",
    "overview-context",
    "overview-def",
    "overview-graph",
    "resolve-graph",
)
GIT_SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")


@dataclass(frozen=True)
class AgentConfiguration:
    id: str
    spec: AgentSpec
    agent_version: str


@dataclass(frozen=True)
class BenchmarkSelection:
    name: BenchmarkName
    source_revision: str
    tiers: tuple[FitTier, ...] | None


@dataclass(frozen=True)
class SymnavRevision:
    sha: str
    kind: SymnavRevisionKind
    evaluation_sequence: int
    base_ref: str
    base_sha: str
    pull_request: int | None


@dataclass(frozen=True)
class StudyProtocol:
    benchmark: BenchmarkSelection
    symnav: SymnavRevision
    repetitions: int
    wall_clock_seconds: int
    randomization_seed: int
    conditions: tuple[ConditionName, ...]
    scoring_policy: str
    practical_uplift_points: float


@dataclass(frozen=True)
class StudyManifest:
    schema_version: int
    id: str
    protocol: StudyProtocol
    configurations: tuple[AgentConfiguration, ...]

    @classmethod
    def load(cls, path: Path) -> StudyManifest:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        manifest_data = require_mapping(raw, "study")
        schema_version = require_integer(manifest_data.get("schema_version"), "schema_version")
        protocol_data = require_mapping(manifest_data.get("protocol"), "protocol")
        expected_fingerprint = require_string(
            manifest_data.get("protocol_fingerprint"), "protocol_fingerprint"
        )
        actual_fingerprint = fingerprint_mapping(protocol_data)
        if expected_fingerprint != actual_fingerprint:
            raise ValueError(
                "protocol fingerprint does not match immutable study protocol: "
                f"expected {expected_fingerprint}, got {actual_fingerprint}"
            )
        protocol = parse_protocol(protocol_data, schema_version)
        configuration_values = require_list(
            manifest_data.get("configurations"), "configurations"
        )
        configurations = tuple(
            parse_configuration(require_mapping(value, "configuration"))
            for value in configuration_values
        )
        configuration_ids = [configuration.id for configuration in configurations]
        if len(configuration_ids) != len(set(configuration_ids)):
            raise ValueError("configuration ids must be unique")
        return cls(
            schema_version=schema_version,
            id=require_string(manifest_data.get("id"), "id"),
            protocol=protocol,
            configurations=configurations,
        )

    def protocol_fingerprint(self) -> str:
        return fingerprint_mapping(protocol_mapping(self.protocol, self.schema_version))


def parse_protocol(data: dict[str, Any], schema_version: int) -> StudyProtocol:
    benchmark = parse_source_pin(data, schema_version)
    symnav_data = require_mapping(data.get("symnav"), "protocol.symnav")
    kind = require_string(symnav_data.get("kind"), "protocol.symnav.kind")
    if kind not in ("main", "pull_request"):
        raise ValueError(f"unknown symnav revision kind {kind!r}")
    symnav_sha = require_git_sha(symnav_data.get("sha"), "protocol.symnav.sha")
    base_sha = require_git_sha(symnav_data.get("base_sha"), "protocol.symnav.base_sha")
    condition_values = require_list(data.get("conditions"), "protocol.conditions")
    conditions: list[ConditionName] = []
    for value in condition_values:
        condition = require_string(value, "protocol.conditions entry")
        if condition not in CONDITION_NAMES:
            raise ValueError(f"unknown study condition {condition!r}")
        conditions.append(cast(ConditionName, condition))
    if len(conditions) != len(set(conditions)):
        raise ValueError("study conditions must be unique")
    repetitions = require_positive_integer(data.get("repetitions"), "protocol.repetitions")
    wall_clock_seconds = require_positive_integer(
        data.get("wall_clock_seconds"), "protocol.wall_clock_seconds"
    )
    pull_request_value = symnav_data.get("pull_request")
    pull_request = (
        None
        if pull_request_value is None
        else require_positive_integer(pull_request_value, "protocol.symnav.pull_request")
    )
    if kind == "pull_request" and pull_request is None:
        raise ValueError("pull_request symnav revision requires pull_request")
    if kind == "main" and pull_request is not None:
        raise ValueError("main symnav revision cannot carry pull_request")
    return StudyProtocol(
        benchmark=benchmark,
        symnav=SymnavRevision(
            sha=symnav_sha,
            kind=cast(SymnavRevisionKind, kind),
            evaluation_sequence=require_positive_integer(
                symnav_data.get("evaluation_sequence"),
                "protocol.symnav.evaluation_sequence",
            ),
            base_ref=require_string(symnav_data.get("base_ref"), "protocol.symnav.base_ref"),
            base_sha=base_sha,
            pull_request=pull_request,
        ),
        repetitions=repetitions,
        wall_clock_seconds=wall_clock_seconds,
        randomization_seed=require_integer(
            data.get("randomization_seed"), "protocol.randomization_seed"
        ),
        conditions=tuple(conditions),
        scoring_policy=require_string(data.get("scoring_policy"), "protocol.scoring_policy"),
        practical_uplift_points=require_number(
            data.get("practical_uplift_points"), "protocol.practical_uplift_points"
        ),
    )


def parse_source_pin(data: dict[str, Any], schema_version: int) -> BenchmarkSelection:
    if schema_version == 1:
        if "benchmark" in data:
            raise ValueError("schema version 1 does not accept protocol.benchmark")
        deep_swe_sha = require_git_sha(data.get("deep_swe_sha"), "protocol.deep_swe_sha")
        return BenchmarkSelection(name="deepswe", source_revision=deep_swe_sha, tiers=None)
    if schema_version == 2:
        if "deep_swe_sha" in data:
            raise ValueError("schema version 2 does not accept protocol.deep_swe_sha")
        return parse_benchmark(require_mapping(data.get("benchmark"), "protocol.benchmark"))
    raise ValueError(f"unsupported study schema version {schema_version}")


def parse_benchmark(data: dict[str, Any]) -> BenchmarkSelection:
    name = require_string(data.get("name"), "protocol.benchmark.name")
    if name not in BENCHMARK_NAMES:
        raise ValueError(f"unknown benchmark name {name!r}")
    source = require_mapping(data.get("source"), "protocol.benchmark.source")
    revision = require_git_sha(source.get("revision"), "protocol.benchmark.source.revision")
    if name != "swe-polybench":
        if data.get("tiers") is not None:
            raise ValueError("protocol.benchmark.tiers is only valid for swe-polybench")
        return BenchmarkSelection(
            name=cast(BenchmarkName, name), source_revision=revision, tiers=None
        )
    return BenchmarkSelection(
        name="swe-polybench",
        source_revision=revision,
        tiers=parse_tiers(data.get("tiers")),
    )


def parse_tiers(value: object) -> tuple[FitTier, ...]:
    tier_values = require_list(value, "protocol.benchmark.tiers")
    if not tier_values:
        raise ValueError("protocol.benchmark.tiers must not be empty")
    tiers: list[FitTier] = []
    for tier_value in tier_values:
        tier = require_string(tier_value, "protocol.benchmark.tiers entry")
        if tier not in FIT_TIERS:
            raise ValueError(f"unknown fit tier {tier!r}")
        tiers.append(cast(FitTier, tier))
    if len(tiers) != len(set(tiers)):
        raise ValueError("protocol.benchmark.tiers must be unique")
    return tuple(tiers)


def parse_configuration(data: dict[str, Any]) -> AgentConfiguration:
    agent = require_string(data.get("agent"), "configuration.agent")
    model = require_string(data.get("model"), "configuration.model")
    effort = require_string(data.get("effort"), "configuration.effort")
    return AgentConfiguration(
        id=require_string(data.get("id"), "configuration.id"),
        spec=AgentSpec.parse(f"{agent}:{model}:{effort}"),
        agent_version=require_string(data.get("agent_version"), "configuration.agent_version"),
    )


def protocol_mapping(protocol: StudyProtocol, schema_version: int) -> dict[str, Any]:
    if schema_version == 1:
        if protocol.benchmark.name != "deepswe":
            raise ValueError("schema version 1 studies are always deepswe")
        source_pin: dict[str, Any] = {"deep_swe_sha": protocol.benchmark.source_revision}
    else:
        source_pin = {"benchmark": benchmark_mapping(protocol.benchmark)}
    return {
        **source_pin,
        "symnav": {
            "sha": protocol.symnav.sha,
            "kind": protocol.symnav.kind,
            "evaluation_sequence": protocol.symnav.evaluation_sequence,
            "base_ref": protocol.symnav.base_ref,
            "base_sha": protocol.symnav.base_sha,
            "pull_request": protocol.symnav.pull_request,
        },
        "repetitions": protocol.repetitions,
        "wall_clock_seconds": protocol.wall_clock_seconds,
        "randomization_seed": protocol.randomization_seed,
        "conditions": list(protocol.conditions),
        "scoring_policy": protocol.scoring_policy,
        "practical_uplift_points": protocol.practical_uplift_points,
    }


def benchmark_mapping(benchmark: BenchmarkSelection) -> dict[str, Any]:
    mapping: dict[str, Any] = {
        "name": benchmark.name,
        "source": {"revision": benchmark.source_revision},
    }
    if benchmark.tiers is not None:
        mapping["tiers"] = list(benchmark.tiers)
    return mapping


def fingerprint_mapping(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def require_mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a mapping")
    return cast(dict[str, Any], value)


def require_list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def require_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def require_integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def require_positive_integer(value: object, name: str) -> int:
    integer = require_integer(value, name)
    if integer <= 0:
        raise ValueError(f"{name} must be positive")
    return integer


def require_number(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    return float(value)


def require_git_sha(value: object, name: str) -> str:
    sha = require_string(value, name)
    if not GIT_SHA.fullmatch(sha):
        raise ValueError(f"{name} must be an immutable git sha")
    return sha
