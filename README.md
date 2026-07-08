# symnav-bench

Reproducible DeepSWE/Pier harness for comparing agent runs with and without
symnav.

## Local use

```bash
python -m pip install -e '.[dev]'
pytest
symnav-bench list-tasks --tasks-dir /path/to/deep-swe/tasks
```

Run one cell:

```bash
symnav-bench run \
  --agent codex:gpt-5.4:xhigh \
  --conditions stock \
  --tasks ts-pattern-match-each \
  --tasks-dir /opt/deep-swe/tasks \
  --results-dir results
```

Generate report:

```bash
symnav-bench report --cells results --out report
```

## Docker

```bash
docker run --privileged \
  -e CLAUDE_CODE_OAUTH_TOKEN=... \
  -e CODEX_AUTH_JSON_B64=... \
  -v "$PWD/results:/results" \
  ghcr.io/mohasarc/symnav-bench:v0.1 \
  run --agent codex:gpt-5.4:xhigh --conditions symnav,stock --tasks all --results-dir /results
```

`CODEX_AUTH_JSON_B64` is decoded into Codex auth state by the entrypoint.
Mounting `/var/lib/docker` as a cache volume speeds repeated DeepSWE task
containers.

Costs in reports are labeled `cost_usd_imputed` because they come from Pier's
trial output, not billing records.

## Environment

| Variable | Purpose |
| --- | --- |
| `DEEPSWE_TASKS_DIR` | Default task directory for `list-tasks` and `run`. |
| `CLAUDE_CODE_OAUTH_TOKEN` | Preferred Claude auth for Claude Code arms. |
| `ANTHROPIC_API_KEY` | Claude fallback auth. |
| `CODEX_AUTH_JSON_B64` | Base64 encoded Codex auth JSON. |
| `SYMNAV_BENCH_VERSION` | Image version recorded into cells. |

## DeepSWE redistribution

The Docker image clones DeepSWE into `/opt/deep-swe`.

Redistribution permitted: no.

As of 2026-07-09, the public `datacurve-ai/deep-swe` GitHub repo did not expose
a `LICENSE` file at `main`. Do not publish a public GHCR image containing the
tasks until upstream license or written permission explicitly permits
redistribution.
