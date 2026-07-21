from __future__ import annotations

from symnav_bench.agents.install import (
    append_text_step,
    pinned_symnav_install_script,
    toolchain_root_step,
    workspace_capture_step,
    write_text_step,
)


def test_pinned_symnav_install_script_checks_out_sha_and_builds() -> None:
    script = pinned_symnav_install_script(
        "a" * 40,
        codex=True,
        allowed_commands=("overview", "refs"),
    )

    assert "git checkout 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'" in script
    assert "pnpm install --frozen-lockfile" in script
    assert "pnpm build" in script
    assert "allowed_commands='overview refs'" in script
    assert "Unsupported symnav invocation for this benchmark arm." in script
    assert 'exec pnpm --dir /opt/symnav --filter symnav dev --cwd /app "\\$@"' in script
    assert "ln -sf /app/bin/symnav /usr/local/bin/symnav" in script


def test_toolchain_root_creates_claude_compat_links() -> None:
    step = toolchain_root_step()
    assert "[ -e /app/.claude/skills ] || ln -s ../.agents/skills /app/.claude/skills" in step.command
    assert "[ -e /app/CLAUDE.md ] || ln -s AGENTS.md /app/CLAUDE.md" in step.command
    assert "bin/symnav .agents/ .claude/ AGENTS.md CLAUDE.md" in step.command


def test_write_text_step_base64_encodes_multiword_text() -> None:
    step = write_text_step("/app/AGENTS.md", "hello world")
    assert "hello world" not in step.command
    assert "base64 -d" in step.command


def test_append_text_step_preserves_tracked_instruction_files() -> None:
    step = append_text_step("/app/AGENTS.md", "hello world")
    assert "hello world" not in step.command
    assert "symnav-bench injected instructions" in step.command
    assert "update-index --skip-worktree" in step.command
    assert ">> \"$path\"" in step.command


def test_workspace_capture_step_wraps_agent_binary(tmp_path) -> None:
    step = workspace_capture_step(tmp_path / "agent", ("codex",))
    assert "symnav-bench-capture-workspace" in step.command
    assert str(tmp_path / "agent") in step.command
    assert "workspace/app" in step.command
    assert "git -C /app diff >" in step.command
    assert 'real_copy="$real.symnav-bench-real"' in step.command
    assert 'mv "$real" "$real_copy"' in step.command
    assert 'cat > "$real" <<EOF' in step.command
    assert 'SYMNAV_BENCH_WORKSPACE_CAPTURE_DIR="$capture_dir" "$real_copy"' in step.command


def test_workspace_capture_defaults_to_persisted_agent_logs() -> None:
    step = workspace_capture_step(None, ("claude",))
    assert "logs_dir=/logs/agent" in step.command
    assert "workspace/app" in step.command


def test_install_layer_targets_the_task_workdir() -> None:
    script = pinned_symnav_install_script(
        "a" * 40,
        codex=True,
        allowed_commands=("overview",),
        workdir="/testbed",
    )

    assert 'exec pnpm --dir /opt/symnav --filter symnav dev --cwd /testbed "\\$@"' in script
    assert "ln -sf /testbed/bin/symnav /usr/local/bin/symnav" in script
    assert "/app" not in script

    root_step = toolchain_root_step("/testbed")
    assert "/testbed/.git/info" in root_step.command
    assert "/app" not in root_step.command

    append_step = append_text_step("/testbed/AGENTS.md", "hello", workdir="/testbed")
    assert 'rel="${path#/testbed/}"' in append_step.command
    assert "git -C /testbed" in append_step.command
    assert "/app" not in append_step.command

    capture_step = workspace_capture_step(None, ("codex",), workdir="/testbed")
    assert "git -C /testbed diff >" in capture_step.command
    assert "/app/" not in capture_step.command


def test_symnav_install_bootstraps_node_and_pnpm_when_missing() -> None:
    script = pinned_symnav_install_script(
        "a" * 40,
        codex=True,
        allowed_commands=("overview",),
    )

    assert "command -v pnpm" in script
    assert "nvm-sh/nvm" in script
    assert "nvm install 22" in script
    assert "npm install -g pnpm@10" in script
    assert 'PATH="$symnav_bench_node_bin:\\$PATH"' in script
