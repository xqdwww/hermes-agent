#!/usr/bin/env bash
set -euo pipefail

OMLX_BIN="${OMLX_BIN:-/Users/xqdwww/.omlx/bin/omlx}"
HERMES_PYTHON="${HERMES_PYTHON:-/Users/xqdwww/Workspace/AI_Core/hermes-agent/.venv/bin/python}"
MODEL_DIR="${OMLX_MODEL_DIR:-/Users/xqdwww/Workspace/AI_Core/mlx_models}"
BASE_PATH="${OMLX_BASE_PATH:-/Users/xqdwww/.omlx}"
HOST="${OMLX_HOST:-127.0.0.1}"
PORT="${OMLX_PORT:-8000}"
MEMORY_GUARD_GB="${OMLX_MEMORY_GUARD_GB:-120}"
LOG_DIR="${OMLX_LOG_DIR:-/Users/xqdwww/.omlx/logs}"
PIDFILE="${OMLX_PIDFILE:-/Users/xqdwww/.omlx/hermes-controlled.pid}"
START_TIMEOUT_SECONDS="${OMLX_START_TIMEOUT_SECONDS:-60}"
MIN_DISK_FREE_GB="${OMLX_MIN_DISK_FREE_GB:-20}"
STOP_SCRIPT="${OMLX_STOP_SCRIPT:-/Users/xqdwww/Workspace/AI_Core/hermes-agent/scripts/omlx_stop_controlled.sh}"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    *) echo "{\"status\":\"FAIL\",\"blocker\":\"UNKNOWN_ARGUMENT\",\"argument\":\"$arg\"}"; exit 2 ;;
  esac
done

if [[ ! -x "$HERMES_PYTHON" ]]; then
  HERMES_PYTHON="$(command -v python3 || true)"
fi

json_escape() {
  "$HERMES_PYTHON" -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

disk_free_gb() {
  "$HERMES_PYTHON" - "$MODEL_DIR" <<'PY'
import os, sys
path = sys.argv[1]
stat = os.statvfs(path if os.path.exists(path) else "/")
print(round(stat.f_bavail * stat.f_frsize / (1024**3), 2))
PY
}

health_json() {
  curl -sS --max-time 5 "http://${HOST}:${PORT}/health" 2>/dev/null || true
}

process_count() {
  (pgrep -x omlx-server 2>/dev/null || true) | wc -l | tr -d ' '
}

health_ceiling_gb() {
  "$HERMES_PYTHON" -c 'import json,sys; data=json.load(sys.stdin); print(round(float(data.get("engine_pool",{}).get("final_ceiling",0))/(1024**3), 2))' 2>/dev/null || echo 0
}

free_gb="$(disk_free_gb)"
if "$DRY_RUN"; then
  cat <<JSON
{"status":"DRY_RUN","command":["$OMLX_BIN","serve","--model-dir","$MODEL_DIR","--host","$HOST","--port","$PORT","--memory-guard-gb","$MEMORY_GUARD_GB","--base-path","$BASE_PATH"],"pidfile":"$PIDFILE","log_dir":"$LOG_DIR","disk_free_gb":$free_gb}
JSON
  exit 0
fi

disk_ok="$("$HERMES_PYTHON" - "$free_gb" "$MIN_DISK_FREE_GB" <<'PY'
import sys
print("yes" if float(sys.argv[1]) >= float(sys.argv[2]) else "no")
PY
)"
if [[ "$disk_ok" != "yes" ]]; then
  cat <<JSON
{"status":"BLOCKED","blocker":"DISK_TOO_LOW","disk_free_gb":$free_gb,"minimum_required_gb":$MIN_DISK_FREE_GB}
JSON
  exit 1
fi

mkdir -p "$LOG_DIR" "$(dirname "$PIDFILE")"

"$HERMES_PYTHON" - "$BASE_PATH/settings.json" "$MODEL_DIR" "$HOST" "$PORT" "$MEMORY_GUARD_GB" <<'PY'
import json
import pathlib
import sys

settings_path = pathlib.Path(sys.argv[1])
model_dir, host, port, ceiling_gb = sys.argv[2:6]
try:
    data = json.loads(settings_path.read_text(encoding="utf-8"))
except Exception:
    data = {}
