#!/usr/bin/env bash
set -euo pipefail

PIDFILE="${OMLX_PIDFILE:-/Users/xqdwww/.omlx/hermes-controlled.pid}"
OMLX_BIN="${OMLX_BIN:-/Users/xqdwww/.omlx/bin/omlx}"
HERMES_PYTHON="${HERMES_PYTHON:-/Users/xqdwww/Workspace/AI_Core/hermes-agent/.venv/bin/python}"
STOP_TIMEOUT_SECONDS="${OMLX_STOP_TIMEOUT_SECONDS:-20}"
STOP_ALL=false

for arg in "$@"; do
  case "$arg" in
    --all) STOP_ALL=true ;;
    *) echo "{\"status\":\"FAIL\",\"blocker\":\"UNKNOWN_ARGUMENT\",\"argument\":\"$arg\"}"; exit 2 ;;
  esac
done

if [[ ! -x "$HERMES_PYTHON" ]]; then
  HERMES_PYTHON="$(command -v python3 || true)"
fi

is_omlx_server_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  ps -p "$pid" -o comm= 2>/dev/null | grep -qx "omlx-server"
}

stop_pid() {
  local pid="$1"
  if ! is_omlx_server_pid "$pid"; then
    return 1
  fi
  kill "$pid" 2>/dev/null || true
  local deadline=$((SECONDS + STOP_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

stopped=()
skipped=()
stop_source="pidfile"

if [[ -x "$OMLX_BIN" ]]; then
  "$OMLX_BIN" stop --timeout "$STOP_TIMEOUT_SECONDS" >/dev/null 2>&1 || true
fi

if "$STOP_ALL"; then
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    if is_omlx_server_pid "$pid"; then
      stop_pid "$pid" || true
      stopped+=("$pid")
    fi
  done < <(pgrep -x omlx-server 2>/dev/null || true)
else
  if [[ -f "$PIDFILE" ]]; then
    pid="$(tr -cd '0-9' < "$PIDFILE" || true)"
    if is_omlx_server_pid "$pid"; then
      stop_pid "$pid" || true
      stopped+=("$pid")
    elif [[ -n "$pid" ]]; then
      skipped+=("$pid")
    fi
  fi
  if [[ "${#stopped[@]}" == "0" ]]; then
    discovered_pids=()
    while IFS= read -r discovered_pid; do
      [[ -n "$discovered_pid" ]] || continue
      discovered_pids+=("$discovered_pid")
    done < <(pgrep -x omlx-server 2>/dev/null || true)
    if [[ "${#discovered_pids[@]}" == "1" ]]; then
      stop_source="discovered_singleton"
      stop_pid "${discovered_pids[0]}" || true
      stopped+=("${discovered_pids[0]}")
    fi
  fi
fi

rm -f "$PIDFILE"
remaining="$( (pgrep -x omlx-server 2>/dev/null || true) | wc -l | tr -d ' ')"

"$HERMES_PYTHON" - "${stopped[*]:-}" "${skipped[*]:-}" "$remaining" "$stop_source" <<'PY'
import json, sys
stopped = [p for p in sys.argv[1].split() if p]
skipped = [p for p in sys.argv[2].split() if p]
remaining = int(sys.argv[3])
stop_source = sys.argv[4]
print(json.dumps({
    "status": "OK" if remaining == 0 else "PARTIAL",
    "stopped_pids": stopped,
    "skipped_non_omlx_pids": skipped,
    "remaining_omlx_server_count": remaining,
    "stop_source": stop_source,
}, ensure_ascii=False))
PY
