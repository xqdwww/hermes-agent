#!/usr/bin/env bash
set -euo pipefail

HERMES_PYTHON="${HERMES_PYTHON:-/Users/xqdwww/Workspace/AI_Core/hermes-agent/.venv/bin/python}"
HOST="${OMLX_HOST:-127.0.0.1}"
PORT="${OMLX_PORT:-8000}"
BASE_URL="${OMLX_BASE_URL:-http://${HOST}:${PORT}}"
EXPECTED_CEILING_GB="${OMLX_MEMORY_GUARD_GB:-120}"
MODEL="${OMLX_NEMOTRON_MODEL:-NVIDIA-Nemotron-3-Super-120B-A12B-5bit}"
MODEL_DIR="${OMLX_MODEL_DIR:-/Users/xqdwww/Workspace/AI_Core/mlx_models}"
MIN_DISK_FREE_GB="${OMLX_MIN_DISK_FREE_GB:-20}"
PROMPT="${OMLX_PREFLIGHT_PROMPT:-Reply exactly: HERMES_NEMOTRON_PREFLIGHT_OK}"
EXPECTED_TEXT="${OMLX_PREFLIGHT_EXPECTED_TEXT:-HERMES_NEMOTRON_PREFLIGHT_OK}"
MAX_TOKENS="${OMLX_PREFLIGHT_MAX_TOKENS:-128}"
AUDIT_DIR="${OMLX_PREFLIGHT_AUDIT_DIR:-/private/tmp/hermes_omlx_preflight}"

if [[ ! -x "$HERMES_PYTHON" ]]; then
  HERMES_PYTHON="$(command -v python3 || true)"
fi

"$HERMES_PYTHON" - "$BASE_URL" "$EXPECTED_CEILING_GB" "$MODEL" "$MODEL_DIR" "$MIN_DISK_FREE_GB" "$PROMPT" "$EXPECTED_TEXT" "$MAX_TOKENS" "$AUDIT_DIR" <<'PY'
import json
import os
import pathlib
import socket
import sys
import time
import urllib.error
import urllib.request

base_url, expected_ceiling_gb, model, model_dir, min_disk_free_gb, prompt, expected_text, max_tokens, audit_dir = sys.argv[1:10]
expected_ceiling_bytes = float(expected_ceiling_gb) * (1024 ** 3)

def emit(status, blocker="", **extra):
    payload = {"status": status}
    if blocker:
        payload["blocker"] = blocker
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False))

def env_file_value(key, path=pathlib.Path("/Users/xqdwww/.hermes/.env")):
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("export "):
                stripped = stripped[len("export "):]
            if stripped.startswith(key + "="):
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""

