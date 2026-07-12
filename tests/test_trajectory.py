from __future__ import annotations

import json
from pathlib import Path

from symnav_bench.cells.trajectory import (
    MAX_COMMAND_OUTPUT_CHARS,
    classify,
    extract_commands,
    extract_tool_events,
    summarize_adoption,
    write_commands_jsonl,
)


FIXTURES = Path(__file__).parent / "fixtures" / "trajectories"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_extracts_nested_terra_exec_with_metadata_and_classification() -> None:
    events = extract_tool_events(_fixture("terra_nested_exec.json"))

    event = events[0]
    assert event.step_id == 7
    assert event.sequence == 0
    assert event.timestamp == "2026-07-11T18:00:00Z"
    assert event.outer_tool == "exec"
    assert event.tool == "exec_command"
    assert event.kind == "shell"
    assert event.command == "symnav overview src/a.ts"
    assert event.args["workdir"] == "/app"
    assert event.args["yield_time_ms"] == 10000
    assert event.tags == ("symnav:overview",)
    assert event.exit_code == 0
    assert event.succeeded is True
    assert event.output == "Process exited with code 0\nOutput:\nsrc/a.ts\n"
    assert event.output_chars == len(event.output)
    assert event.output_truncated is False
    assert event.parser_warning is None


def test_multiple_nested_calls_preserve_source_order() -> None:
    events = extract_tool_events(_fixture("terra_nested_exec.json"))

    assert [event.command for event in events[1:3]] == [
        "rg -n Foo src",
        "sed -n '1,80p' src/a.ts",
    ]
    assert [event.sequence for event in events] == list(range(len(events)))
    assert [event.tags for event in events[1:3]] == [("search",), ("read",)]


def test_nested_patch_becomes_patch_event() -> None:
    events = extract_tool_events(_fixture("terra_nested_exec.json"))

    assert events[3].tool == "apply_patch"
    assert events[3].kind == "patch"
    assert events[3].command.startswith("*** Begin Patch")


def test_outer_wait_and_nested_write_stdin_complete_original_commands() -> None:
    events = extract_tool_events(_fixture("terra_sessions.json"))

    assert [event.command for event in events] == ["symnav refs Foo", "pnpm test"]
    assert events[0].exit_code == 0
    assert events[0].succeeded is True
    assert events[0].output.endswith("3 references\n")
    assert events[1].session_id == 42
    assert events[1].exit_code == 1
    assert events[1].succeeded is False
    assert events[1].output.endswith("1 failed\n")


def test_direct_claude_tools_keep_their_classification() -> None:
    events = extract_tool_events(
        {
            "steps": [
                {
                    "tool_calls": [
                        {"function_name": "Read", "arguments": {"file_path": "src/a.ts"}},
                        {"function_name": "Grep", "arguments": {"pattern": "Foo"}},
                        {"function_name": "Glob", "arguments": {"pattern": "**/*.ts"}},
                        {"function_name": "Bash", "arguments": {"command": "symnav def Foo"}},
                        {"function_name": "Skill", "arguments": {"skill": "symnav"}},
                    ]
                }
            ]
        }
    )

    assert [event.kind for event in events] == ["read", "search", "search", "shell", "skill"]
    assert events[3].tags == ("symnav:def",)
    assert events[4].tags == ("skill:symnav",)


def test_malformed_nested_javascript_preserves_outer_event_with_warning() -> None:
    events = extract_tool_events(
        {
            "steps": [
                {
                    "tool_calls": [
                        {
                            "function_name": "exec",
                            "arguments": {"code": "await tools.exec_command({cmd: broken);"},
                        }
                    ]
                }
            ]
        }
    )

    assert len(events) == 1
    assert events[0].outer_tool == "exec"
    assert events[0].tool == "exec"
    assert events[0].kind == "other"
    assert events[0].parser_warning


def test_skill_reads_recognize_full_and_bundle_metadata_paths() -> None:
    variant = _fixture("terra_nested_exec.json")
    variant["steps"] = [
        {
            "tool_calls": [
                {
                    "function_name": "Read",
                    "arguments": {
                        "file_path": "/app/.agents/integrations/symnav/variants/overview/skill/SKILL.md"
                    },
                }
            ]
        }
    ]
    full = {
        "steps": [
            {
                "tool_calls": [
                    {
                        "function_name": "Read",
                        "arguments": {"file_path": "/app/.agents/skills/symnav/SKILL.md"},
                    }
                ]
            }
        ]
    }

    assert extract_tool_events(variant)[0].kind == "skill"
    assert extract_tool_events(full)[0].kind == "skill"


