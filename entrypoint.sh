#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--version" ]]; then
  exec symnav-bench "$@"
fi

dockerd-entrypoint.sh dockerd >/tmp/dockerd.log 2>&1 &

for _ in $(seq 1 60); do
  if docker info >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! docker info >/dev/null 2>&1; then
  cat /tmp/dockerd.log >&2
  exit 1
fi

if [[ -n "${CODEX_AUTH_JSON_B64:-}" ]]; then
  mkdir -p "${HOME}/.codex"
  printf '%s' "${CODEX_AUTH_JSON_B64}" | base64 -d > "${HOME}/.codex/auth.json"
fi

exec symnav-bench "$@"
