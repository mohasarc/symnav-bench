from __future__ import annotations

import pytest

from symnav_bench.cell_identity import CellIdentity
from symnav_bench.run_spec import AgentSpec, Condition


def test_agent_spec_parse() -> None:
    assert AgentSpec.parse("codex:gpt-5.4:xhigh") == AgentSpec("codex", "gpt-5.4", "xhigh")
    assert AgentSpec.parse("claude:claude-opus-4-8:high") == AgentSpec("claude", "claude-opus-4-8", "high")


@pytest.mark.parametrize("spec", ["codex:gpt-5.4", "openai:gpt-5:xhigh", "codex::xhigh"])
def test_agent_spec_parse_rejects_bad_specs(spec: str) -> None:
    with pytest.raises(ValueError, match="bad agent spec"):
        AgentSpec.parse(spec)


def test_condition_label_and_cell_dirname() -> None:
    spec = AgentSpec.parse("codex:gpt-5.4:xhigh")
    condition = Condition("symnav", "abc123def4569999999999999999999999999999")
    assert condition.label == "symnav@abc123def456"
    assert (
        CellIdentity(spec, condition.label, "ts-pattern-match-each", 0).dirname()
        == "codex-gpt-5.4-xhigh-symnav@abc123def456-ts-pattern-match-each-rep0"
    )