def test_summarizes_per_trial_tool_adoption() -> None:
    summary = summarize_adoption(
        extract_tool_events(_fixture("terra_nested_exec.json")),
        agent_steps=10,
    )

    assert summary.used_symnav is True
    assert summary.read_symnav_skill is False
    assert summary.symnav_calls == 1
    assert summary.symnav_calls_per_agent_step == 0.1
    assert summary.symnav_failures == 0
    assert summary.symnav_timeouts == 0
    assert summary.first_symnav_step == 7
    assert summary.search_calls == 1
    assert summary.read_calls == 1
    assert summary.patch_calls == 1
    assert summary.command_counts == {"overview": 1}


def test_summarizes_symnav_failures_timeouts_and_skill_reads() -> None:
    events = extract_tool_events(
        {
            "steps": [
                {
                    "step_id": 2,
                    "tool_calls": [
                        {"function_name": "Bash", "arguments": {"command": "symnav resolve Foo"}}
                    ],
                    "observation": "Exit code 1\nnot found",
                },
                {
                    "step_id": 3,
                    "tool_calls": [
                        {"function_name": "Read", "arguments": {"file_path": "/app/.agents/skills/symnav/SKILL.md"}}
                    ],
                },
                {
                    "step_id": 5,
                    "tool_calls": [
                        {"function_name": "Bash", "arguments": {"command": "symnav refs Foo"}}
                    ],
                    "observation": "command timed out",
                },
            ]
        }
    )

    summary = summarize_adoption(events, agent_steps=None)

    assert summary.read_symnav_skill is True
    assert summary.symnav_calls == 2
    assert summary.symnav_calls_per_agent_step == 0.0
    assert summary.symnav_failures == 1
    assert summary.symnav_timeouts == 1
    assert summary.first_symnav_step == 2
    assert summary.command_counts == {"resolve": 1, "refs": 1}


def test_reprocessing_stored_terra_trajectory_reports_real_adoption() -> None:
    summary = summarize_adoption(
        extract_tool_events(_fixture("terra_nested_exec.json")),
        agent_steps=4,
    )

    assert summary.symnav_calls > 0
    assert summary.search_calls > 0
    assert summary.read_calls > 0


def test_codex_exec_commands_extract_in_order() -> None:
    commands = extract_commands(
        {
            "steps": [
                {
                    "step_id": 2,
                    "timestamp": "t1",
                    "tool_calls": [
                        {
                            "function_name": "exec_command",
                            "arguments": {"cmd": "symnav resolve Foo", "workdir": "/repo"},
                        }
                    ],
                }
            ]
        }
    )
    assert commands[0].command == "symnav resolve Foo"
    assert commands[0].args["workdir"] == "/repo"
    assert commands[0].tags == ("symnav:resolve",)


def test_extracts_exit_code_from_matching_observation() -> None:
    commands = extract_commands(
        {
            "steps": [
                {
                    "step_id": 2,
                    "timestamp": "t1",
                    "tool_calls": [
                        {
                            "tool_call_id": "ok",
                            "function_name": "exec_command",
                            "arguments": {"cmd": "symnav resolve Foo"},
                        },
                        {
                            "tool_call_id": "bad",
                            "function_name": "exec_command",
                            "arguments": {"cmd": "symnav resolve Bar"},
                        },
                    ],
                    "observation": {
                        "results": [
                            {"source_call_id": "ok", "content": "Process exited with code 0\nOutput:\nFoo\n"},
                            {"source_call_id": "bad", "content": "Process exited with code 1\nOutput:\nnope\n"},
                        ]
                    },
                }
            ]
        }
    )
    assert commands[0].exit_code == 0
    assert commands[0].succeeded is True
    assert commands[0].output_chars == len("Process exited with code 0\nOutput:\nFoo\n")
    assert commands[0].output == "Process exited with code 0\nOutput:\nFoo\n"
    assert commands[0].output_truncated is False
    assert commands[1].exit_code == 1
    assert commands[1].succeeded is False


