from __future__ import annotations


try:
    from pier.agents.installed.claude_code import ClaudeCode
    from pier.agents.installed.codex import Codex
except Exception:

    class _BaseAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.install_steps = tuple(kwargs.get("install_steps", ()))
            self.network_allowlist = tuple(kwargs.get("network_allowlist", ()))

    class ClaudeCode(_BaseAgent):
        pass

    class Codex(_BaseAgent):
        pass
