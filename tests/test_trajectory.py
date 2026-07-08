from __future__ import annotations

import json

from symnav_bench.cells.trajectory import classify, extract_commands, write_commands_jsonl


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
    assert json.loads(path.read_text(encoding="utf-8"))["timed_out"] is True


def test_malformed_trajectory_returns_empty() -> None:
    assert extract_commands({"steps": "bad"}) == []