def test_extracts_claude_exit_code_format() -> None:
    commands = extract_commands(
        {
            "steps": [
                {
                    "tool_calls": [
                        {
                            "function_name": "Bash",
                            "arguments": {"command": "symnav resolve Foo"},
                        }
                    ],
                    "observation": "Exit code 127\nOutput:\nnot found\n",
                }
            ]
        }
    )
    assert commands[0].exit_code == 127
    assert commands[0].succeeded is False


def test_write_stdin_inherits_running_command() -> None:
    commands = extract_commands(
        {
            "steps": [
                {
                    "step_id": 1,
                    "tool_calls": [
                        {
                            "tool_call_id": "start",
                            "function_name": "exec_command",
                            "arguments": {"cmd": "symnav resolve Foo"},
                        }
                    ],
                    "observation": {
                        "results": [
                            {
                                "source_call_id": "start",
                                "content": "Process running with session ID 123\nOutput:\n",
                            }
                        ]
                    },
                },
                {
                    "step_id": 2,
                    "tool_calls": [
                        {
                            "tool_call_id": "poll",
                            "function_name": "write_stdin",
                            "arguments": {"session_id": 123},
                        }
                    ],
                    "observation": {
                        "results": [
                            {
                                "source_call_id": "poll",
                                "content": "Process exited with code 0\nOutput:\nFoo\n",
                            }
                        ]
                    },
                },
            ]
        }
    )
    assert commands[1].command == "symnav resolve Foo"
    assert commands[1].tags == ("symnav:resolve",)
    assert commands[1].exit_code == 0


def test_claude_tools_extract_and_classify() -> None:
    commands = extract_commands(
        {
            "steps": [
                {"tool_calls": [{"function_name": "Bash", "arguments": {"command": "rg -n Foo"}}]},
                {"tool_calls": [{"function_name": "Read", "arguments": {"file_path": "src/a.ts"}}]},
            ]
        }
    )
    assert [command.tags for command in commands] == [("search",), ("read",)]


def test_classification_matrix() -> None:
    assert classify("Bash", "symnav overview src/a.ts") == ("symnav:overview",)
    assert classify("Bash", "pnpm --dir /opt/symnav --filter symnav dev --cwd /app context Foo") == (
        "symnav:context",
    )
    assert classify("Bash", "pnpm --dir /opt/symnav --filter symnav exec tsx src/cli.ts --cwd /app refs Foo") == (
        "symnav:refs",
    )
    assert classify("Bash", "rg -n symnav . | sed -n '1,20p'") == ("search",)
    assert classify("Bash", "git grep Foo") == ("search",)
    assert classify("Bash", "sed -n '1,2p' src/a.ts") == ("read",)
    assert classify("Bash", "npm test") == ("other",)


def test_timeout_and_jsonl(tmp_path) -> None:
    commands = extract_commands(
        {
            "steps": [
                {
                    "tool_calls": [{"function_name": "exec_command", "arguments": {"cmd": "npm test"}}],
                    "observation": "command timed out",
                }
            ]
        }
    )
    assert commands[0].timed_out is True
    path = tmp_path / "commands.jsonl"
    write_commands_jsonl(commands, path)
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["timed_out"] is True
    assert row["output"] == "command timed out"
    assert row["output_truncated"] is False


def test_long_output_is_truncated_but_original_size_is_kept() -> None:
    output = f"Process exited with code 0\nOutput:\n{'a' * (MAX_COMMAND_OUTPUT_CHARS + 1)}"
    commands = extract_commands(
        {
            "steps": [
                {
                    "tool_calls": [{"function_name": "exec_command", "arguments": {"cmd": "cat huge.txt"}}],
                    "observation": output,
                }
            ]
        }
    )
    assert commands[0].output_chars == len(output)
    assert commands[0].output_truncated is True
    assert len(commands[0].output) <= MAX_COMMAND_OUTPUT_CHARS
    assert "[... truncated " in commands[0].output
    assert commands[0].output.startswith("Process exited with code 0")


def test_malformed_trajectory_returns_empty() -> None:
    assert extract_commands({"steps": "bad"}) == []