data.setdefault("version", "1.0")
server = data.setdefault("server", {})
server["host"] = host
server["port"] = int(port)
server.setdefault("auto_start_on_launch", True)
model = data.setdefault("model", {})
model["model_dir"] = model_dir
model["model_dirs"] = [model_dir]
memory = data.setdefault("memory", {})
memory["prefill_memory_guard"] = True
memory["memory_guard_tier"] = "custom"
memory["memory_guard_custom_ceiling_gb"] = float(ceiling_gb)
settings_path.parent.mkdir(parents=True, exist_ok=True)
settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

count="$(process_count)"
if [[ "$count" != "0" ]]; then
  health="$(health_json)"
  ceiling="$(printf '%s' "$health" | health_ceiling_gb)"
  if [[ "$count" == "1" && "$ceiling" == "$MEMORY_GUARD_GB"* ]]; then
    pid="$(pgrep -x omlx-server | head -1)"
    echo "$pid" > "$PIDFILE"
    cat <<JSON
{"status":"OK","already_running":true,"pid":$pid,"single_instance":true,"memory_ceiling_gb":$ceiling,"disk_free_gb":$free_gb}
JSON
    exit 0
  fi
  "$OMLX_BIN" stop --timeout 20 >/dev/null 2>&1 || true
  "$STOP_SCRIPT" --all >/dev/null
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
stdout_log="$LOG_DIR/hermes-omlx-controlled.${timestamp}.out.log"
stderr_log="$LOG_DIR/hermes-omlx-controlled.${timestamp}.err.log"

if ! "$OMLX_BIN" start --timeout "$START_TIMEOUT_SECONDS" >"$stdout_log" 2>"$stderr_log"; then
  first_start_log="$(tail -80 "$stderr_log" "$stdout_log" 2>/dev/null || true)"
  if printf '%s' "$first_start_log" | grep -q "control socket"; then
    /usr/bin/open -a oMLX >/dev/null 2>&1 || true
    sleep 5
    if ! "$OMLX_BIN" start --timeout "$START_TIMEOUT_SECONDS" >>"$stdout_log" 2>>"$stderr_log"; then
      escaped_health="$(tail -120 "$stderr_log" "$stdout_log" 2>/dev/null | json_escape)"
      cat <<JSON
{"status":"BLOCKED","blocker":"OMLX_TIMEOUT","stdout_log":"$stdout_log","stderr_log":"$stderr_log","last_health":"$escaped_health"}
JSON
      exit 1
    fi
  else
    escaped_health="$(printf '%s' "$first_start_log" | json_escape)"
    cat <<JSON
{"status":"BLOCKED","blocker":"OMLX_TIMEOUT","stdout_log":"$stdout_log","stderr_log":"$stderr_log","last_health":"$escaped_health"}
JSON
    exit 1
  fi
fi

deadline=$((SECONDS + START_TIMEOUT_SECONDS))
last_health=""
while (( SECONDS < deadline )); do
  count="$(process_count)"
  last_health="$(health_json)"
  if [[ "$count" == "1" && -n "$last_health" ]]; then
    ceiling="$(printf '%s' "$last_health" | health_ceiling_gb)"
    if [[ "$ceiling" == "$MEMORY_GUARD_GB"* ]]; then
      pid="$(pgrep -x omlx-server | head -1)"
      sleep 2
      stable_count="$(process_count)"
      stable_health="$(health_json)"
      stable_ceiling="$(printf '%s' "$stable_health" | health_ceiling_gb)"
      if [[ "$stable_count" != "1" || "$stable_ceiling" != "$MEMORY_GUARD_GB"* ]]; then
        last_health="$stable_health"
        continue
      fi
      stable_pid="$(pgrep -x omlx-server | head -1)"
      echo "$stable_pid" > "$PIDFILE"
      cat <<JSON
{"status":"OK","started":true,"pid":$stable_pid,"single_instance":true,"memory_ceiling_gb":$stable_ceiling,"preload_nemotron_at_boot":false,"stdout_log":"$stdout_log","stderr_log":"$stderr_log","disk_free_gb":$free_gb}
JSON
      exit 0
    fi
  fi
  sleep 1
done

if [[ -s "$stderr_log" || -s "$stdout_log" ]]; then
  last_health="$(tail -80 "$stderr_log" "$stdout_log" 2>/dev/null | "$HERMES_PYTHON" -c 'import json,sys; print(json.dumps(sys.stdin.read())[:2000])')"
fi

escaped_health="$(printf '%s' "$last_health" | json_escape)"
cat <<JSON
{"status":"BLOCKED","blocker":"OMLX_TIMEOUT","pidfile":"$PIDFILE","stdout_log":"$stdout_log","stderr_log":"$stderr_log","last_health":"$escaped_health"}
JSON
exit 1
