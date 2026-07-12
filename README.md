# symnav-bench

Reproducible DeepSWE/Pier harness for comparing agent runs with and without
symnav.

## Local use

```bash
python -m pip install -e '.[dev]'
pytest
symnav-bench list-tasks
```

Run one cell:

```bash
symnav-bench run \
  --agent codex:gpt-5.4:xhigh \
  --conditions stock \
  --tasks ts-pattern-match-each \
  --results-dir results
```

Generate a study report:

```bash
symnav-bench report --study studies/typescript-primary --out report
```

Stored v1 cells remain available in a separate Legacy report and never enter
study statistics:

```bash
symnav-bench report --cells results --out legacy-report
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
| `DEEPSWE_TASKS_DIR` | Existing task directory. When unset, `run` clones DeepSWE at runtime. |
| `DEEPSWE_ROOT` | Runtime DeepSWE checkout path. Defaults to `/tmp/deep-swe` locally and `/work/deep-swe` in the image. |
| `CLAUDE_CODE_OAUTH_TOKEN` | Preferred Claude auth for Claude Code arms. |
| `ANTHROPIC_API_KEY` | Claude fallback auth. |
| `CODEX_AUTH_JSON_B64` | Base64 encoded Codex auth JSON. |
| `SYMNAV_BENCH_VERSION` | Image version recorded into cells. |

## DeepSWE redistribution

The Docker image keeps only the task slug catalog. It does not redistribute
DeepSWE task contents. `run` downloads DeepSWE from the public upstream repo at
execution time when `DEEPSWE_TASKS_DIR` is not supplied.
