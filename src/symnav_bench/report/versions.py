from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from symnav_bench.report.statistics import ConditionComparison
from symnav_bench.report.statistics import Estimate
from symnav_bench.study import SymnavRevision


@dataclass(frozen=True)
class VersionComparison:
    left_study_id: str
    right_study_id: str
    left_revision: SymnavRevision
    right_revision: SymnavRevision
    uplift_difference: Estimate


def compare_study_versions(
    left: ConditionComparison,
    right: ConditionComparison,
    *,
    seed: int,
) -> VersionComparison:
    raise NotImplementedError


def order_symnav_revisions(
    revisions: tuple[SymnavRevision, ...],
    *,
    first_parent_positions: Mapping[str, int],
) -> tuple[SymnavRevision, ...]:
    raise NotImplementedError
