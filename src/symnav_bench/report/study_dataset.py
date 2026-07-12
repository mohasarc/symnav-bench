from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from symnav_bench.cells.attempt import SlotResult
from symnav_bench.cells.cell import Cell
from symnav_bench.study import StudyManifest
from symnav_bench.suite import SuiteManifest


@dataclass(frozen=True)
class ConfigurationKey:
    agent: str
    model: str
    effort: str
    agent_version: str
    condition: str
    bundle_hash: str | None


@dataclass(frozen=True)
class Coverage:
    planned_slots: int
    scored_slots: int
    retryable_attempts: int
    unresolved_slot_ids: tuple[str, ...]
    complete_tasks: int
    total_tasks: int
    provisional: bool
    pilot: bool


@dataclass(frozen=True)
class AdoptionSummary:
    used_symnav_rate: float
    read_symnav_skill_rate: float
    mean_symnav_calls: float
    mean_symnav_calls_per_agent_step: float
    mean_symnav_failures: float
    mean_symnav_timeouts: float
    mean_first_symnav_step: float | None
    mean_search_calls: float
    mean_read_calls: float
    mean_patch_calls: float
    mean_command_counts: dict[str, float]


@dataclass(frozen=True)
class TaskMetrics:
    task: str
    scored_trials: int
    pass_fraction: float | None
    mean_f2p: float | None
    mean_p2p: float | None
    mean_partial: float | None
    mean_cost: float | None
    median_cost: float | None
    mean_output_tokens: float | None
    mean_steps: float | None
    mean_duration_seconds: float | None
    adoption: AdoptionSummary | None


@dataclass(frozen=True)
class ConfigurationMetrics:
    key: ConfigurationKey
    coverage: Coverage
    tasks: tuple[TaskMetrics, ...]
    performance_score: float | None
    repetition_scores: tuple[float, ...]
    mean_f2p: float | None
    mean_p2p: float | None
    mean_partial: float | None
    total_cost: float | None
    cost_per_success: float | None
    adoption: AdoptionSummary | None


@dataclass(frozen=True)
class StudyDataset:
    manifest: StudyManifest
    suite: SuiteManifest
    slots: tuple[SlotResult, ...]
    warnings: tuple[str, ...]

    @classmethod
    def load(cls, study_dir: Path) -> StudyDataset:
        raise NotImplementedError

    def configurations(self) -> dict[ConfigurationKey, tuple[SlotResult, ...]]:
        raise NotImplementedError


def compute_configuration_metrics(
    dataset: StudyDataset,
    key: ConfigurationKey,
) -> ConfigurationMetrics:
    raise NotImplementedError


@dataclass(frozen=True)
class LegacyDataset:
    cells: tuple[Cell, ...]
    warnings: tuple[str, ...]


def import_legacy_cells(cells_dir: Path) -> LegacyDataset:
    raise NotImplementedError