def request(method, path, body=None, timeout=120, opener=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = dict(headers or {})
    if data:
        request_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=request_headers,
        method=method,
    )
    opener = opener or urllib.request.build_opener()
    with opener.open(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    return json.loads(text) if text else {}

def write_audit(name, payload):
    try:
        audit_path = pathlib.Path(audit_dir)
        audit_path.mkdir(parents=True, exist_ok=True)
        path = audit_path / name
        if isinstance(payload, (dict, list)):
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            path.write_text(str(payload), encoding="utf-8")
        return str(path)
    except Exception:
        return ""

try:
    stat = os.statvfs(model_dir if os.path.exists(model_dir) else "/")
    disk_free_gb = round(stat.f_bavail * stat.f_frsize / (1024 ** 3), 2)
except OSError:
    disk_free_gb = 0.0
if disk_free_gb < float(min_disk_free_gb):
    emit("BLOCKED", "DISK_TOO_LOW", disk_free_gb=disk_free_gb, minimum_required_gb=float(min_disk_free_gb))
    raise SystemExit(1)

server_pids = [
    pid for pid in os.popen("pgrep -x omlx-server 2>/dev/null").read().split()
    if pid.strip()
]
if not server_pids:
    emit("BLOCKED", "OMLX_NOT_RUNNING", disk_free_gb=disk_free_gb)
    raise SystemExit(1)
if len(server_pids) != 1:
    emit("BLOCKED", "OMLX_MULTIPLE_SERVERS", server_pids=server_pids, disk_free_gb=disk_free_gb)
    raise SystemExit(1)

try:
    health = request("GET", "/health", timeout=10)
except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
    emit("BLOCKED", "OMLX_TIMEOUT", error=str(exc), server_pids=server_pids, disk_free_gb=disk_free_gb)
    raise SystemExit(1)
except Exception as exc:
    emit("BLOCKED", "OMLX_NOT_RUNNING", error=str(exc), server_pids=server_pids, disk_free_gb=disk_free_gb)
    raise SystemExit(1)

detected_ceiling = float(health.get("engine_pool", {}).get("final_ceiling", 0))
if abs(detected_ceiling - expected_ceiling_bytes) > (0.25 * 1024 ** 3):
    emit(
        "BLOCKED",
        "OMLX_WRONG_CEILING",
        ceiling_detected_gb=round(detected_ceiling / (1024 ** 3), 2),
        expected_ceiling_gb=float(expected_ceiling_gb),
        server_pids=server_pids,
        disk_free_gb=disk_free_gb,
    )
    raise SystemExit(1)

api_key = os.environ.get("OMLX_API_KEY", "").strip() or env_file_value("OMLX_API_KEY")
if not api_key:
    emit("BLOCKED", "OMLX_AUTH_BLOCKED", message="OMLX_API_KEY missing", disk_free_gb=disk_free_gb)
    raise SystemExit(1)

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
try:
    login = request("POST", "/admin/api/login", {"api_key": api_key}, timeout=20, opener=opener)
    if not login.get("success"):
        emit("BLOCKED", "OMLX_AUTH_BLOCKED", message="admin login failed", disk_free_gb=disk_free_gb)
        raise SystemExit(1)
    load_started = time.time()
    load = request("POST", f"/admin/api/models/{model}/load", timeout=900, opener=opener)
    load_elapsed = round(time.time() - load_started, 2)
    if load.get("error"):
        detail = str(load.get("detail") or load.get("status") or "load failed")
        blocker = "MEMORY_TOO_LOW" if any(token in detail.lower() for token in ("memory", "ceiling", "guard")) else "NEMOTRON_LOAD_FAILED"
        emit("BLOCKED", blocker, model=model, detail=detail[:800], disk_free_gb=disk_free_gb, load_elapsed_seconds=load_elapsed)
        raise SystemExit(1)
    chat_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a Hermes local model preflight checker. Return the requested sentinel exactly and completely."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": int(max_tokens),
        "temperature": 0,
    }
    raw_request_path = write_audit("nemotron_preflight_request.json", chat_body)
    chat = request(
        "POST",
        "/v1/chat/completions",
        chat_body,
        timeout=600,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    raw_response_path = write_audit("nemotron_preflight_response.json", chat)
    content = ""
    try:
        content = chat["choices"][0]["message"]["content"]
    except Exception:
        content = json.dumps(chat, ensure_ascii=False)[:800]
    response_ok = expected_text in str(content)
    unload = request("POST", f"/admin/api/models/{model}/unload", timeout=120, opener=opener)
except SystemExit:
    raise
except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
    emit("BLOCKED", "OMLX_TIMEOUT", error=str(exc), disk_free_gb=disk_free_gb)
    raise SystemExit(1)
except Exception as exc:
    emit("BLOCKED", "NEMOTRON_LOAD_FAILED", error=str(exc), disk_free_gb=disk_free_gb)
    raise SystemExit(1)

if not response_ok:
    emit(
        "BLOCKED",
        "NEMOTRON_LOAD_FAILED",
        message="Nemotron loaded but did not return expected preflight text",
        response_preview=str(content)[:300],
        response_length=len(str(content)),
        raw_request=raw_request_path,
        raw_response=raw_response_path,
        disk_free_gb=disk_free_gb,
    )
    raise SystemExit(1)

emit(
    "PASS",
    server_pid=server_pids[0],
    single_instance=True,
    ceiling_detected_gb=round(detected_ceiling / (1024 ** 3), 2),
    model=model,
    nemotron_loaded=True,
    nemotron_responded=True,
    nemotron_unloaded=not bool(unload.get("error")),
    disk_free_gb=disk_free_gb,
    load_elapsed_seconds=load_elapsed,
)
PY
