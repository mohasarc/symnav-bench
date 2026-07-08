from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable


TASK_SLUGS: tuple[str, ...] = (
    "arktype-json-schema-refs-dependencies",
    "awilix-async-container-initialization",
    "clack-async-autocomplete-options",
    "claude-code-by-agents-recursive-delegation",
    "cliffy-config-file-parsing",
    "drizzle-orm-window-function-builders",
    "dynamodb-toolbox-conditional-attribute-requirements",
    "dynamodb-toolbox-lazy-recursive-schemas",
    "effect-sse-httpapi-streaming",
    "eicrud-keyset-pagination-cursor",
    "happy-dom-abort-pending-body-reads",
    "happy-dom-deterministic-intersectionobserver",
    "httpx-deterministic-cookie-store",
    "ink-grid-box-layout",
    "kea-atomic-signal-selectors",
    "koota-composite-trait-aspects",
    "koota-deferred-mutation-buffer",
    "koota-pair-relation-tracking",
    "koota-query-predicates",
    "kysely-window-grouping-helpers",
    "meriyah-explicit-resource-declarations",
    "obsidian-linter-auto-table-of-contents",
    "obsidian-linter-link-format-conversion",
    "obsidian-linter-scoped-ignore-markers",
    "ofetch-per-origin-circuit-breaker",
    "optique-conditional-option-dependencies",
    "prometheus-transactional-reload-status",
    "query-persist-restored-query-state",
    "quill-shared-toolbar-focus",
    "sql-formatter-bigquery-pipe-formatting",
    "superjson-error-stack-serialization",
    "true-myth-iterable-collection-combinators",
    "ts-pattern-match-each",
    "valibot-recursive-schema-composition",
    "vitest-duration-sharding",
)

DEFAULT_DEEPSWE_REPO = "https://github.com/datacurve-ai/deep-swe.git"

GitRunner = Callable[[list[str]], None]


def configured_tasks_dir() -> Path | None:
    value = os.environ.get("DEEPSWE_TASKS_DIR")
    return Path(value) if value else None


def default_deepswe_root() -> Path:
    return Path(os.environ.get("DEEPSWE_ROOT", "/tmp/deep-swe"))


def ensure_deepswe_tasks(
    ref: str,
    root: Path | None = None,
    repo: str = DEFAULT_DEEPSWE_REPO,
    runner: GitRunner | None = None,
) -> Path:
    checkout = root or default_deepswe_root()
    run = runner or _run
    if (checkout / ".git").exists():
        run(["git", "-C", str(checkout), "fetch", "--depth", "1", "origin", ref])
        run(["git", "-C", str(checkout), "checkout", "FETCH_HEAD"])
    else:
        checkout.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--depth", "1", repo, str(checkout)])
        run(["git", "-C", str(checkout), "fetch", "--depth", "1", "origin", ref])
        run(["git", "-C", str(checkout), "checkout", "FETCH_HEAD"])
    tasks_dir = checkout / "tasks"
    if not tasks_dir.is_dir():
        raise FileNotFoundError(f"DeepSWE checkout has no tasks dir: {tasks_dir}")
    return tasks_dir


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)
