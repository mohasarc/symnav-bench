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
    assert commands[1].exit_code == 1
    assert commands[1].succeeded is False


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
    assert json.loads(path.read_text(encoding="utf-8"))["timed_out"] is True


def test_malformed_trajectory_returns_empty() -> None:
    assert extract_commands({"steps": "bad"}) == []
