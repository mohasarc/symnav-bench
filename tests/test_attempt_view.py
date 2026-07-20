from symnav_bench.report.attempt_view import build_attempt_view


def _trajectory():
    return {
        "agent": {
            "name": "codex",
            "version": "1.0",
            "model_name": "gpt-x",
            "extra": {"cwd": "/app", "git": {"branch": "main", "commit_hash": "abc"}},
        },
        "final_metrics": {
            "total_prompt_tokens": 100,
            "total_completion_tokens": 20,
            "total_cached_tokens": 80,
            "total_steps": 3,
            "total_cost_usd": 0.5,
            "extra": {"reasoning_output_tokens": 5, "peak_context_tokens": 90},
        },
        "steps": [
            {"step_id": 1, "timestamp": "t0", "source": "system", "message": "instructions"},
            {"step_id": 2, "timestamp": "t1", "source": "user", "message": "the task"},
            {
                "step_id": 3,
                "timestamp": "t2",
                "source": "agent",
                "message": "running a command",
                "metrics": {"prompt_tokens": 10, "completion_tokens": 4, "cached_tokens": 8},
                "tool_calls": [
                    {
                        "tool_call_id": "c1",
                        "function_name": "exec",
                        "arguments": {
                            "input": 'const r = await tools.exec_command({"cmd":"ls -a","workdir":"/app"});\ntext(r.output);\n'
                        },
                    }
                ],
                "observation": {"results": [{"source_call_id": "c1", "content": "file.ts"}]},
            },
            {
                "step_id": 4,
                "timestamp": "t3",
                "source": "agent",
                "message": "editing",
                "tool_calls": [
                    {
                        "tool_call_id": "c2",
                        "function_name": "exec",
                        "arguments": {
                            "input": 'const patch = "*** Begin Patch\\n*** Update File: /app/a.ts\\n+added\\n*** End Patch";\nawait tools.apply_patch(patch);\n'
                        },
                    }
                ],
                "observation": {"results": [{"source_call_id": "c2", "content": "ok"}]},
            },
        ],
    }


def _summary():
    return {
        "identity": {"attempt_id": "abc123"},
        "slot": {"slot_id": "s1", "task": "demo", "condition": "symnav", "repetition": 2},
        "disposition": {"outcome": "passed"},
        "rewards": {"reward": 1, "f2p_passed": 5, "f2p_total": 5},
        "usage": {"n_output_tokens": 20},
        "timing": {"started_at": "t0", "finished_at": "t3"},
    }


def test_build_attempt_view_extracts_steps_tools_and_patch():
    view = build_attempt_view(_trajectory(), _summary(), {"tests": {"passed": 5, "failed": []}})

    assert view["attempt_id"] == "abc123"
    assert view["task"] == "demo"
    assert view["condition"] == "symnav"
    assert view["outcome"] == "passed"
    assert view["totals"]["steps"] == 3
    assert len(view["steps"]) == 4

    exec_step = view["steps"][2]
    assert exec_step["source"] == "agent"
    assert exec_step["tools"][0]["tool"] == "exec_command"
    assert exec_step["tools"][0]["command"] == "ls -a"
    assert exec_step["tools"][0]["output"] == "file.ts"

    # apply_patch passed as a JS variable is still recovered as the patch body
    assert view["patches"] == ["*** Begin Patch\n*** Update File: /app/a.ts\n+added\n*** End Patch"]
    assert view["environment"]["system_messages"] == ["instructions"]
    assert view["verifier"]["tests"]["passed"] == 5
