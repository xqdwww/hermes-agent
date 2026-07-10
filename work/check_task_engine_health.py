#!/usr/bin/env python3
"""Lightweight health check for Hermes task_engine_runner.

This script intentionally avoids real full-runs and model execution stages.
It performs compile/test checks, preflights, bridge health, and dry/simulated
contract checks only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODES = {
    "RESEARCH": 6,
    "DECISION": 10,
    "RESEARCH_DECISION": 16,
}
QUERY = "这是一个研究决策任务。health check only."
KEY_FILES = [
    "tools/task_engine_contracts.py",
    "tools/task_engine_executors.py",
    "tools/task_engine_runner.py",
]


def _tail(text: str, limit: int = 4000) -> str:
    return (text or "")[-limit:]


def _run(cmd: list[str], timeout_s: int) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout_s,
        )
        return {
            "passed": proc.returncode == 0,
            "returncode": proc.returncode,
            "elapsed_seconds": round(time.time() - started, 2),
            "stdout_tail": _tail(proc.stdout),
            "stderr_tail": _tail(proc.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "passed": False,
            "returncode": None,
            "elapsed_seconds": round(time.time() - started, 2),
            "stdout_tail": _tail(_decode_timeout_part(exc.stdout)),
            "stderr_tail": _tail(_decode_timeout_part(exc.stderr)),
            "error": "timeout",
        }


def _decode_timeout_part(part: str | bytes | None) -> str:
    if part is None:
        return ""
    if isinstance(part, bytes):
        return part.decode("utf-8", errors="replace")
    return part


def _pytest_passed_count(output: str) -> int | None:
    match = re.search(r"(\d+)\s+passed", output or "")
    if not match:
        return None
    return int(match.group(1))


def _load_runner() -> Any:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.task_engine_runner import task_engine_runner

    return task_engine_runner


def _runner_json(**kwargs: Any) -> dict[str, Any]:
    task_engine_runner = _load_runner()
    raw = task_engine_runner(**kwargs)
    return json.loads(raw)


def _preflight_checks() -> dict[str, Any]:
    agy = _runner_json(query=QUERY, mode="RESEARCH_DECISION", action="agy-preflight")
    omlx = _runner_json(query=QUERY, mode="RESEARCH_DECISION", action="omlx-preflight")
    return {
        "agy_preflight": {
            "passed": agy.get("status") == "AGY_OK",
            "status": agy.get("status"),
            "blocked_stage": agy.get("blocked_stage", ""),
            "blocked_reason": agy.get("blocked_reason", ""),
            "required_models": agy.get("required_models", []),
            "missing_models": agy.get("missing_models", []),
            "elapsed_seconds": agy.get("elapsed_seconds"),
        },
        "omlx_preflight": {
            "passed": omlx.get("status") == "OMLX_OK",
            "status": omlx.get("status"),
            "blocked_stage": omlx.get("blocked_stage", ""),
            "blocked_reason": omlx.get("blocked_reason", ""),
            "key_source": omlx.get("key_source", ""),
            "key_fingerprint_present": bool(omlx.get("key_fingerprint")),
            "actual_r1_model": omlx.get("actual_r1_model", ""),
            "model_visible": bool(omlx.get("model_visible")),
            "elapsed_seconds": omlx.get("elapsed_seconds"),
        },
    }


def _bridge_health() -> dict[str, Any]:
    url = os.getenv("HERMES_GPT_BRIDGE_URL", "http://127.0.0.1:18890/health")
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
        parsed: Any
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body[:500]}
        return {
            "passed": True,
            "url": url,
            "elapsed_seconds": round(time.time() - started, 2),
            "response": parsed,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "passed": False,
            "url": url,
            "elapsed_seconds": round(time.time() - started, 2),
            "error": type(exc).__name__,
            "reason": str(exc),
        }


def _dry_run_matrix(base_dir: Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for mode, expected_count in MODES.items():
        data = _runner_json(
            query=f"这是一个{_mode_cn(mode)}任务。health dry-run.",
            mode=mode,
            action="dry-run",
            base_dir=str(base_dir / f"{mode.lower()}_dry"),
        )
        plan = data.get("plan", {})
        stages = plan.get("stages", [])
        results[mode] = {
            "passed": data.get("status") == "ok"
            and plan.get("stage_count") == expected_count
            and len(stages) == expected_count
            and plan.get("model_calls_made") is False,
            "status": data.get("status"),
            "stage_count": plan.get("stage_count"),
            "expected_stage_count": expected_count,
            "model_calls_made": plan.get("model_calls_made"),
        }
    return results


def _simulated_run_matrix(base_dir: Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for mode, expected_count in MODES.items():
        data = _runner_json(
            query=f"这是一个{_mode_cn(mode)}任务。health simulated-run.",
            mode=mode,
            action="simulated-run",
            base_dir=str(base_dir / f"{mode.lower()}_simulated"),
        )
        run = data.get("run", {})
        stages = run.get("stages", [])
        validation = data.get("validation", {})
        results[mode] = {
            "passed": data.get("status") == "ok"
            and data.get("pipeline_status") == "PIPELINE_COMPLETE"
            and validation.get("valid") is True
            and len(stages) == expected_count,
            "status": data.get("status"),
            "pipeline_status": data.get("pipeline_status"),
            "validation_valid": validation.get("valid"),
            "stage_count": len(stages),
            "expected_stage_count": expected_count,
            "artifact_dir": data.get("artifact_dir"),
        }
    return results


def _mode_cn(mode: str) -> str:
    if mode == "RESEARCH":
        return "研究"
    if mode == "DECISION":
        return "决策"
    return "研究决策"


def _all_passed(value: Any) -> bool:
    if isinstance(value, dict):
        if "passed" in value and isinstance(value["passed"], bool):
            own = value["passed"]
        else:
            own = True
        return own and all(_all_passed(item) for item in value.values() if isinstance(item, (dict, list)))
    if isinstance(value, list):
        return all(_all_passed(item) for item in value)
    return True


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="task_engine_health_", dir="/private/tmp"))
    checks: dict[str, Any] = {}

    checks["py_compile"] = _run([sys.executable, "-m", "py_compile", *KEY_FILES], timeout_s=60)
    checks["pytest"] = _run(
        [sys.executable, "-m", "pytest", "-q", "tests/tools/test_task_engine_contracts.py"],
        timeout_s=180,
    )
    checks["pytest"]["passed_count"] = _pytest_passed_count(
        "\n".join([checks["pytest"].get("stdout_tail", ""), checks["pytest"].get("stderr_tail", "")])
    )

    try:
        checks.update(_preflight_checks())
    except Exception as exc:
        checks["preflight_exception"] = {
            "passed": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }

    checks["gpt_bridge_health"] = _bridge_health()

    try:
        checks["dry_run_matrix"] = _dry_run_matrix(temp_root)
        checks["simulated_run_matrix"] = _simulated_run_matrix(temp_root)
    except Exception as exc:
        checks["matrix_exception"] = {
            "passed": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }

    summary = {
        "status": "PASS" if _all_passed(checks) else "FAIL",
        "generated_at_epoch": int(time.time()),
        "repo": str(ROOT),
        "no_full_run_executed": True,
        "temporary_artifact_root": str(temp_root),
        "checks": checks,
        "external_dependencies": {
            "agy": "requires logged-in Antigravity with Gemini 3.5 Flash (High) and Gemini 3.1 Pro (High)",
            "omlx": "requires OMLX_API_KEY from env or ~/.hermes/.env and visible R1 actual model",
            "gpt_bridge": "requires ChatGPT App Bridge worker health at http://127.0.0.1:18890/health",
            "ddgs": "not exercised by health script; covered by adapter tests and full/smoke runs",
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
