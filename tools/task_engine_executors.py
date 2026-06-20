"""Execution adapters for Hermes task engines.

The controller is allowed to orchestrate through this interface only. That
keeps model/tool invocation behind canonical stage specs and makes every stage
produce a StageRecord before validation can pass.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import http.client
import http.cookiejar
import hashlib
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Protocol

from tools.task_engine_contracts import (
    CANONICAL_STAGES,
    CONTROLLER_ACCEPTANCE,
    DDGS_MODEL,
    ENGINE_DECISION,
    ENGINE_RESEARCH,
    ENGINE_RESEARCH_DECISION,
    FINAL_CONTROLLER,
    GEMINI_HIGH,
    GEMINI_PRO_HIGH,
    GPT_OR_GEMINI_EXTERNAL,
    GEMMA431B,
    PIPELINE_BLOCKED,
    PIPELINE_COMPLETE,
    PIPELINE_INCOMPLETE,
    LLAMA70B,
    NEMOTRON120B,
    QWEN72B,
    R1_32B,
    StageRecord,
    StageSpec,
    make_stage_record,
    planned_outputs,
    render_final_markdown,
    validate_pipeline,
)

R1_ACTUAL_MODEL_DEFAULT = "DeepSeek-R1-Distill-Qwen-32B-MLX-8Bit"
QWEN72B_ACTUAL_MODEL_DEFAULT = "Qwen2.5-72B-Instruct-abliterated-mlx-4Bit"
NEMOTRON120B_ACTUAL_MODEL_DEFAULT = "NVIDIA-Nemotron-3-Super-120B-A12B-5bit"
LLAMA70B_ACTUAL_MODEL_DEFAULT = "Llama-3.3-70B-Instruct-abliterated-8bit-mlx"
GEMMA431B_ACTUAL_MODEL_DEFAULT = "gemma-4-31B-it-qat-8bit"
AGY_PREFLIGHT_REQUIRED_MODELS = (GEMINI_HIGH, GEMINI_PRO_HIGH)
CHATGPT_APP_BRIDGE_WRAPPER = Path("/Users/Shared/OpenClaw/chatgpt_app_bridge_http_cli.py")
_GPT_BRIDGE_LAST_EXECUTOR_MODEL = "GPT Bridge"
AGY_KEYCHAIN_FALSE_NEGATIVE = "AGY_KEYCHAIN_TIMEOUT_FALSE_NEGATIVE"
AGY_TIMEOUT_RESPONSE = "AGY_TIMEOUT_RESPONSE"
AGY_TIMEOUT_BLOCKED = "AGY_TIMEOUT_BLOCKED"
AGY_PRINTMODE_TIMEOUT_AFTER_AUTH_SUCCESS = "AGY_PRINTMODE_TIMEOUT_AFTER_AUTH_SUCCESS"
AGY_PRINTMODE_TIMEOUT_AUTH_UNCERTAIN = "AGY_PRINTMODE_TIMEOUT_AUTH_UNCERTAIN"
AGY_KEYCHAIN_RETRY_SLEEP_S = 2
AGY_STABLE_CWD_DEFAULT = Path("/Users/xqdwww/Workspace/AI_Core/hermes-agent")
PROFILE_EVIDENCE_GROUNDED = "evidence_grounded"
PROFILE_FORESIGHT_MECHANISM = "foresight_mechanism"
PROFILE_FUTURE_SCENARIO = "future_scenario"
PROFILE_IMPLEMENTATION_PLAN = "implementation_plan"


class TaskEngineExecutor(Protocol):
    def run_agy_preflight(self, timeout_s: int = 45) -> dict[str, Any]:
        ...

    def run_agy_gemini(self, stage: StageSpec, prompt: str, model: str, timeout_s: int | None = None) -> str:
        ...

    def run_ddgs(self, stage: StageSpec, queries: list[str]) -> list[dict[str, str]]:
        ...

    def run_codex_handoff(self, stage: StageSpec, inputs: dict[str, Any]) -> str:
        ...

    def run_omlx_model(self, stage: StageSpec, model: str, prompt: str) -> str:
        ...

    def run_controller_acceptance(self, stage: StageSpec, packet: dict[str, Any]) -> str:
        ...

    def run_external_calibration(self, stage: StageSpec, packet: dict[str, Any]) -> str:
        ...

    def run_final_controller_report(self, stage: StageSpec, packet: dict[str, Any]) -> str:
        ...

    def write_artifact(self, stage: StageSpec, content: Any, *, base_dir: str | Path) -> tuple[Path, dict[str, str]]:
        ...

    def make_stage_record(
        self,
        stage: StageSpec,
        *,
        base_dir: str | Path,
        artifact_path: str | Path,
        outputs: dict[str, str],
        created: bool,
        valid: bool,
        status: str,
        executor_model: str | None = None,
    ) -> StageRecord:
        ...


def run_agy_preflight(timeout_s: int = 45) -> dict[str, Any]:
    """Check AGY auth/model availability without creating pipeline artifacts."""
    agy_path = shutil.which("agy") or "/opt/homebrew/bin/agy"
    command = [agy_path, "models"]
    agy_cwd = _agy_subprocess_cwd()
    agy_env = _agy_subprocess_env()
    last_blocked: dict[str, Any] | None = None
    for attempt in range(2):
        started = time.time()
        stdout = ""
        stderr = ""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=agy_cwd,
                env=agy_env,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            elapsed = time.time() - started
            combined = "\n".join(part for part in (stdout, stderr) if part)
            models = _parse_agy_models(stdout)
            if result.returncode == 0:
                missing = [model for model in AGY_PREFLIGHT_REQUIRED_MODELS if model not in combined]
                if not missing:
                    return _agy_preflight_result(
                        "AGY_OK",
                        command=command,
                        elapsed=elapsed,
                        stdout=stdout,
                        stderr=stderr,
                        models=models,
                        agy_cwd=agy_cwd,
                        gemini_dir_absolute=_agy_gemini_dir_is_absolute(agy_env),
                    )
                return _agy_preflight_blocked(
                    "AGY_MODEL_LIST_MISSING_REQUIRED",
                    command=command,
                    elapsed=elapsed,
                    stdout=stdout,
                    stderr=stderr,
                    models=models,
                    missing_models=missing,
                    agy_cwd=agy_cwd,
                    gemini_dir_absolute=_agy_gemini_dir_is_absolute(agy_env),
                )
            reason = _classify_agy_preflight_block(stdout, stderr)
            last_blocked = _agy_preflight_blocked(
                reason,
                command=command,
                elapsed=elapsed,
                stdout=stdout,
                stderr=stderr,
                models=models,
                agy_cwd=agy_cwd,
                gemini_dir_absolute=_agy_gemini_dir_is_absolute(agy_env),
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.time() - started
            stdout = _decode_timeout_part(exc.stdout)
            stderr = _decode_timeout_part(exc.stderr)
            reason = _classify_agy_preflight_block(stdout, stderr)
            if reason != AGY_KEYCHAIN_FALSE_NEGATIVE:
                reason = "AGY_AUTH_TIMEOUT"
            last_blocked = _agy_preflight_blocked(
                reason,
                command=command,
                elapsed=elapsed,
                stdout=stdout,
                stderr=stderr,
                models=[],
                agy_cwd=agy_cwd,
                gemini_dir_absolute=_agy_gemini_dir_is_absolute(agy_env),
            )
        if last_blocked and last_blocked.get("blocked_reason") == AGY_KEYCHAIN_FALSE_NEGATIVE and attempt == 0:
            time.sleep(AGY_KEYCHAIN_RETRY_SLEEP_S)
            continue
        return last_blocked
    return last_blocked or _agy_preflight_blocked(
        "AGY_AUTH_REQUIRES_USER",
        command=command,
        elapsed=0,
        stdout="",
        stderr="",
        models=[],
        agy_cwd=agy_cwd,
        gemini_dir_absolute=_agy_gemini_dir_is_absolute(agy_env),
    )


def run_omlx_preflight(timeout_s: int = 15) -> dict[str, Any]:
    """Check OMLX auth/admin visibility without loading a model or writing artifacts."""
    details = _omlx_api_key_details(load_env_file=True)
    actual_r1 = resolve_r1_omlx_model_alias(R1_32B)
    base_url = _omlx_base_url()
    common = {
        "blocked_stage": "",
        "blocked_reason": "",
        "base_url": base_url,
        "configured_key_env": details["env_key"],
        "key_source": details["source"],
        "key_fingerprint": details["fingerprint"],
        "hermes_env_path": details["hermes_env_path"],
        "hermes_env_exists": details["hermes_env_exists"],
        "actual_r1_model": actual_r1,
        "model_visible": False,
    }
    api_key = details["value"]
    if not api_key:
        return {
            "status": "BLOCKED_STATUS",
            **common,
            "blocked_stage": "omlx_preflight",
            "blocked_reason": "OMLX_API_KEY_MISSING",
        }
    admin = _OmlxAdmin(base_url, api_key)
    started = time.time()
    if not admin.login():
        return {
            "status": "BLOCKED_STATUS",
            **common,
            "blocked_stage": "omlx_preflight",
            "blocked_reason": "OMLX_AUTH_BLOCKED",
            "elapsed_seconds": round(time.time() - started, 2),
        }
    try:
        models = admin.get_models()
    except Exception:
        models = []
    model_ids = [str(item.get("id") or "") for item in models if isinstance(item, dict)]
    visible = actual_r1 in model_ids
    if not visible:
        return {
            "status": "BLOCKED_STATUS",
            **common,
            "blocked_stage": "omlx_preflight",
            "blocked_reason": "OMLX_MODEL_LIST_MISSING_R1",
            "elapsed_seconds": round(time.time() - started, 2),
            "model_count": len(model_ids),
        }
    return {
        "status": "OMLX_OK",
        **common,
        "elapsed_seconds": round(time.time() - started, 2),
        "model_visible": True,
        "model_count": len(model_ids),
    }


class LocalTaskEngineExecutor:
    """Local adapter for real AGY/DDGS calls and deterministic artifact writes."""

    def __init__(self, *, agy_log_dir: str | Path | None = None):
        self.agy_log_dir = Path(agy_log_dir or os.getenv("HERMES_AGY_LOG_DIR", "work/agy_logs"))
        self.last_executor_models: dict[str, str] = {}
        self.last_omlx_diagnostics: dict[str, dict[str, Any]] = {}
        self._agy_preflight_warmed = False

    def run_agy_preflight(self, timeout_s: int = 45) -> dict[str, Any]:
        result = run_agy_preflight(timeout_s=timeout_s)
        if result.get("status") == "AGY_OK":
            self._agy_preflight_warmed = True
        return result

    def _ensure_agy_preflight_warmed(self, stage: StageSpec) -> None:
        if self._agy_preflight_warmed:
            return
        result = self.run_agy_preflight()
        if result.get("status") == "AGY_OK":
            self._agy_preflight_warmed = True
            return
        raise RuntimeError(
            f"{stage.stage_name}: AGY_PREFLIGHT_BLOCKED\n"
            f"blocked_reason={result.get('blocked_reason') or result.get('status')}\n"
            f"command={json.dumps(result.get('command') or [], ensure_ascii=False)}\n"
            f"stdout_tail={json.dumps(str(result.get('stdout_tail') or '')[-1000:], ensure_ascii=False)}\n"
            f"stderr_tail={json.dumps(str(result.get('stderr_tail') or '')[-1000:], ensure_ascii=False)}"
        )

    def run_agy_gemini(self, stage: StageSpec, prompt: str, model: str, timeout_s: int | None = None) -> str:
        if stage.model not in {GEMINI_HIGH, GEMINI_PRO_HIGH} or model != stage.model:
            raise RuntimeError(f"{stage.stage_name}: Gemini model binding mismatch")
        agy_path = shutil.which("agy") or "/opt/homebrew/bin/agy"
        if not os.path.exists(agy_path):
            raise RuntimeError(f"{stage.stage_name}: agy not found at {agy_path}")
        actual_model = resolve_agy_model_alias(model)
        self._ensure_agy_preflight_warmed(stage)
        self.last_executor_models[stage.stage_name] = actual_model
        timeout_s = timeout_s or _agy_timeout_for_stage(stage)
        agy_cwd = _agy_subprocess_cwd()
        agy_env = _agy_subprocess_env()
        last_error = ""
        for attempt in range(2):
            log_file = Path(f"/private/tmp/agy-{uuid.uuid4().hex[:8]}.log")
            command = [
                agy_path,
                "--log-file",
                str(log_file),
                "--model",
                actual_model,
                "-p",
                prompt,
                "--print-timeout",
                f"{timeout_s}s",
            ]
            started = time.time()
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s + 30,
                    cwd=agy_cwd,
                    env=agy_env,
                )
                elapsed = time.time() - started
                stdout = result.stdout or ""
                stderr = result.stderr or ""
                log_text = _read_text(log_file)
                combined = "\n".join(part for part in (stdout, stderr, log_text) if part)
                if _agy_model_alias_failed(combined, actual_model):
                    last_error = _format_agy_failure(
                        stage=stage,
                        command=command,
                        canonical_model=model,
                        actual_model=actual_model,
                        log_file=log_file,
                        stdout=stdout,
                        stderr=stderr,
                        log_text=log_text,
                        elapsed=elapsed,
                        agy_cwd=agy_cwd,
                        reason="AGY_MODEL_ALIAS_BLOCKED",
                    )
                    break
                timeout_response = _agy_timeout_response(combined)
                if timeout_response:
                    timeout_reason = _agy_timeout_blocker_reason(combined, actual_model, attempt=attempt)
                    last_error = _format_agy_failure(
                        stage=stage,
                        command=command,
                        canonical_model=model,
                        actual_model=actual_model,
                        log_file=log_file,
                        stdout=stdout,
                        stderr=stderr,
                        log_text=log_text,
                        elapsed=elapsed,
                        agy_cwd=agy_cwd,
                        reason=timeout_reason,
                    )
                    if attempt == 0:
                        time.sleep(AGY_KEYCHAIN_RETRY_SLEEP_S)
                        continue
                    break
                keychain_false_negative = _agy_keychain_false_negative(combined)
                auth_negative = _agy_auth_negative(combined)
                if result.returncode != 0:
                    last_error = _format_agy_failure(
                        stage=stage,
                        command=command,
                        canonical_model=model,
                        actual_model=actual_model,
                        log_file=log_file,
                        stdout=stdout,
                        stderr=stderr,
                        log_text=log_text,
                        elapsed=elapsed,
                        agy_cwd=agy_cwd,
                        reason=(
                            AGY_KEYCHAIN_FALSE_NEGATIVE
                            if keychain_false_negative
                            else "AGY_AUTH_BLOCKED"
                            if auth_negative and attempt > 0
                            else "AGY_AUTH_REQUIRES_USER"
                            if auth_negative
                            else f"returncode={result.returncode}"
                        ),
                    )
                    if (keychain_false_negative or auth_negative) and attempt == 0:
                        time.sleep(AGY_KEYCHAIN_RETRY_SLEEP_S)
                        continue
                    break
                output = stdout.strip()
                if output:
                    return output
                last_error = _format_agy_failure(
                    stage=stage,
                    command=command,
                    canonical_model=model,
                    actual_model=actual_model,
                    log_file=log_file,
                    stdout=stdout,
                    stderr=stderr,
                    log_text=log_text,
                    elapsed=elapsed,
                    agy_cwd=agy_cwd,
                    reason="empty_stdout",
                )
                break
            except subprocess.TimeoutExpired as exc:
                elapsed = time.time() - started
                stdout = _decode_timeout_part(exc.stdout)
                stderr = _decode_timeout_part(exc.stderr)
                log_text = _read_text(log_file)
                combined = "\n".join(part for part in (stdout, stderr, log_text) if part)
                timeout_response = _agy_timeout_response(combined)
                keychain_false_negative = _agy_keychain_false_negative(combined)
                reason = (
                    _agy_timeout_blocker_reason(combined, actual_model, attempt=attempt)
                    if timeout_response
                    else AGY_KEYCHAIN_FALSE_NEGATIVE
                    if keychain_false_negative
                    else f"timeout_after={timeout_s + 30}s"
                )
                last_error = _format_agy_failure(
                    stage=stage,
                    command=command,
                    canonical_model=model,
                    actual_model=actual_model,
                    log_file=log_file,
                    stdout=stdout,
                    stderr=stderr,
                    log_text=log_text,
                    elapsed=elapsed,
                    agy_cwd=agy_cwd,
                    reason=reason,
                )
                if (timeout_response or keychain_false_negative) and attempt == 0:
                    time.sleep(AGY_KEYCHAIN_RETRY_SLEEP_S)
                    continue
                break
        raise RuntimeError(last_error or f"{stage.stage_name}: agy failed")

    def run_ddgs(self, stage: StageSpec, queries: list[str]) -> list[dict[str, str]]:
        if stage.model != DDGS_MODEL:
            raise RuntimeError(f"{stage.stage_name}: DDGS model binding mismatch")

        hits: list[dict[str, str]] = []
        errors: list[str] = []
        backends = _ddgs_backend_list()
        timeout_s = _ddgs_timeout_s()
        retries = _ddgs_retries()
        for query in queries[:5]:
            for backend in backends:
                for attempt in range(1, retries + 2):
                    try:
                        results = _ddgs_search_once(query, backend=backend, timeout_s=timeout_s, max_results=5)
                    except Exception as exc:
                        message = f"{backend}:{type(exc).__name__}:{exc}"
                        errors.append(message)
                        if attempt <= retries and _is_transient_ddgs_error(exc):
                            time.sleep(0.2)
                            continue
                        break
                    if not results:
                        errors.append(f"{backend}:empty")
                        break
                    for hit in results:
                        normalized = _normalize_ddgs_hit(query, hit)
                        if normalized["url"]:
                            hits.append(normalized)
                    break
                if hits:
                    break
            time.sleep(0.2)
        if not hits:
            raise RuntimeError(
                f"{stage.stage_name}: DDGS returned no fresh hits; "
                f"backends={','.join(backends)}; errors={'; '.join(errors[-8:])}"
            )
        return hits

    def run_codex_handoff(self, stage: StageSpec, inputs: dict[str, Any]) -> str:
        required = ("source_candidates.json", "ddgs_gap_sources.json")
        missing = [name for name in required if not inputs.get(name)]
        if missing:
            raise RuntimeError(f"{stage.stage_name}: missing handoff inputs: {', '.join(missing)}")
        return json.dumps(
            {
                "handoff_protocol": "Hermes-Codex evidence organizer smoke",
                "inputs": {name: inputs[name] for name in required},
                "outputs": ["sources.csv", "evidence.csv", "claims.md", "gaps.md"],
            },
            ensure_ascii=False,
            indent=2,
        )

    def run_omlx_model(self, stage: StageSpec, model: str, prompt: str) -> str:
        if stage.stage_name in {"L3_r1_synthesis", "convergence_report"}:
            if stage.model != R1_32B or model != R1_32B:
                raise RuntimeError(f"{stage.stage_name}: R1 model binding mismatch")
            actual_model = resolve_r1_omlx_model_alias(model)
            empty_message = f"{stage.stage_name}: OMLX R1-32B returned empty content"
        elif stage.stage_name == "structure_mapper":
            if stage.model != QWEN72B or model != QWEN72B:
                raise RuntimeError(f"{stage.stage_name}: Qwen72B model binding mismatch")
            actual_model = resolve_qwen72b_omlx_model_alias(model)
            empty_message = f"{stage.stage_name}: OMLX Qwen72B returned empty content"
        elif stage.stage_name == "evidence_judge":
            if stage.model != NEMOTRON120B or model != NEMOTRON120B:
                raise RuntimeError(f"{stage.stage_name}: Nemotron-120B model binding mismatch")
            actual_model = resolve_nemotron120b_omlx_model_alias(model)
            empty_message = f"{stage.stage_name}: OMLX Nemotron-120B returned empty content"
        elif stage.stage_name == "premise_auditor":
            if stage.model != LLAMA70B or model != LLAMA70B:
                raise RuntimeError(f"{stage.stage_name}: Llama70B model binding mismatch")
            actual_model = resolve_llama70b_omlx_model_alias(model)
            empty_message = f"{stage.stage_name}: OMLX Llama70B returned empty content"
        elif stage.stage_name in {"alternative_generator", "insight_harvester"}:
            if stage.model != GEMMA431B or model != GEMMA431B:
                raise RuntimeError(f"{stage.stage_name}: Gemma-4-31B model binding mismatch")
            actual_model = resolve_gemma431b_omlx_model_alias(model)
            empty_message = f"{stage.stage_name}: OMLX Gemma-4-31B returned empty content"
        else:
            raise RuntimeError(f"{stage.stage_name}: OMLX stage is not wired in this smoke layer")
        self.last_executor_models[stage.stage_name] = actual_model
        api_key = _omlx_api_key()
        if not api_key:
            raise RuntimeError("OMLX_AUTH_BLOCKED: missing OMLX_API_KEY in environment or ~/.hermes/.env")
        admin = _OmlxAdmin(_omlx_base_url(), api_key)
        if not admin.login():
            raise RuntimeError("OMLX_AUTH_BLOCKED: admin login failed using OMLX_API_KEY from env/config")
        request_context: dict[str, Any] | None = None
        try:
            loaded_before_unload = _loaded_omlx_model_ids(admin)
            admin.unload_all()
            loaded_after_unload = _loaded_omlx_model_ids(admin)
            load_result = admin.load_model(actual_model)
            if load_result.get("error") and _is_omlx_memory_guard_error(load_result):
                admin.unload_all()
                time.sleep(5)
                loaded_after_unload = _loaded_omlx_model_ids(admin)
                load_result = admin.load_model(actual_model)
            if load_result.get("error"):
                raise RuntimeError(f"{stage.stage_name}: failed to load OMLX actual model: {_safe_omlx_error(load_result)}")
            loaded_after_load = _loaded_omlx_model_ids(admin)
            request_context = _omlx_request_diagnostic_context(
                stage,
                prompt,
                actual_model,
                loaded_models_before_unload=loaded_before_unload,
                loaded_models_after_unload=loaded_after_unload,
                loaded_models_after_load=loaded_after_load,
                retry_attempt="first",
            )
            try:
                data = _run_omlx_chat_with_retry(stage, actual_model, prompt, api_key=api_key)
            except RuntimeError as exc:
                if stage.stage_name == "evidence_judge" and _is_omlx_prefill_memory_text(str(exc)):
                    diagnostic_context = dict(request_context or {})
                    diagnostic_context["retry_attempt"] = "final"
                    self.last_omlx_diagnostics[stage.stage_name] = _omlx_prefill_memory_exception_diagnostic(
                        stage, actual_model, exc, attempt="final", request_context=diagnostic_context
                    )
                    raise RuntimeError(
                        f"{stage.stage_name}: OMLX_PREFILL_MEMORY_GUARD_BLOCKED: Nemotron-120B prefill memory guard rejected request"
                    ) from exc
                raise
            content = _extract_chat_content(data)
            if not content.strip() and stage.stage_name == "evidence_judge":
                self.last_omlx_diagnostics[stage.stage_name] = _omlx_empty_content_diagnostic(
                    stage, actual_model, data, attempt="first", request_context=request_context
                )
                if _is_omlx_prefill_memory_diagnostic(self.last_omlx_diagnostics[stage.stage_name]):
                    request_context = dict(request_context or {})
                    request_context["retry_attempt"] = "final"
                admin.unload_all()
                if request_context is not None:
                    request_context["loaded_models_after_unload"] = _loaded_omlx_model_ids(admin)
                load_result = admin.load_model(actual_model)
                if load_result.get("error"):
                    raise RuntimeError(f"{stage.stage_name}: failed to reload OMLX actual model after empty content: {_safe_omlx_error(load_result)}")
                if request_context is not None:
                    request_context["loaded_models_after_load"] = _loaded_omlx_model_ids(admin)
                try:
                    data = _run_omlx_chat_with_retry(stage, actual_model, prompt, api_key=api_key)
                except RuntimeError as exc:
                    if _is_omlx_prefill_memory_text(str(exc)):
                        diagnostic_context = dict(request_context or {})
                        diagnostic_context["retry_attempt"] = "final"
                        self.last_omlx_diagnostics[stage.stage_name] = _omlx_prefill_memory_exception_diagnostic(
                            stage, actual_model, exc, attempt="final", request_context=diagnostic_context
                        )
                        raise RuntimeError(
                            f"{stage.stage_name}: OMLX_PREFILL_MEMORY_GUARD_BLOCKED: Nemotron-120B prefill memory guard rejected request"
                        ) from exc
                    raise
                content = _extract_chat_content(data)
            if not content.strip():
                self.last_omlx_diagnostics[stage.stage_name] = _omlx_empty_content_diagnostic(
                    stage, actual_model, data, attempt="final", request_context=request_context
                )
                if stage.stage_name == "evidence_judge":
                    if _is_omlx_prefill_memory_diagnostic(self.last_omlx_diagnostics[stage.stage_name]):
                        raise RuntimeError(
                            f"{stage.stage_name}: OMLX_PREFILL_MEMORY_GUARD_BLOCKED: Nemotron-120B prefill memory guard rejected request"
                        )
                    raise RuntimeError(f"{stage.stage_name}: OMLX_EMPTY_CONTENT_BLOCKED: Nemotron-120B returned empty content")
                raise RuntimeError(empty_message)
            return content
        finally:
            admin.unload_model(actual_model)

    def run_external_calibration(self, stage: StageSpec, packet: dict[str, Any]) -> str:
        if stage.stage_name != "external_calibration" or stage.model != GPT_OR_GEMINI_EXTERNAL:
            raise RuntimeError(f"{stage.stage_name}: external calibration binding mismatch")
        prompt = str(packet.get("prompt") or "")
        if not prompt.strip():
            raise RuntimeError("external_calibration: missing calibration prompt")
        base_dir = packet.get("base_dir")

        fallback_reasons: list[str] = []
        try:
            content = _run_gpt_bridge_calibration(prompt)
            executor_model = _gpt_bridge_executor_model()
            quality_error = _external_calibration_quality_error(
                _external_calibration_with_metadata(content, executor_model=executor_model, fallback_reasons=fallback_reasons)
            ) if content.strip() else "external_calibration_empty_output"
            if not quality_error:
                self.last_executor_models[stage.stage_name] = executor_model
                return _external_calibration_with_metadata(
                    content,
                    executor_model=self.last_executor_models[stage.stage_name],
                    fallback_reasons=fallback_reasons,
                )
            _write_external_calibration_invalid(
                stage,
                base_dir=base_dir,
                content=content,
                executor_model=executor_model,
                fallback_used=False,
                error_summary=quality_error,
                attempt="gpt_bridge_first",
            )
            fallback_reasons.append(f"GPT_BRIDGE_INVALID_FIRST:{quality_error}")
            time.sleep(_gpt_bridge_header_retry_wait_s())
            retry_content = _run_gpt_bridge_calibration(prompt)
            retry_executor_model = _gpt_bridge_executor_model()
            retry_quality_error = _external_calibration_quality_error(
                _external_calibration_with_metadata(
                    retry_content,
                    executor_model=retry_executor_model,
                    fallback_reasons=fallback_reasons,
                )
            ) if retry_content.strip() else "external_calibration_empty_output"
            if not retry_quality_error:
                self.last_executor_models[stage.stage_name] = retry_executor_model
                fallback_reasons.append("GPT_BRIDGE_TARGETED_RETRY_USED")
                return _external_calibration_with_metadata(
                    retry_content,
                    executor_model=self.last_executor_models[stage.stage_name],
                    fallback_reasons=fallback_reasons,
                )
            _write_external_calibration_invalid(
                stage,
                base_dir=base_dir,
                content=retry_content,
                executor_model=retry_executor_model,
                fallback_used=False,
                error_summary=retry_quality_error,
                attempt="gpt_bridge_retry",
            )
            fallback_reasons.append(f"GPT_BRIDGE_INVALID_RETRY:{retry_quality_error}")
        except Exception as exc:
            fallback_reasons.append(f"GPT_BRIDGE_UNAVAILABLE:{_redact_secret_text(str(exc))}")

        gemini_stage = StageSpec(stage.stage_name, GEMINI_PRO_HIGH, GEMINI_PRO_HIGH, stage.required_outputs)
        try:
            content = self.run_agy_gemini(gemini_stage, prompt, GEMINI_PRO_HIGH)
        except Exception as exc:
            raise RuntimeError(
                "external_calibration: GPT Bridge and Gemini/agy unavailable; "
                f"fallback_reasons={json.dumps(fallback_reasons, ensure_ascii=False)}; "
                f"gemini_error={_redact_secret_text(str(exc))}"
            ) from exc
        self.last_executor_models[stage.stage_name] = getattr(self, "last_executor_models", {}).get(stage.stage_name, GEMINI_PRO_HIGH)
        quality_error = _external_calibration_quality_error(
            _external_calibration_with_metadata(
                content,
                executor_model=self.last_executor_models[stage.stage_name],
                fallback_reasons=fallback_reasons,
            )
        )
        if quality_error:
            _write_external_calibration_invalid(
                stage,
                base_dir=base_dir,
                content=content,
                executor_model=self.last_executor_models[stage.stage_name],
                fallback_used=True,
                error_summary=quality_error,
                attempt="gemini_fallback",
            )
            raise RuntimeError(f"external_calibration: artifact_quality_error:{quality_error}")
        return _external_calibration_with_metadata(
            content,
            executor_model=self.last_executor_models[stage.stage_name],
            fallback_reasons=fallback_reasons,
        )

    def run_controller_acceptance(self, stage: StageSpec, packet: dict[str, Any]) -> str:
        if stage.stage_name != "L5_deepseek_acceptance" or stage.model != CONTROLLER_ACCEPTANCE:
            raise RuntimeError(f"{stage.stage_name}: controller acceptance binding mismatch")
        self.last_executor_models[stage.stage_name] = CONTROLLER_ACCEPTANCE
        checked = [
            "L1_gemini_search",
            "L2_ddgs_supplement",
            "L2_5_codex_evidence_organizer",
            "L3_r1_synthesis",
            "L4_gemini_audit",
        ]
        missing = list(packet.get("missing_or_invalid_artifacts") or [])
        profile_issues = _research_packet_profile_acceptance_issues(packet)
        missing.extend(profile_issues)
        profile_requirements = [str(item) for item in (packet.get("profile_acceptance_requirements") or [])]
        audit_summary = str(packet.get("audit_summary") or "L4 audit artifact present.")
        rejected = missing or _audit_text_rejects(str(packet.get("audit_text") or ""))
        verdict = "REJECTED" if rejected else "ACCEPTED"
        accepted = "false" if rejected else "true"
        ready = "false" if rejected else "true"
        lines = [
            "research_evidence_packet",
            f"verdict: {verdict}",
            f"accepted: {accepted}",
            "checked_stages: [" + ", ".join(checked) + "]",
            "research_packet_profile: [" + ", ".join(_normalize_profiles(packet.get("research_packet_profile"))) + "]",
            "profile_acceptance_requirements: [" + "; ".join(profile_requirements) + "]",
            "missing_or_invalid_artifacts: [" + ", ".join(missing) + "]",
            f"audit_summary: {audit_summary}",
            f"evidence_packet_ready_for_decision: {ready}",
            "",
        ]
        lines.extend(_compact_research_evidence_sections(packet, accepted=not rejected))
        lines.extend([
            "",
            "scope: acceptance gate only; no new research, no search, no synthesis, no user-facing advice or decision output.",
        ])
        return "\n".join(lines)

    def run_final_controller_report(self, stage: StageSpec, packet: dict[str, Any]) -> str:
        if stage.stage_name != "final_controller_report" or stage.model != FINAL_CONTROLLER:
            raise RuntimeError(f"{stage.stage_name}: final controller binding mismatch")
        self.last_executor_models[stage.stage_name] = os.getenv("HERMES_FINAL_CONTROLLER_MODEL", "Hermes Controller").strip() or "Hermes Controller"
        content = _final_controller_report_from_packet(packet)
        try:
            _assert_final_controller_packet_quality(packet, content)
        except RuntimeError as exc:
            _write_final_controller_invalid(
                stage,
                base_dir=packet.get("base_dir"),
                content=content,
                executor_model=self.last_executor_models[stage.stage_name],
                error_summary=str(exc),
            )
            raise
        return content

    def write_artifact(self, stage: StageSpec, content: Any, *, base_dir: str | Path) -> tuple[Path, dict[str, str]]:
        outputs = planned_outputs(stage, base_dir)
        stage_dir = Path(base_dir) / stage.stage_name
        stage_dir.mkdir(parents=True, exist_ok=True)
        text = _stringify_artifact(content)
        _assert_artifact_quality(stage, text)
        if stage.stage_name == "L2_5_codex_evidence_organizer":
            for path in outputs.values():
                Path(path).write_text(text, encoding="utf-8")
            return stage_dir, outputs
        artifact_path = _primary_output_path(stage, outputs, stage_dir)
        artifact_path.write_text(text, encoding="utf-8")
        return artifact_path, outputs

    def make_stage_record(
        self,
        stage: StageSpec,
        *,
        base_dir: str | Path,
        artifact_path: str | Path,
        outputs: dict[str, str],
        created: bool,
        valid: bool,
        status: str,
        executor_model: str | None = None,
    ) -> StageRecord:
        return make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=created,
            valid=valid,
            status=status,
            executor_model=executor_model or self.last_executor_models.get(stage.stage_name, stage.model),
        )


def run_simulated_pipeline(mode: str, *, base_dir: str | Path) -> dict[str, Any]:
    """Write fake artifacts for every canonical stage, then validate/render."""
    executor = LocalTaskEngineExecutor()
    stages: list[dict[str, Any]] = []
    for stage in CANONICAL_STAGES[mode]:
        content = _simulated_content(stage)
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="simulated",
            executor_model=stage.model,
        )
        stages.append(record.__dict__)
    run = {"mode": mode, "execution_mode": "simulated-run", "stages": stages}
    validation = validate_pipeline(mode, run, base_dir=base_dir)
    markdown = render_final_markdown(mode, run, validation, base_dir=base_dir)
    return {
        "status": "ok" if validation["valid"] else "blocked",
        "pipeline_status": validation["pipeline_status"],
        "run": run,
        "validation": validation,
        "markdown": markdown,
    }


def run_research_l1_l2_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run only RESEARCH L1/L2 with real adapters, then stop fail-closed."""
    executor = executor or LocalTaskEngineExecutor()
    stages: list[dict[str, Any]] = []
    research_stages = CANONICAL_STAGES[ENGINE_RESEARCH]
    for stage in research_stages[:2]:
        try:
            if stage.stage_name == "L1_gemini_search":
                content = executor.run_agy_gemini(
                    stage,
                    _gemini_search_prompt(query),
                    stage.model,
                )
            elif stage.stage_name == "L2_ddgs_supplement":
                content = executor.run_ddgs(stage, _ddgs_queries(query))
            else:
                raise RuntimeError(f"Unexpected smoke stage: {stage.stage_name}")
            artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
            record = executor.make_stage_record(
                stage,
                base_dir=base_dir,
                artifact_path=artifact_path,
                outputs=outputs,
                created=True,
                valid=True,
                status="real",
                executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
            )
            stages.append(record.__dict__)
        except Exception as exc:
            outputs = planned_outputs(stage, base_dir)
            artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
            record = make_stage_record(
                stage,
                base_dir=base_dir,
                artifact_path=artifact_path,
                outputs=outputs,
                created=False,
                valid=False,
                status="blocked",
                executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
            )
            item = record.__dict__
            item["error"] = str(exc)
            stages.append(item)
            return {
                "status": "blocked",
                "pipeline_status": PIPELINE_BLOCKED,
                "blocked_stage": stage.stage_name,
                "run": {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l2", "stages": stages},
                "message": "Smoke test stopped fail-closed before final report.",
            }

    run = {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l2", "stages": stages}
    validation = validate_pipeline(ENGINE_RESEARCH, run, base_dir=base_dir)
    return {
        "status": "ok",
        "pipeline_status": PIPELINE_INCOMPLETE,
        "full_pipeline_validation": validation,
        "run": run,
        "message": "L1/L2 smoke completed. Full RESEARCH pipeline remains incomplete by design.",
    }


def run_research_l2_5_codex_handoff_smoke(
    prior_run: dict[str, Any],
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke the L2.5 handoff file protocol after real L1/L2 records exist."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    by_name = {stage.get("stage_name"): stage for stage in stages if isinstance(stage, dict)}
    l1 = by_name.get("L1_gemini_search")
    l2 = by_name.get("L2_ddgs_supplement")
    if not l1 or not l2:
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": "L2_5_codex_evidence_organizer",
            "message": "Codex handoff smoke requires completed L1 and L2 records.",
        }
    if l1.get("valid_for_pipeline") is not True or l2.get("valid_for_pipeline") is not True:
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": "L2_5_codex_evidence_organizer",
            "message": "Codex handoff smoke requires L1/L2 valid_for_pipeline=true.",
        }

    stage = CANONICAL_STAGES[ENGINE_RESEARCH][2]
    inputs = {
        "source_candidates.json": l1.get("artifact_path"),
        "ddgs_gap_sources.json": l2.get("artifact_path"),
    }
    try:
        content = executor.run_codex_handoff(stage, inputs)
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="handoff-smoke",
            executor_model=stage.model,
        )
        stages.append(record.__dict__)
        run = {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l2-plus-l2_5", "stages": stages}
        validation = validate_pipeline(ENGINE_RESEARCH, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "L2.5 Codex handoff file protocol smoke completed. Full RESEARCH pipeline remains incomplete by design.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            outputs=outputs,
            artifact_path=Path(base_dir) / stage.stage_name,
            created=False,
            valid=False,
            status="blocked",
            executor_model=stage.model,
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l2-plus-l2_5", "stages": stages},
            "message": "Codex handoff smoke stopped fail-closed.",
        }


def run_research_l3_synthesis_smoke(
    prior_run: dict[str, Any],
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
    query: str = "",
) -> dict[str, Any]:
    """Smoke L3 R1 synthesis from fresh L1/L2/L2.5 artifacts, then stop."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH][3]
    try:
        _require_fresh_prior_for_l3(stages, base_dir=base_dir)
        prompt = _r1_synthesis_prompt_from_artifacts(stages, base_dir=base_dir, query=query)
        content = executor.run_omlx_model(stage, stage.model, prompt)
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l3", "stages": stages}
        validation = validate_pipeline(ENGINE_RESEARCH, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "L3 R1 synthesis smoke completed. Full RESEARCH pipeline remains incomplete by design.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l3", "stages": stages},
            "message": "L3 R1 synthesis smoke stopped fail-closed before L4.",
        }


def run_research_l1_l3_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run real L1/L2, L2.5 handoff, then real L3 R1 synthesis and stop."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l2 = run_research_l1_l2_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l2.get("status") != "ok":
        return l1_l2
    l2_5 = run_research_l2_5_codex_handoff_smoke(l1_l2["run"], base_dir=base_dir, executor=executor)
    if l2_5.get("status") != "ok":
        return l2_5
    return run_research_l3_synthesis_smoke(l2_5["run"], base_dir=base_dir, executor=executor, query=query)


def run_research_l4_gemini_audit_smoke(
    prior_run: dict[str, Any],
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
    query: str = "",
) -> dict[str, Any]:
    """Smoke L4 Gemini audit from fresh L1/L2/L2.5/L3 artifacts, then stop."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH][4]
    try:
        _require_fresh_prior_for_l4(stages, base_dir=base_dir)
        prompt = _gemini_audit_prompt_from_artifacts(stages, base_dir=base_dir, query=query)
        content = executor.run_agy_gemini(stage, prompt, stage.model)
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l4", "stages": stages}
        validation = validate_pipeline(ENGINE_RESEARCH, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "L4 Gemini audit smoke completed. Full RESEARCH pipeline remains incomplete by design.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l4", "stages": stages},
            "message": "L4 Gemini audit smoke stopped fail-closed before L5.",
        }


def run_research_l5_acceptance_smoke(
    prior_run: dict[str, Any],
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
    query: str = "",
) -> dict[str, Any]:
    """Smoke L5 controller acceptance from fresh L1-L4 artifacts, then stop."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH][5]
    try:
        _require_fresh_prior_for_l5(stages, base_dir=base_dir)
        packet = _research_acceptance_packet_from_artifacts(stages, base_dir=base_dir, query=query)
        content = executor.run_controller_acceptance(stage, packet)
        accepted = _l5_acceptance_text_is_accepted(content)
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=accepted,
            status="accepted" if accepted else "rejected",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l5", "stages": stages}
        validation = validate_pipeline(ENGINE_RESEARCH, run, base_dir=base_dir)
        if not accepted:
            return {
                "status": "blocked",
                "pipeline_status": PIPELINE_BLOCKED,
                "blocked_stage": stage.stage_name,
                "full_pipeline_validation": validation,
                "run": run,
                "message": "L5 acceptance rejected the research evidence packet. Decision phase was not entered.",
            }
        return {
            "status": "ok" if validation["valid"] else "blocked",
            "pipeline_status": validation["pipeline_status"],
            "full_pipeline_validation": validation,
            "run": run,
            "message": "L5 acceptance completed. RESEARCH pipeline is complete; Decision phase was not entered.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l5", "stages": stages},
            "message": "L5 acceptance smoke stopped fail-closed before Decision.",
        }


def run_research_l1_l4_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run real L1/L2, L2.5, L3, then real L4 Gemini audit and stop."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l3 = run_research_l1_l3_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l3.get("status") != "ok":
        return l1_l3
    return run_research_l4_gemini_audit_smoke(l1_l3["run"], base_dir=base_dir, executor=executor, query=query)


def run_research_l1_l5_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run real L1-L4, then L5 acceptance and stop before Decision."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l4 = run_research_l1_l4_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l4.get("status") != "ok":
        return l1_l4
    return run_research_l5_acceptance_smoke(l1_l4["run"], base_dir=base_dir, executor=executor, query=query)


def run_research_decision_intelligence_smoke(
    prior_run: dict[str, Any],
    *,
    query: str,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke Decision stage 7 intelligence_layer after accepted RESEARCH packet."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][6]
    try:
        _require_accepted_research_packet_for_intelligence(stages, base_dir=base_dir)
        prompt = _intelligence_layer_prompt_from_research_packet(stages, query=query, base_dir=base_dir)
        content = executor.run_agy_gemini(stage, prompt, stage.model)
        leaked = _intelligence_output_forbidden_tokens(content)
        if leaked:
            raise RuntimeError(f"intelligence_layer: forbidden final-output tokens: {', '.join(leaked)}")
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {
            "mode": ENGINE_RESEARCH_DECISION,
            "execution_mode": "real-smoke-research-decision-intelligence",
            "stages": stages,
        }
        validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "Decision intelligence_layer smoke completed. Pipeline remains incomplete before Stage 8.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-intelligence",
                "stages": stages,
            },
            "message": "Decision intelligence_layer smoke stopped fail-closed before Stage 8.",
        }


def run_research_decision_supplementary_search_smoke(
    prior_run: dict[str, Any],
    *,
    query: str,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke Decision stage 8 supplementary_search after intelligence_layer."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][7]
    try:
        _require_fresh_prior_for_supplementary_search(stages, base_dir=base_dir)
        hits = executor.run_ddgs(stage, _supplementary_search_queries(query))
        content = _supplementary_search_report(hits, stages=stages, query=query, base_dir=base_dir)
        leaked = _intelligence_output_forbidden_tokens(content)
        if leaked:
            raise RuntimeError(f"supplementary_search: forbidden final-output tokens: {', '.join(leaked)}")
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=stage.model,
        )
        stages.append(record.__dict__)
        run = {
            "mode": ENGINE_RESEARCH_DECISION,
            "execution_mode": "real-smoke-research-decision-search",
            "stages": stages,
        }
        validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "Decision supplementary_search smoke completed. Pipeline remains incomplete before Stage 9.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=stage.model,
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-search",
                "stages": stages,
            },
            "message": "Decision supplementary_search smoke stopped fail-closed before Stage 9.",
        }


def run_research_decision_structure_mapper_smoke(
    prior_run: dict[str, Any],
    *,
    query: str,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke Decision stage 9 structure_mapper after supplementary_search."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][8]
    try:
        _require_fresh_prior_for_structure_mapper(stages, base_dir=base_dir)
        prompt = _structure_mapper_prompt_from_artifacts(stages, query=query, base_dir=base_dir)
        content = executor.run_omlx_model(stage, stage.model, prompt)
        leaked = _structure_mapper_forbidden_tokens(content)
        if leaked:
            debug_path = _write_invalid_stage_debug(stage, content, base_dir=base_dir)
            raise RuntimeError(f"structure_mapper: forbidden later-stage/final tokens: {', '.join(leaked)}; debug_artifact={debug_path}")
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {
            "mode": ENGINE_RESEARCH_DECISION,
            "execution_mode": "real-smoke-research-decision-structure",
            "stages": stages,
        }
        validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "Decision structure_mapper smoke completed. Pipeline remains incomplete before evidence_judge.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-structure",
                "stages": stages,
            },
            "message": "Decision structure_mapper smoke stopped fail-closed before evidence_judge.",
        }


def run_research_decision_evidence_judge_smoke(
    prior_run: dict[str, Any],
    *,
    query: str,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke Decision stage 10 evidence_judge after structure_mapper."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][9]
    debug_content = ""
    try:
        _require_fresh_prior_for_evidence_judge(stages, base_dir=base_dir)
        prompt = _evidence_judge_prompt_from_artifacts(stages, query=query, base_dir=base_dir)
        content = executor.run_omlx_model(stage, stage.model, prompt)
        debug_content = content
        leaked = _evidence_judge_forbidden_tokens(content)
        if leaked:
            debug_path = _write_invalid_stage_debug(stage, content, base_dir=base_dir)
            raise RuntimeError(f"evidence_judge: forbidden later-stage/final tokens: {', '.join(leaked)}; debug_artifact={debug_path}")
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {
            "mode": ENGINE_RESEARCH_DECISION,
            "execution_mode": "real-smoke-research-decision-evidence",
            "stages": stages,
        }
        validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "Decision evidence_judge smoke completed. Pipeline remains incomplete before premise_auditor.",
        }
    except Exception as exc:
        diagnostic_path = _write_omlx_stage_diagnostic(stage, executor, base_dir=base_dir)
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc) + (f"; diagnostic_artifact={diagnostic_path}" if diagnostic_path else "")
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-evidence",
                "stages": stages,
            },
            "message": "Decision evidence_judge smoke stopped fail-closed before premise_auditor.",
        }


def run_research_decision_premise_auditor_smoke(
    prior_run: dict[str, Any],
    *,
    query: str,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke Decision stage 11 premise_auditor after evidence_judge."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][10]
    try:
        _require_fresh_prior_for_premise_auditor(stages, base_dir=base_dir)
        prompt = _premise_auditor_prompt_from_artifacts(stages, query=query, base_dir=base_dir)
        content = executor.run_omlx_model(stage, stage.model, prompt)
        leaked = _premise_auditor_forbidden_tokens(content)
        if leaked:
            debug_path = _write_invalid_stage_debug(stage, content, base_dir=base_dir)
            raise RuntimeError(f"premise_auditor: forbidden later-stage/final tokens: {', '.join(leaked)}; debug_artifact={debug_path}")
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {
            "mode": ENGINE_RESEARCH_DECISION,
            "execution_mode": "real-smoke-research-decision-premise",
            "stages": stages,
        }
        validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "Decision premise_auditor smoke completed. Pipeline remains incomplete before alternative_generator.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-premise",
                "stages": stages,
            },
            "message": "Decision premise_auditor smoke stopped fail-closed before alternative_generator.",
        }


def run_research_decision_alternative_generator_smoke(
    prior_run: dict[str, Any],
    *,
    query: str,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke Decision stage 12 alternative_generator after premise_auditor."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][11]
    try:
        _require_fresh_prior_for_alternative_generator(stages, base_dir=base_dir)
        prompt = _alternative_generator_prompt_from_artifacts(stages, query=query, base_dir=base_dir)
        content = executor.run_omlx_model(stage, stage.model, prompt)
        leaked = _alternative_generator_forbidden_tokens(content)
        if leaked:
            debug_path = _write_invalid_stage_debug(stage, content, base_dir=base_dir)
            raise RuntimeError(f"alternative_generator: forbidden later-stage/final tokens: {', '.join(leaked)}; debug_artifact={debug_path}")
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {
            "mode": ENGINE_RESEARCH_DECISION,
            "execution_mode": "real-smoke-research-decision-alternative",
            "stages": stages,
        }
        validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "Decision alternative_generator smoke completed. Pipeline remains incomplete before insight_harvester.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-alternative",
                "stages": stages,
            },
            "message": "Decision alternative_generator smoke stopped fail-closed before insight_harvester.",
        }


def run_research_decision_insight_harvester_smoke(
    prior_run: dict[str, Any],
    *,
    query: str,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke Decision stage 13 insight_harvester after alternative_generator."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][12]
    try:
        _require_fresh_prior_for_insight_harvester(stages, base_dir=base_dir)
        prompt = _insight_harvester_prompt_from_artifacts(stages, query=query, base_dir=base_dir)
        content = executor.run_omlx_model(stage, stage.model, prompt)
        leaked = _insight_harvester_forbidden_tokens(content)
        if leaked:
            debug_path = _write_invalid_stage_debug(stage, content, base_dir=base_dir)
            raise RuntimeError(f"insight_harvester: forbidden later-stage/final tokens: {', '.join(leaked)}; debug_artifact={debug_path}")
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        if stages and Path(str(stages[-1].get("artifact_path") or "")).resolve() == Path(artifact_path).resolve():
            raise RuntimeError("insight_harvester: artifact_path must be distinct from alternative_generator")
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {
            "mode": ENGINE_RESEARCH_DECISION,
            "execution_mode": "real-smoke-research-decision-insight",
            "stages": stages,
        }
        validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "Decision insight_harvester smoke completed. Pipeline remains incomplete before convergence_report.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-insight",
                "stages": stages,
            },
            "message": "Decision insight_harvester smoke stopped fail-closed before convergence_report.",
        }


def run_research_decision_convergence_smoke(
    prior_run: dict[str, Any],
    *,
    query: str,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke Decision stage 14 convergence_report after all divergence roles."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][13]
    try:
        _require_fresh_prior_for_convergence_report(stages, base_dir=base_dir)
        prompt = _convergence_report_prompt_from_artifacts(stages, query=query, base_dir=base_dir)
        content = executor.run_omlx_model(stage, stage.model, prompt)
        leaked = _convergence_report_forbidden_tokens(content)
        if leaked:
            raise RuntimeError(f"convergence_report: forbidden final/tool-chain tokens: {', '.join(leaked)}")
        profile_errors = _quality_profile_errors(content, _task_engine_profiles_from_query(query), stage_name="convergence_report")
        if profile_errors:
            raise RuntimeError(f"convergence_report: output_quality_profile_error:{', '.join(profile_errors)}")
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        l3_path = Path(str(stages[3].get("artifact_path") or "")).resolve()
        if Path(artifact_path).resolve() == l3_path:
            raise RuntimeError("convergence_report: artifact_path must be distinct from L3_r1_synthesis")
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {
            "mode": ENGINE_RESEARCH_DECISION,
            "execution_mode": "real-smoke-research-decision-convergence",
            "stages": stages,
        }
        validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "Decision convergence_report smoke completed. Pipeline remains incomplete before external_calibration.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-convergence",
                "stages": stages,
            },
            "message": "Decision convergence_report smoke stopped fail-closed before external_calibration.",
        }


def run_research_decision_external_calibration_smoke(
    prior_run: dict[str, Any],
    *,
    query: str,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke Decision stage 15 external_calibration after convergence_report."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][14]
    try:
        _require_fresh_prior_for_external_calibration(stages, base_dir=base_dir)
        prompt = _external_calibration_prompt_from_artifacts(stages, query=query, base_dir=base_dir)
        content = executor.run_external_calibration(stage, {"prompt": prompt, "base_dir": str(base_dir)})
        leaked = _external_calibration_forbidden_tokens(content)
        if leaked:
            raise RuntimeError(f"external_calibration: forbidden final-output tokens: {', '.join(leaked)}")
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {
            "mode": ENGINE_RESEARCH_DECISION,
            "execution_mode": "real-smoke-research-decision-calibration",
            "stages": stages,
        }
        validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=base_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_INCOMPLETE,
            "full_pipeline_validation": validation,
            "run": run,
            "message": "Decision external_calibration smoke completed. Pipeline remains incomplete before final_controller_report.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-calibration",
                "stages": stages,
            },
            "message": "Decision external_calibration smoke stopped fail-closed before final_controller_report.",
        }


def run_research_decision_final_controller_smoke(
    prior_run: dict[str, Any],
    *,
    query: str,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Smoke Decision stage 16 final_controller_report after external_calibration."""
    executor = executor or LocalTaskEngineExecutor()
    stages = list(prior_run.get("stages", []))
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][15]
    try:
        _require_fresh_prior_for_final_controller_report(stages, base_dir=base_dir)
        packet = _final_controller_packet_from_artifacts(stages, query=query, base_dir=base_dir)
        content = executor.run_final_controller_report(stage, packet)
        leaked = _final_controller_report_forbidden_tokens(content)
        if leaked:
            raise RuntimeError(f"final_controller_report: forbidden raw/tool-chain tokens: {', '.join(leaked)}")
        artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
        record = executor.make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="real",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        stages.append(record.__dict__)
        run = {
            "mode": ENGINE_RESEARCH_DECISION,
            "execution_mode": "real-smoke-research-decision-final",
            "stages": stages,
        }
        validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=base_dir)
        markdown = render_final_markdown(ENGINE_RESEARCH_DECISION, run, validation, base_dir=base_dir)
        return {
            "status": "ok" if validation.get("valid") else "blocked",
            "pipeline_status": validation["pipeline_status"],
            "full_pipeline_validation": validation,
            "run": run,
            "markdown": markdown,
            "message": "Decision final_controller_report smoke completed." if validation.get("valid") else "Decision final_controller_report smoke failed validation.",
        }
    except Exception as exc:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-final",
                "stages": stages,
            },
            "message": "Decision final_controller_report smoke stopped fail-closed.",
        }


def run_research_decision_l1_l7_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run RESEARCH L1-L5, then Decision intelligence_layer and stop."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l5 = run_research_l1_l5_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l5.get("status") != "ok":
        return l1_l5
    return run_research_decision_intelligence_smoke(
        l1_l5["run"],
        query=query,
        base_dir=base_dir,
        executor=executor,
    )


def run_research_decision_l1_l8_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run RESEARCH L1-L5, intelligence_layer, supplementary_search, then stop."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l7 = run_research_decision_l1_l7_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l7.get("status") != "ok":
        return l1_l7
    return run_research_decision_supplementary_search_smoke(
        l1_l7["run"],
        query=query,
        base_dir=base_dir,
        executor=executor,
    )


def run_research_decision_l1_l9_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run RESEARCH L1-L5, intelligence_layer, supplementary_search, structure_mapper, then stop."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l8 = run_research_decision_l1_l8_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l8.get("status") != "ok":
        return l1_l8
    return run_research_decision_structure_mapper_smoke(
        l1_l8["run"],
        query=query,
        base_dir=base_dir,
        executor=executor,
    )


def run_research_decision_l1_l10_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run RESEARCH L1-L5, Decision stages 7-10, then stop before premise_auditor."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l9 = run_research_decision_l1_l9_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l9.get("status") != "ok":
        return l1_l9
    return run_research_decision_evidence_judge_smoke(
        l1_l9["run"],
        query=query,
        base_dir=base_dir,
        executor=executor,
    )


def run_research_decision_l1_l11_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run RESEARCH L1-L5, Decision stages 7-11, then stop before alternative_generator."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l10 = run_research_decision_l1_l10_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l10.get("status") != "ok":
        return l1_l10
    return run_research_decision_premise_auditor_smoke(
        l1_l10["run"],
        query=query,
        base_dir=base_dir,
        executor=executor,
    )


def run_research_decision_l1_l12_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run RESEARCH L1-L5, Decision stages 7-12, then stop before insight_harvester."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l11 = run_research_decision_l1_l11_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l11.get("status") != "ok":
        return l1_l11
    return run_research_decision_alternative_generator_smoke(
        l1_l11["run"],
        query=query,
        base_dir=base_dir,
        executor=executor,
    )


def run_research_decision_l1_l13_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run RESEARCH L1-L5, Decision stages 7-13, then stop before convergence_report."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l12 = run_research_decision_l1_l12_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l12.get("status") != "ok":
        return l1_l12
    return run_research_decision_insight_harvester_smoke(
        l1_l12["run"],
        query=query,
        base_dir=base_dir,
        executor=executor,
    )


def run_research_decision_l1_l14_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run RESEARCH L1-L5, Decision stages 7-14, then stop before external_calibration."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l13 = run_research_decision_l1_l13_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l13.get("status") != "ok":
        return l1_l13
    return run_research_decision_convergence_smoke(
        l1_l13["run"],
        query=query,
        base_dir=base_dir,
        executor=executor,
    )


def run_research_decision_l1_l15_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run RESEARCH L1-L5, Decision stages 7-15, then stop before final_controller_report."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l14 = run_research_decision_l1_l14_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l14.get("status") != "ok":
        return l1_l14
    return run_research_decision_external_calibration_smoke(
        l1_l14["run"],
        query=query,
        base_dir=base_dir,
        executor=executor,
    )


def run_research_decision_l1_l16_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
) -> dict[str, Any]:
    """Run complete RESEARCH_DECISION L1-L16."""
    executor = executor or LocalTaskEngineExecutor()
    l1_l15 = run_research_decision_l1_l15_smoke(query, base_dir=base_dir, executor=executor)
    if l1_l15.get("status") != "ok":
        return l1_l15
    return run_research_decision_final_controller_smoke(
        l1_l15["run"],
        query=query,
        base_dir=base_dir,
        executor=executor,
    )


def run_decision_final_smoke(
    query: str,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor | None = None,
    research_packet_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run complete DECISION D1-D10 without entering RESEARCH L1-L5."""
    executor = executor or LocalTaskEngineExecutor()
    stages: list[dict[str, Any]] = []
    specs = CANONICAL_STAGES[ENGINE_DECISION]

    def blocked(stage: StageSpec, exc: Exception) -> dict[str, Any]:
        outputs = planned_outputs(stage, base_dir)
        artifact_path = _primary_output_path(stage, outputs, Path(base_dir) / stage.stage_name)
        record = make_stage_record(
            stage,
            base_dir=base_dir,
            artifact_path=artifact_path,
            outputs=outputs,
            created=False,
            valid=False,
            status="blocked",
            executor_model=getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
        )
        item = record.__dict__
        item["error"] = str(exc)
        stages.append(item)
        return {
            "status": "blocked",
            "pipeline_status": PIPELINE_BLOCKED,
            "blocked_stage": stage.stage_name,
            "run": {"mode": ENGINE_DECISION, "execution_mode": "real-smoke-decision-final", "stages": stages},
            "message": "DECISION smoke stopped fail-closed.",
        }

    try:
        stage = specs[0]
        content = executor.run_agy_gemini(
            stage,
            _decision_intelligence_prompt(query, base_dir=base_dir, research_packet_path=research_packet_path),
            stage.model,
        )
        leaked = _intelligence_output_forbidden_tokens(content)
        if leaked:
            raise RuntimeError(f"intelligence_layer: forbidden final-output tokens: {', '.join(leaked)}")
        _append_real_stage(stages, stage, content, base_dir=base_dir, executor=executor, status="real")

        stage = specs[1]
        _require_decision_prior(stages, ["intelligence_layer"], base_dir=base_dir, consumer_stage=stage.stage_name)
        hits = executor.run_ddgs(stage, _supplementary_search_queries(query))
        content = _decision_supplementary_search_report(
            hits,
            stages=stages,
            query=query,
            base_dir=base_dir,
            research_packet_path=research_packet_path,
        )
        leaked = _intelligence_output_forbidden_tokens(content)
        if leaked:
            raise RuntimeError(f"supplementary_search: forbidden final-output tokens: {', '.join(leaked)}")
        _append_real_stage(stages, stage, content, base_dir=base_dir, executor=executor, status="real", executor_model=stage.model)

        stage = specs[2]
        _require_decision_prior(stages, ["intelligence_layer", "supplementary_search"], base_dir=base_dir, consumer_stage=stage.stage_name)
        content = executor.run_omlx_model(stage, stage.model, _decision_stage_prompt(stage, stages, query=query, base_dir=base_dir, research_packet_path=research_packet_path))
        leaked = _structure_mapper_forbidden_tokens(content)
        if leaked:
            debug_path = _write_invalid_stage_debug(stage, content, base_dir=base_dir)
            raise RuntimeError(f"structure_mapper: forbidden later-stage/final tokens: {', '.join(leaked)}; debug_artifact={debug_path}")
        _append_real_stage(stages, stage, content, base_dir=base_dir, executor=executor, status="real")

        stage = specs[3]
        _require_decision_prior(stages, ["intelligence_layer", "supplementary_search", "structure_mapper"], base_dir=base_dir, consumer_stage=stage.stage_name)
        try:
            content = executor.run_omlx_model(stage, stage.model, _decision_stage_prompt(stage, stages, query=query, base_dir=base_dir, research_packet_path=research_packet_path))
        except Exception as exc:
            diagnostic_path = _write_omlx_stage_diagnostic(stage, executor, base_dir=base_dir)
            if diagnostic_path:
                raise RuntimeError(f"{exc}; diagnostic_artifact={diagnostic_path}") from exc
            raise
        leaked = _evidence_judge_forbidden_tokens(content)
        if leaked:
            debug_path = _write_invalid_stage_debug(stage, content, base_dir=base_dir)
            raise RuntimeError(f"evidence_judge: forbidden later-stage/final tokens: {', '.join(leaked)}; debug_artifact={debug_path}")
        _append_real_stage(stages, stage, content, base_dir=base_dir, executor=executor, status="real")

        stage = specs[4]
        _require_decision_prior(stages, ["intelligence_layer", "supplementary_search", "structure_mapper", "evidence_judge"], base_dir=base_dir, consumer_stage=stage.stage_name)
        content = executor.run_omlx_model(stage, stage.model, _decision_stage_prompt(stage, stages, query=query, base_dir=base_dir, research_packet_path=research_packet_path))
        leaked = _premise_auditor_forbidden_tokens(content)
        if leaked:
            debug_path = _write_invalid_stage_debug(stage, content, base_dir=base_dir)
            raise RuntimeError(f"premise_auditor: forbidden later-stage/final tokens: {', '.join(leaked)}; debug_artifact={debug_path}")
        _append_real_stage(stages, stage, content, base_dir=base_dir, executor=executor, status="real")

        stage = specs[5]
        _require_decision_prior(stages, ["intelligence_layer", "supplementary_search", "structure_mapper", "evidence_judge", "premise_auditor"], base_dir=base_dir, consumer_stage=stage.stage_name)
        content = executor.run_omlx_model(stage, stage.model, _decision_stage_prompt(stage, stages, query=query, base_dir=base_dir, research_packet_path=research_packet_path))
        leaked = _alternative_generator_forbidden_tokens(content)
        if leaked:
            debug_path = _write_invalid_stage_debug(stage, content, base_dir=base_dir)
            raise RuntimeError(f"alternative_generator: forbidden later-stage/final tokens: {', '.join(leaked)}; debug_artifact={debug_path}")
        _append_real_stage(stages, stage, content, base_dir=base_dir, executor=executor, status="real")

        stage = specs[6]
        _require_decision_prior(stages, ["intelligence_layer", "supplementary_search", "structure_mapper", "evidence_judge", "premise_auditor", "alternative_generator"], base_dir=base_dir, consumer_stage=stage.stage_name)
        content = executor.run_omlx_model(stage, stage.model, _decision_stage_prompt(stage, stages, query=query, base_dir=base_dir, research_packet_path=research_packet_path))
        leaked = _insight_harvester_forbidden_tokens(content)
        if leaked:
            debug_path = _write_invalid_stage_debug(stage, content, base_dir=base_dir)
            raise RuntimeError(f"insight_harvester: forbidden later-stage/final tokens: {', '.join(leaked)}; debug_artifact={debug_path}")
        _append_real_stage(stages, stage, content, base_dir=base_dir, executor=executor, status="real")

        stage = specs[7]
        _require_decision_prior(stages, [
            "intelligence_layer",
            "supplementary_search",
            "structure_mapper",
            "evidence_judge",
            "premise_auditor",
            "alternative_generator",
            "insight_harvester",
        ], base_dir=base_dir, consumer_stage=stage.stage_name)
        content = executor.run_omlx_model(stage, stage.model, _decision_stage_prompt(stage, stages, query=query, base_dir=base_dir, research_packet_path=research_packet_path))
        leaked = _convergence_report_forbidden_tokens(content)
        if leaked:
            raise RuntimeError(f"convergence_report: forbidden final/tool-chain tokens: {', '.join(leaked)}")
        profile_errors = _quality_profile_errors(content, _task_engine_profiles_from_query(query), stage_name="convergence_report")
        if profile_errors:
            raise RuntimeError(f"convergence_report: output_quality_profile_error:{', '.join(profile_errors)}")
        _append_real_stage(stages, stage, content, base_dir=base_dir, executor=executor, status="real")

        stage = specs[8]
        _require_decision_prior(stages, [
            "intelligence_layer",
            "supplementary_search",
            "structure_mapper",
            "evidence_judge",
            "premise_auditor",
            "alternative_generator",
            "insight_harvester",
            "convergence_report",
        ], base_dir=base_dir, consumer_stage=stage.stage_name)
        content = executor.run_external_calibration(
            stage,
            {
                "prompt": _decision_external_calibration_prompt(
                    stages,
                    query=query,
                    base_dir=base_dir,
                    research_packet_path=research_packet_path,
                ),
                "base_dir": str(base_dir),
            },
        )
        leaked = _external_calibration_forbidden_tokens(content)
        if leaked:
            raise RuntimeError(f"external_calibration: forbidden final-output tokens: {', '.join(leaked)}")
        _append_real_stage(stages, stage, content, base_dir=base_dir, executor=executor, status="real")

        stage = specs[9]
        _require_decision_prior(stages, [
            "intelligence_layer",
            "supplementary_search",
            "structure_mapper",
            "evidence_judge",
            "premise_auditor",
            "alternative_generator",
            "insight_harvester",
            "convergence_report",
            "external_calibration",
        ], base_dir=base_dir, consumer_stage=stage.stage_name)
        packet = _decision_final_controller_packet(stages, query=query, base_dir=base_dir, research_packet_path=research_packet_path)
        content = executor.run_final_controller_report(stage, packet)
        leaked = _final_controller_report_forbidden_tokens(content)
        if leaked:
            raise RuntimeError(f"final_controller_report: forbidden raw/tool-chain tokens: {', '.join(leaked)}")
        _append_real_stage(stages, stage, content, base_dir=base_dir, executor=executor, status="real")

        run = {"mode": ENGINE_DECISION, "execution_mode": "real-smoke-decision-final", "stages": stages}
        validation = validate_pipeline(ENGINE_DECISION, run, base_dir=base_dir)
        markdown = render_final_markdown(ENGINE_DECISION, run, validation, base_dir=base_dir)
        return {
            "status": "ok" if validation.get("valid") else "blocked",
            "pipeline_status": validation["pipeline_status"],
            "full_pipeline_validation": validation,
            "run": run,
            "markdown": markdown,
            "message": "DECISION final_controller_report smoke completed." if validation.get("valid") else "DECISION final_controller_report smoke failed validation.",
        }
    except Exception as exc:
        return blocked(stage, exc)


def _append_real_stage(
    stages: list[dict[str, Any]],
    stage: StageSpec,
    content: Any,
    *,
    base_dir: str | Path,
    executor: TaskEngineExecutor,
    status: str,
    executor_model: str | None = None,
) -> None:
    artifact_path, outputs = executor.write_artifact(stage, content, base_dir=base_dir)
    record = executor.make_stage_record(
        stage,
        base_dir=base_dir,
        artifact_path=artifact_path,
        outputs=outputs,
        created=True,
        valid=True,
        status=status,
        executor_model=executor_model or getattr(executor, "last_executor_models", {}).get(stage.stage_name, stage.model),
    )
    stages.append(record.__dict__)


def resolve_agy_model_alias(canonical_model: str) -> str:
    """Resolve canonical Gemini binding to an actual AGY model id.

    The canonical StageRecord keeps the requested Gemini label. The actual AGY
    CLI model can be configured separately, but must never be blank or CCPA.
    """
    env_keys = {
        GEMINI_HIGH: "HERMES_AGY_GEMINI_HIGH_MODEL",
        GEMINI_PRO_HIGH: "HERMES_AGY_GEMINI_PRO_HIGH_MODEL",
    }
    env_key = env_keys.get(canonical_model)
    if not env_key:
        return canonical_model
    actual = (
        os.getenv(env_key, "").strip()
        or _env_file_agy_model(env_key)
    )
    if not actual:
        settings_model = _settings_agy_model()
        actual = settings_model if settings_model == canonical_model else canonical_model
    if actual.strip().lower() == "ccpa":
        raise RuntimeError("AGY actual model resolved to forbidden CCPA alias")
    return actual


def resolve_r1_omlx_model_alias(canonical_model: str) -> str:
    if canonical_model != R1_32B:
        raise RuntimeError("R1 OMLX alias resolver only accepts canonical R1-32B")
    return (
        os.getenv("HERMES_OMLX_R1_MODEL", "").strip()
        or _env_file_value("HERMES_OMLX_R1_MODEL", Path(os.getenv("HERMES_R1_MODEL_ALIAS_ENV", "work/agy_model_alias.env")))
        or R1_ACTUAL_MODEL_DEFAULT
    )


def resolve_qwen72b_omlx_model_alias(canonical_model: str) -> str:
    if canonical_model != QWEN72B:
        raise RuntimeError("Qwen72B OMLX alias resolver only accepts canonical Qwen72B")
    actual = (
        os.getenv("HERMES_OMLX_QWEN72B_MODEL", "").strip()
        or _env_file_value(
            "HERMES_OMLX_QWEN72B_MODEL",
            Path(os.getenv("HERMES_QWEN72B_MODEL_ALIAS_ENV", "work/agy_model_alias.env")),
        )
        or QWEN72B_ACTUAL_MODEL_DEFAULT
    )
    forbidden = ("9b", "r1", "deepseek", "flash", "controller")
    lowered = actual.lower()
    if any(token in lowered for token in forbidden):
        raise RuntimeError(f"structure_mapper: forbidden Qwen72B actual model alias: {actual}")
    return actual


def resolve_nemotron120b_omlx_model_alias(canonical_model: str) -> str:
    if canonical_model != NEMOTRON120B:
        raise RuntimeError("Nemotron-120B OMLX alias resolver only accepts canonical Nemotron-120B")
    actual = (
        os.getenv("HERMES_OMLX_NEMOTRON120B_MODEL", "").strip()
        or _env_file_value(
            "HERMES_OMLX_NEMOTRON120B_MODEL",
            Path(os.getenv("HERMES_NEMOTRON120B_MODEL_ALIAS_ENV", "work/agy_model_alias.env")),
        )
        or NEMOTRON120B_ACTUAL_MODEL_DEFAULT
    )
    forbidden = ("9b", "qwen", "r1", "deepseek", "flash", "controller")
    lowered = actual.lower()
    if any(token in lowered for token in forbidden):
        raise RuntimeError(f"evidence_judge: forbidden Nemotron-120B actual model alias: {actual}")
    return actual


def resolve_llama70b_omlx_model_alias(canonical_model: str) -> str:
    if canonical_model != LLAMA70B:
        raise RuntimeError("Llama70B OMLX alias resolver only accepts canonical Llama70B")
    actual = (
        os.getenv("HERMES_OMLX_LLAMA70B_MODEL", "").strip()
        or _env_file_value(
            "HERMES_OMLX_LLAMA70B_MODEL",
            Path(os.getenv("HERMES_LLAMA70B_MODEL_ALIAS_ENV", "work/agy_model_alias.env")),
        )
        or LLAMA70B_ACTUAL_MODEL_DEFAULT
    )
    forbidden = ("9b", "qwen", "nemotron", "r1", "deepseek", "flash", "controller")
    lowered = actual.lower()
    if any(token in lowered for token in forbidden):
        raise RuntimeError(f"premise_auditor: forbidden Llama70B actual model alias: {actual}")
    return actual


def resolve_gemma431b_omlx_model_alias(canonical_model: str) -> str:
    if canonical_model != GEMMA431B:
        raise RuntimeError("Gemma-4-31B OMLX alias resolver only accepts canonical Gemma-4-31B")
    actual = (
        os.getenv("HERMES_OMLX_GEMMA431B_MODEL", "").strip()
        or _env_file_value(
            "HERMES_OMLX_GEMMA431B_MODEL",
            Path(os.getenv("HERMES_GEMMA431B_MODEL_ALIAS_ENV", "work/agy_model_alias.env")),
        )
        or GEMMA431B_ACTUAL_MODEL_DEFAULT
    )
    forbidden = ("9b", "qwen", "nemotron", "llama", "r1", "deepseek", "flash", "controller")
    lowered = actual.lower()
    if any(token in lowered for token in forbidden):
        raise RuntimeError(f"alternative_generator: forbidden Gemma-4-31B actual model alias: {actual}")
    return actual


class _OmlxAdmin:
    """L3-only OMLX admin client matching the legacy decision-engine path."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.admin_url = f"{self.base_url}/admin/api"
        self.api_key = api_key
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self._logged_in = False

    def login(self) -> bool:
        try:
            result = self._raw_request("POST", "/login", {"api_key": self.api_key}, timeout=10)
            self._logged_in = bool(result.get("success"))
            return self._logged_in
        except Exception:
            return False

    def _admin_request(self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: int = 120) -> dict[str, Any]:
        if not self._logged_in:
            raise RuntimeError("OMLX_AUTH_BLOCKED: admin session not logged in")
        return self._raw_request(method, path, body, timeout=timeout)

    def _raw_request(self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: int = 120) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body else None
        headers = {"Content-Type": "application/json"} if data else {}
        request = urllib.request.Request(
            f"{self.admin_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            return {"error": True, "status": int(exc.code), "detail": detail}
        except Exception as exc:
            return {"error": True, "detail": str(exc)}

    def get_models(self) -> list[dict[str, Any]]:
        result = self._admin_request("GET", "/models")
        models = result.get("models")
        return models if isinstance(models, list) else []

    def is_model_loaded(self, model_id: str) -> bool:
        for item in self.get_models():
            if not isinstance(item, dict) or str(item.get("id") or "") != model_id:
                continue
            state = str(item.get("state") or item.get("status") or "").lower()
            return bool(item.get("loaded") or item.get("is_loaded") or state == "loaded")
        return False

    def unload_all(self) -> None:
        for item in self.get_models():
            if not isinstance(item, dict) or not item.get("id"):
                continue
            model_id = str(item["id"])
            if self.is_model_loaded(model_id):
                self.unload_and_wait(model_id)

    def load_model(self, model_id: str) -> dict[str, Any]:
        return self._admin_request("POST", f"/models/{model_id}/load", timeout=900)

    def unload_model(self, model_id: str) -> dict[str, Any]:
        return self._admin_request("POST", f"/models/{model_id}/unload", timeout=120)

    def unload_and_wait(self, model_id: str, *, timeout: int = 15) -> bool:
        self.unload_model(model_id)
        time.sleep(3)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_model_loaded(model_id):
                return True
            time.sleep(1.5)
        return not self.is_model_loaded(model_id)


def _omlx_chat_completion(
    model: str,
    messages: list[dict[str, str]],
    *,
    api_key: str,
    timeout: int,
    max_tokens: int,
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        f"{_omlx_base_url()}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        if int(exc.code) == 401:
            raise RuntimeError("OMLX_AUTH_BLOCKED: chat completion rejected OMLX_API_KEY") from exc
        raise RuntimeError(f"OMLX chat HTTP {int(exc.code)}: {_redact_secret_text(detail)}") from exc
    except http.client.IncompleteRead:
        raise
    except Exception as exc:
        raise RuntimeError(f"OMLX chat failed: {_redact_secret_text(str(exc))}") from exc


def _run_omlx_chat_with_retry(stage: StageSpec, actual_model: str, prompt: str, *, api_key: str) -> dict[str, Any]:
    attempts = 2 if stage.stage_name in {"evidence_judge", "premise_auditor"} else 1
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _omlx_chat_completion(
                actual_model,
                [{"role": "user", "content": prompt}],
                api_key=api_key,
                timeout=_omlx_timeout_s(),
                max_tokens=_omlx_max_tokens_for_stage(stage),
            )
        except http.client.IncompleteRead as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(0.5)
                continue
            break
    raise RuntimeError(f"{stage.stage_name}: OMLX chat IncompleteRead after {attempts} attempts") from last_error


def _omlx_base_url() -> str:
    raw = (
        os.getenv("OMLX_BASE", "").strip()
        or os.getenv("OMLX_BASE_URL", "").strip()
        or _decision_engine_api_config().get("base_url", "")
        or "http://127.0.0.1:8000"
    )
    base = str(raw).rstrip("/")
    return base[:-3].rstrip("/") if base.endswith("/v1") else base


def _run_gpt_bridge_calibration(prompt: str) -> str:
    global _GPT_BRIDGE_LAST_EXECUTOR_MODEL
    command_value = os.getenv("HERMES_GPT_BRIDGE_CMD", "").strip() or _hermes_env_value("HERMES_GPT_BRIDGE_CMD")
    url_value = os.getenv("HERMES_GPT_BRIDGE_URL", "").strip() or _hermes_env_value("HERMES_GPT_BRIDGE_URL")
    timeout_s = _gpt_bridge_timeout_s()
    if command_value:
        _GPT_BRIDGE_LAST_EXECUTOR_MODEL = "GPT Bridge"
        command = shlex.split(command_value)
        if not command:
            raise RuntimeError("GPT_BRIDGE_CMD_EMPTY")
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "GPT_BRIDGE_CMD_FAILED:"
                + _redact_secret_text((result.stderr or result.stdout or f"returncode={result.returncode}")[:1000])
            )
        return (result.stdout or "").strip()
    if url_value:
        _GPT_BRIDGE_LAST_EXECUTOR_MODEL = "GPT Bridge"
        body = json.dumps({"prompt": prompt}).encode("utf-8")
        request = urllib.request.Request(
            url_value,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise RuntimeError(f"GPT_BRIDGE_HTTP_{int(exc.code)}:{_redact_secret_text(detail)}") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text.strip()
        for key in ("content", "text", "output", "message"):
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
        return text.strip()
    wrapper = _discover_chatgpt_app_bridge_wrapper()
    if wrapper:
        _GPT_BRIDGE_LAST_EXECUTOR_MODEL = "ChatGPT App Bridge"
        return _run_chatgpt_app_bridge_wrapper(wrapper, prompt, timeout_s=timeout_s)
    raise RuntimeError("GPT_BRIDGE_NOT_CONFIGURED")


def _gpt_bridge_executor_model() -> str:
    return _GPT_BRIDGE_LAST_EXECUTOR_MODEL or "GPT Bridge"


def _discover_chatgpt_app_bridge_wrapper() -> Path | None:
    if CHATGPT_APP_BRIDGE_WRAPPER.exists():
        return CHATGPT_APP_BRIDGE_WRAPPER
    configured = _decision_engine_bridge_script()
    if configured and configured.exists():
        return configured
    return None


def _decision_engine_bridge_script() -> Path | None:
    path = Path(os.getenv("HERMES_DECISION_ENGINE_CONFIG", "/Users/xqdwww/decision-engine/config.yaml"))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("bridge_script:"):
            continue
        value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        return Path(value) if value else None
    return None


def _run_chatgpt_app_bridge_wrapper(wrapper: Path, prompt: str, *, timeout_s: int) -> str:
    command = [sys.executable, str(wrapper), prompt, "--timeout", str(timeout_s)]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_s + 30,
    )
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if result.returncode != 0:
        raise RuntimeError(
            "GPT_BRIDGE_WRAPPER_FAILED:"
            + _redact_secret_text((stderr or stdout or f"returncode={result.returncode}")[:1000])
        )
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        if stdout.strip():
            return stdout.strip()
        raise RuntimeError("GPT_BRIDGE_WRAPPER_EMPTY_OUTPUT")
    ok = bool(data.get("success") or data.get("ok"))
    content = _first_text_value(data, ("response", "text", "content", "output", "message"))
    if ok and content:
        return content
    error = str(data.get("error") or "GPT Bridge wrapper returned no content")
    raise RuntimeError("GPT_BRIDGE_WRAPPER_FAILED:" + _redact_secret_text(error))


def _first_text_value(data: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(data, dict):
        return ""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _gpt_bridge_timeout_s() -> int:
    raw = os.getenv("HERMES_GPT_BRIDGE_TIMEOUT_S", "").strip() or _hermes_env_value("HERMES_GPT_BRIDGE_TIMEOUT_S")
    try:
        return max(10, min(int(raw or "240"), 600))
    except ValueError:
        return 240


def _gpt_bridge_header_retry_wait_s() -> float:
    raw = os.getenv("HERMES_GPT_BRIDGE_HEADER_RETRY_WAIT_S", "").strip() or _hermes_env_value("HERMES_GPT_BRIDGE_HEADER_RETRY_WAIT_S")
    try:
        return max(0.0, min(float(raw or "8"), 60.0))
    except ValueError:
        return 8.0


def _write_external_calibration_invalid(
    stage: StageSpec,
    *,
    base_dir: Any,
    content: str,
    executor_model: str,
    fallback_used: bool,
    error_summary: str,
    attempt: str,
) -> None:
    if not base_dir:
        return
    try:
        stage_dir = Path(base_dir) / stage.stage_name
        stage_dir.mkdir(parents=True, exist_ok=True)
        raw_text = str(content or "")
        (stage_dir / "external_calibration.invalid.md").write_text(_redact_secret_text(raw_text), encoding="utf-8")
        diagnostic = {
            "stage_name": stage.stage_name,
            "attempt": attempt,
            "raw_length": len(raw_text),
            "body_length": len(raw_text.strip()),
            "executor_model": executor_model,
            "fallback_used": fallback_used,
            "error_summary": _redact_secret_text(error_summary),
        }
        (stage_dir / "external_calibration.diagnostic.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        return


def _write_final_controller_invalid(
    stage: StageSpec,
    *,
    base_dir: Any,
    content: str,
    executor_model: str,
    error_summary: str,
) -> None:
    if not base_dir:
        return
    try:
        stage_dir = Path(base_dir) / stage.stage_name
        stage_dir.mkdir(parents=True, exist_ok=True)
        raw_text = str(content or "")
        (stage_dir / "final_decision_report.invalid.md").write_text(_redact_secret_text(raw_text), encoding="utf-8")
        diagnostic = {
            "stage_name": stage.stage_name,
            "raw_length": len(raw_text),
            "body_length": len(raw_text.strip()),
            "executor_model": executor_model,
            "error_summary": _redact_secret_text(error_summary),
        }
        (stage_dir / "final_controller_report.diagnostic.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        return


def _external_calibration_with_metadata(
    content: str,
    *,
    executor_model: str,
    fallback_reasons: list[str],
) -> str:
    return "\n".join(
        [
            "external_calibration",
            f"executor_model: {executor_model}",
            "fallback_reasons: " + json.dumps(fallback_reasons, ensure_ascii=False),
            "",
            str(content).strip(),
        ]
    ).strip()


def _omlx_api_key() -> str:
    return str(_omlx_api_key_details(load_env_file=True)["value"])


def _omlx_api_key_details(*, load_env_file: bool = True) -> dict[str, Any]:
    config = _decision_engine_api_config()
    env_key = str(config.get("api_key_env") or "OMLX_API_KEY")
    hermes_env_path = Path.home() / ".hermes" / ".env"
    env_value = os.getenv(env_key, "").strip()
    file_value = _hermes_env_value(env_key)
    source = "missing"
    value = ""
    if env_value:
        source = "process_env"
        value = env_value
    elif file_value:
        source = str(hermes_env_path)
        value = file_value
        if load_env_file:
            os.environ[env_key] = file_value
    return {
        "env_key": env_key,
        "source": source,
        "value": value,
        "fingerprint": _secret_fingerprint(value),
        "hermes_env_path": str(hermes_env_path),
        "hermes_env_exists": hermes_env_path.exists(),
    }


def _decision_engine_api_config() -> dict[str, Any]:
    path = Path(os.getenv("HERMES_DECISION_ENGINE_CONFIG", "/Users/xqdwww/decision-engine/config.yaml"))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    api: dict[str, Any] = {}
    in_api = False
    for line in text.splitlines():
        if line.strip() == "api:":
            in_api = True
            continue
        if in_api and line and not line.startswith((" ", "\t")):
            break
        if in_api and ":" in line:
            key, value = line.split(":", 1)
            api[key.strip()] = value.strip().strip('"').strip("'")
    return api


def _hermes_env_value(key: str) -> str:
    return _env_file_value(key, Path.home() / ".hermes" / ".env")


def _secret_fingerprint(value: str) -> dict[str, Any]:
    if not value:
        return {"present": False, "length": 0, "sha256_12": ""}
    return {
        "present": True,
        "length": len(value),
        "sha256_12": hashlib.sha256(value.encode("utf-8")).hexdigest()[:12],
    }


def _env_file_value(key: str, path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    prefix = f"{key}="
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("export "):
            stripped = stripped[len("export "):]
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip().strip('"').strip("'")
    return ""


def _safe_omlx_error(result: dict[str, Any]) -> str:
    return _redact_secret_text(str(result.get("detail") or result.get("status") or "unknown"))


def _is_omlx_memory_guard_error(result: dict[str, Any]) -> bool:
    text = json.dumps(result, ensure_ascii=False, default=str).lower()
    return "memory ceiling" in text or "memory_guard_tier" in text or "projected memory" in text


def _redact_secret_text(text: str) -> str:
    key = _omlx_api_key()
    value = str(text or "")
    if key:
        value = value.replace(key, "<redacted>")
    return value[:1000]


def _primary_output_path(stage: StageSpec, outputs: dict[str, str], stage_dir: Path) -> Path:
    if stage.required_outputs == ("artifact_path",):
        return stage_dir / "report.md"
    first = stage.required_outputs[0]
    return Path(outputs[first])


def _stringify_artifact(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, indent=2)


def _assert_artifact_quality(stage: StageSpec, text: str) -> None:
    token = _artifact_error_token(text)
    if token:
        raise RuntimeError(f"{stage.stage_name}: artifact_quality_error:{token}")
    if stage.stage_name == "L5_deepseek_acceptance":
        token = _research_evidence_packet_quality_error(text)
        if token:
            raise RuntimeError(f"{stage.stage_name}: artifact_quality_error:{token}")
    if stage.stage_name == "external_calibration":
        token = _external_calibration_quality_error(text)
        if token:
            raise RuntimeError(f"{stage.stage_name}: artifact_quality_error:{token}")
    if stage.stage_name == "final_controller_report":
        token = _final_controller_quality_error(text)
        if token:
            raise RuntimeError(f"{stage.stage_name}: artifact_quality_error:{token}")


def _artifact_error_token(text: str) -> str:
    head = (text or "")[:5000]
    lines = [line.strip() for line in head.splitlines()[:40] if line.strip()]
    lowered_head = "\n".join(lines).lower()
    prefix_checks = (
        ("error_timeout_response", "error: timed out waiting for response"),
        ("error_prefix_timeout", "error: timeout"),
        ("bracket_error", "[error:"),
        ("traceback", "traceback"),
        ("exception_prefix", "exception"),
    )
    for token, prefix in prefix_checks:
        if any(line.lower().startswith(prefix) for line in lines):
            return token
    phrase_checks = (
        ("authentication_timed_out", "authentication timed out"),
        ("antigravity_not_logged_in", "you are not logged into antigravity"),
        ("omlx_auth_blocked", "omlx_auth_blocked"),
        ("agy_call_blocked", "agy_call_blocked"),
        ("ddgs_no_fresh_hits", "ddgs returned no fresh hits"),
        ("ddgs_no_fresh_result_urls", "ddgs returned no fresh result urls"),
        ("gpt_bridge_not_configured", "gpt_bridge_not_configured"),
        ("empty_stdout", "returned empty stdout"),
    )
    for token, phrase in phrase_checks:
        if phrase in lowered_head:
            return token
    return ""


def _task_engine_profiles_from_query(query: str) -> list[str]:
    value = query or ""
    lowered = value.lower()
    profiles: list[str] = []

    foresight_terms = (
        "未来10年",
        "未来 10 年",
        "未来十年",
        "ai 环境",
        "ai降低",
        "ai 降低",
        "知识获取成本",
        "结构性反转",
        "优势变陷阱",
        "缺陷变优势",
        "机制推理",
        "趋势演化",
        "情景判断",
        "foresight",
        "structural reversal",
        "future scenario",
    )
    if any(term in value for term in foresight_terms) or any(term in lowered for term in ("future scenario", "structural reversal")):
        profiles.append(PROFILE_FORESIGHT_MECHANISM)

    implementation_terms = (
        "家长行为培训",
        "如何执行",
        "训练方案",
        "准备路线",
        "操作计划",
        "执行计划",
        "干预方案",
        "implementation plan",
        "parent training",
    )
    if any(term in value for term in implementation_terms) or any(term in lowered for term in ("implementation plan", "parent training")):
        profiles.append(PROFILE_IMPLEMENTATION_PLAN)

    evidence_terms = (
        "医学",
        "治疗方案",
        "研究进展",
        "文献综述",
        "指南",
        "循证",
        "证据",
        "therapy",
        "treatment",
        "guideline",
        "evidence",
    )
    if not profiles or any(term in value for term in evidence_terms) or any(term in lowered for term in ("treatment", "guideline", "evidence")):
        profiles.insert(0, PROFILE_EVIDENCE_GROUNDED)

    deduped: list[str] = []
    for profile in profiles:
        if profile not in deduped:
            deduped.append(profile)
    return deduped


def _external_calibration_quality_error(text: str) -> str:
    value = (text or "").strip()
    lowered = value.lower()
    if _external_calibration_has_minimum_fields(value):
        missing_body = _external_calibration_header_only_fields(value)
        if missing_body:
            return "external_calibration_header_only"
        if not any(term in lowered for term in ("supported", "plausible", "speculative", "contradicted", "支持", "可信", "推测", "矛盾")):
            return "external_calibration_missing_strength_labels"
        return ""
    if len(value) < 1500:
        if any(term in lowered for term in ("calibration_scope", "claim_strength_table", "calibration_verdict")):
            return "external_calibration_header_only"
        return "external_calibration_too_short"
    tail = _normalized_tail(value)
    if _tail_looks_truncated(tail):
        return "truncated_tail"
    if not any(term in lowered for term in ("supported", "plausible", "speculative", "contradicted", "支持", "可信", "推测", "矛盾")):
        return "external_calibration_missing_strength_labels"
    if not any(term in lowered for term in ("calibration verdict", "calibration_verdict", "校准结论", "verdict")):
        return "external_calibration_missing_verdict"
    if "claim_strength_table" in lowered and "calibration" not in lowered[lowered.rfind("claim_strength_table"):]:
        return "external_calibration_header_only"
    return ""


EXTERNAL_CALIBRATION_MINIMUM_FIELDS = (
    "calibration_verdict",
    "agreement_points",
    "disagreement_or_risk_points",
    "missing_considerations",
    "final_adjustment_recommendation",
)


def _external_calibration_has_minimum_fields(text: str) -> bool:
    lowered = (text or "").lower()
    return all(field in lowered for field in EXTERNAL_CALIBRATION_MINIMUM_FIELDS)


def _external_calibration_header_only_fields(text: str) -> list[str]:
    missing: list[str] = []
    for field in EXTERNAL_CALIBRATION_MINIMUM_FIELDS:
        body = _markdown_section_body(text, field) or _colon_or_plain_section_body(text, field)
        if len(" ".join(body.split())) < 20:
            missing.append(field)
    return missing


def _colon_or_plain_section_body(text: str, field: str) -> str:
    lines = (text or "").splitlines()
    start = -1
    lowered_field = field.lower()
    known = set(EXTERNAL_CALIBRATION_MINIMUM_FIELDS)
    for index, line in enumerate(lines):
        stripped = line.strip().lower().lstrip("#").strip()
        key = stripped.split(":", 1)[0].strip()
        if key == lowered_field:
            start = index
            break
    if start < 0:
        return ""
    collected: list[str] = []
    first = lines[start].split(":", 1)
    if len(first) == 2 and first[1].strip():
        collected.append(first[1].strip())
    for line in lines[start + 1:]:
        stripped = line.strip().lower().lstrip("#").strip()
        key = stripped.split(":", 1)[0].strip()
        if key in known:
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _final_controller_quality_error(text: str) -> str:
    value = (text or "").strip()
    lowered = value.lower()
    raw_tokens = (
        "persona raw",
        "r1 convergence body",
        "raw artifact",
        "artifact dump",
        "claim_strength_table | claim",
        "```json\n{\n  \"stage_name\"",
        "external_calibration executor_model",
        "fallback_reasons:",
        "evidence judge – decision stage",
        "evidence judge - decision stage",
        "convergence decision framework",
        "artifact (stage)",
        "strength / quality of evidence",
    )
    if any(token in lowered for token in raw_tokens):
        return "raw_intermediate_dump"
    if _looks_like_raw_markdown_table_dump(value):
        return "raw_table_dump"
    if _tail_looks_truncated(_normalized_tail(value)):
        return "truncated_tail"
    if "decision_mode=true" in lowered and any(term in value for term in ("家长行为培训详细方案", "三年级准备路线", "ADHD 儿童研究决策报告")):
        return "decision_mode_family_advice_leak"
    return ""


def _looks_like_raw_markdown_table_dump(text: str) -> bool:
    rows = [line.strip() for line in (text or "").splitlines() if line.strip().startswith("|")]
    if len(rows) < 3:
        return False
    joined = "\n".join(rows[:12]).lower()
    stageish = ("artifact" in joined or "stage" in joined or "evidence" in joined or "claim" in joined)
    has_separator = any("---" in row for row in rows[:6])
    return stageish and has_separator


def _decision_query_forbids_advice(query: str) -> bool:
    value = query or ""
    return any(
        term in value
        for term in (
            "不要家长建议",
            "不要做家长建议",
            "不要建议",
            "不要做建议",
            "不要培养计划",
            "不要做培养计划",
            "不要文献综述",
            "不要做文献综述",
        )
    )


def _decision_query_requests_future_inversion_structure(query: str) -> bool:
    value = query or ""
    return all(
        term in value
        for term in (
            "未来优势变陷阱",
            "未来缺陷变优势",
            "最危险的错误培养路径",
            "最反直觉但值得追踪的假设",
            "danger_flag",
        )
    )


def _required_decision_future_sections() -> tuple[str, ...]:
    return (
        "未来优势变陷阱 Top5",
        "未来缺陷变优势 Top5",
        "最危险的错误培养路径",
        "最反直觉但值得追踪的假设",
        "danger_flag",
    )


def _assert_final_controller_packet_quality(packet: dict[str, Any], text: str) -> None:
    token = _final_controller_quality_error(text)
    if token:
        raise RuntimeError(f"final_controller_report: artifact_quality_error:{token}")
    query = str(packet.get("query") or "")
    if str(packet.get("mode") or "") == ENGINE_DECISION:
        if _decision_query_forbids_advice(query):
            forbidden_terms = ("建议方向", "下一步", "培养计划", "家长建议", "专业评估", "补研究", "行动路线")
            found = [term for term in forbidden_terms if term in text]
            if found:
                raise RuntimeError("final_controller_report: forbidden_user_terms:" + ",".join(found))
        if _decision_query_requests_future_inversion_structure(query):
            missing = [section for section in _required_decision_future_sections() if f"## {section}" not in text]
            if missing:
                raise RuntimeError("final_controller_report: missing_requested_sections:" + ",".join(missing))
    profiles = (
        _normalize_profiles(packet.get("output_quality_profile"))
        if "output_quality_profile" in packet
        else _task_engine_profiles_from_query(query)
    )
    profile_errors = _quality_profile_errors(text, profiles, stage_name="final_controller_report")
    if profile_errors:
        raise RuntimeError("final_controller_report: output_quality_profile_error:" + ",".join(profile_errors))


def _quality_profile_errors(text: str, profiles: list[str], *, stage_name: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    errors: list[str] = []
    if _profiles_require_foresight_template(profiles):
        checks = {
            "missing_key_drivers": ("关键驱动", "驱动变量", "key_drivers", "key driver", "driver variable"),
            "missing_mechanism_chain": ("输入变量", "中介机制", "输出变量", "机制链", "mechanism_chain", "input variable", "mediating mechanism", "output variable"),
            "missing_scenario_branches": ("情景分叉", "情景 a", "情景 b", "scenario_branches", "scenario a", "scenario b", "scenario branch"),
            "missing_counter_signals": ("反证信号", "可观察指标", "counter_signals", "falsification_signals", "observable signal", "counter signal", "falsification"),
            "missing_certainty_levels": ("确定性等级", "高 / 中 / 低", "高/中/低", "certainty_levels", "confidence_level", "certainty level", "high / medium / low"),
        }
        for name, terms in checks.items():
            if not any(term in value or term in lowered for term in terms):
                errors.append(name)
    if PROFILE_IMPLEMENTATION_PLAN in profiles:
        checks = {
            "missing_cycle": ("周期", "4-6 周", "4–6 周", "cycle"),
            "missing_frequency": ("频率", "每天", "每周", "frequency"),
            "missing_steps": ("步骤", "step"),
            "missing_metrics": ("记录指标", "观察指标", "metric"),
            "missing_adjustment_rules": ("调整规则", "降难度", "adjustment rule"),
        }
        for name, terms in checks.items():
            if not any(term in value or term in lowered for term in terms):
                errors.append(name)
    if PROFILE_EVIDENCE_GROUNDED in profiles and stage_name == "final_controller_report":
        checks = {
            "missing_evidence_strength": ("证据强度", "evidence_strength", "evidence strength"),
            "missing_controversy": ("争议", "controversy"),
            "missing_gap": ("缺口", "evidence_gap", "gap"),
        }
        for name, terms in checks.items():
            if not any(term in value or term in lowered for term in terms):
                errors.append(name)
    return errors


def _normalized_tail(text: str, *, limit: int = 180) -> str:
    return " ".join((text or "").strip().split())[-limit:].strip().lower()


def _tail_looks_truncated(tail: str) -> bool:
    if not tail:
        return True
    exact_or_suffixes = (
        "claim_strength_table",
        "strength_by_claim",
        "alternative c:",
        "alternative c: proactive ne",
        "third-grad",
        "evidence pac",
        "causing",
        "deficit neutr",
        "low – inten",
        "low - inten",
        "最危险的错误培养路径 ... 过",
    )
    if any(tail.endswith(fragment) for fragment in exact_or_suffixes):
        return True
    if tail.endswith(("|", "-", "###", "##", ":")):
        return True
    return False


def _simulated_content(stage: StageSpec) -> str:
    if stage.stage_name == "external_calibration":
        return (
            "calibration_scope\n"
            "This simulated calibration artifact is intentionally complete enough for contract validation. " * 8
            + "claim_strength_table\n"
            "| Claim | Strength | Calibration Notes |\n"
            "| --- | --- | --- |\n"
            "| Simulated claim A | supported | Evidence packet directly supports this bounded claim. |\n"
            "| Simulated claim B | plausible | Current artifacts make this likely but implementation context still matters. |\n"
            "| Simulated claim C | speculative | The packet marks this as a hypothesis only. |\n"
            "| Simulated claim D | contradicted | A conflicting artifact should prevent unqualified use. |\n"
            "over_inference_checks\n"
            "The simulated calibration explicitly checks for overreach, scope creep, and unsupported extrapolation. " * 8
            + "contradiction_checks\n"
            "No simulated contradiction is allowed to pass without label and handoff note. " * 8
            + "calibration_verdict\n"
            "verdict: calibrated_for_final_controller; supported/plausible/speculative/contradicted labels are present.\n"
            "handoff_notes_for_final_controller\n"
            "Use calibrated claims only and do not convert speculative material into final advice.\n"
        )
    if stage.stage_name == "final_controller_report":
        return "FINAL CONTROLLER BODY\n\nThis is the simulated final controller report."
    if stage.stage_name == "L5_deepseek_acceptance":
        return "\n".join(
            [
                "research_evidence_packet",
                "verdict: ACCEPTED",
                "accepted: true",
                "checked_stages: [L1_gemini_search, L2_ddgs_supplement, L2_5_codex_evidence_organizer, L3_r1_synthesis, L4_gemini_audit]",
                "missing_or_invalid_artifacts: []",
                "audit_summary: Simulated L4 audit accepted the evidence packet.",
                "evidence_packet_ready_for_decision: true",
                "",
                "## evidence_strength",
                "Simulated evidence_strength: stronger support is limited to current research artifacts and audited synthesis; weaker support remains for individual long-horizon forecasts.",
                "",
                "## controversy",
                "Simulated controversy: translation from current evidence to a future AI environment depends on context, tool quality, and population differences.",
                "",
                "## evidence_gap",
                "Simulated evidence_gap: direct longitudinal evidence for the exact future scenario and individual outcome path is unavailable.",
                "",
                "## evidence_supported",
                "Simulated evidence_supported: stable current evidence may support bounded claims about executive function, feedback structure, and learning supports.",
                "",
                "## reasonable_inference",
                "Simulated reasonable_inference: current mechanisms can be connected to future decision variables only through explicit mechanism chains.",
                "",
                "## foresight_hypothesis",
                "Simulated foresight_hypothesis: future structural reversals are conditional hypotheses with uncertainty boundaries and counter-signals.",
                "",
                "scope: acceptance gate plus compact evidence packet; no new research, no search, no raw artifact dump, no user-facing advice or decision output.",
            ]
        )
    if stage.stage_name == "convergence_report":
        return "Simulated convergence artifact."
    return f"Simulated artifact for {stage.stage_name} using {stage.model}."


def _gemini_search_prompt(query: str) -> str:
    chunks = [
        "Run RESEARCH stage L1_gemini_search through AGY/Gemini.",
        "Use Gemini 3.5 Flash (High). Return source candidates as concise JSON-compatible notes.",
        "Output must be short structured JSON-compatible notes only: max 8 source_candidates; max 2 lines per item.",
        "Include coverage_axes (or an equivalent field) naming which evidence axes are covered.",
        "Consider task-relevant axes such as authoritative_guideline_or_consensus, systematic_review_or_meta_analysis, empirical_study_or_RCT, mechanism_or_theory, intervention_or_practice, local_or_contextual_source, controversy_or_counterevidence, and recent_update.",
        "Each source_candidate must briefly label evidence_type, coverage_axis, and why_relevant.",
        "If 8 candidates cannot cover all relevant axes, include known_gaps_for_L2 for DDGS supplementation.",
        "Candidates may be source URLs or search queries, but do not present L1 inference as evidence.",
        "Do not write long analysis, final-style prose, recommendations, or conclusions in L1.",
    ]
    if PROFILE_FORESIGHT_MECHANISM in _task_engine_profiles_from_query(query):
        chunks.extend(_foresight_research_prompt_guidance("L1_gemini_search"))
    chunks.append(f"Query:\n{query}")
    return "\n".join(chunks)


def _ddgs_queries(query: str) -> list[str]:
    text = query.lower()
    if "adhd" in text or "注意力" in query or "多动" in query:
        return [
            "ADHD parent training children",
            "ADHD inattentive presentation children parent training",
            "ADHD children treatment guidelines school preparation parent training",
        ]
    return [
        query[:180],
        f"{query} latest evidence guidelines",
        f"{query} systematic review treatment parent training",
    ]


def _ddgs_backend_list() -> list[str]:
    raw = os.getenv("HERMES_DDGS_BACKENDS", "duckduckgo,brave,yahoo")
    backends = [item.strip().lower() for item in raw.split(",") if item.strip()]
    forbidden = {"web_search", "generic_web_search"}
    if any(backend in forbidden for backend in backends):
        raise RuntimeError("DDGS backend list cannot include web_search fallback")
    return backends or ["duckduckgo"]


def _ddgs_timeout_s() -> int:
    try:
        return max(2, min(int(os.getenv("HERMES_DDGS_QUERY_TIMEOUT_S", "8")), 30))
    except ValueError:
        return 8


def _ddgs_retries() -> int:
    try:
        return max(0, min(int(os.getenv("HERMES_DDGS_RETRIES", "1")), 3))
    except ValueError:
        return 1


def _ddgs_search_once(query: str, *, backend: str, timeout_s: int, max_results: int) -> list[dict[str, Any]]:
    from ddgs import DDGS

    with DDGS(timeout=timeout_s) as ddgs:
        return list(ddgs.text(query, backend=backend, max_results=max_results) or [])


def _normalize_ddgs_hit(query: str, hit: dict[str, Any]) -> dict[str, str]:
    return {
        "query": query,
        "title": str(hit.get("title", "")),
        "url": str(hit.get("href") or hit.get("url") or ""),
        "snippet": str(hit.get("body") or hit.get("snippet") or ""),
    }


def _is_transient_ddgs_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "timeout" in text or "timed out" in text or "temporarily" in text


def _require_fresh_prior_for_l3(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = ["L1_gemini_search", "L2_ddgs_supplement", "L2_5_codex_evidence_organizer"]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"L3_r1_synthesis: requires fresh L1/L2/L2_5 stages in order, got={actual}")
    base = Path(base_dir).resolve()
    for record in stages:
        name = str(record.get("stage_name") or "")
        if record.get("created_in_current_run") is not True:
            raise RuntimeError(f"L3_r1_synthesis: {name} is not created_in_current_run")
        if record.get("legacy_contaminated") is not False:
            raise RuntimeError(f"L3_r1_synthesis: {name} is legacy contaminated")
        if record.get("valid_for_pipeline") is not True:
            raise RuntimeError(f"L3_r1_synthesis: {name} is not valid_for_pipeline")
        _assert_current_run_path(record.get("artifact_path"), base, name)
        for output in (record.get("outputs") or {}).values():
            _assert_current_run_path(output, base, name)


def _require_fresh_prior_for_l4(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = ["L1_gemini_search", "L2_ddgs_supplement", "L2_5_codex_evidence_organizer", "L3_r1_synthesis"]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"L4_gemini_audit: requires fresh L1/L2/L2_5/L3 stages in order, got={actual}")
    base = Path(base_dir).resolve()
    for record in stages:
        name = str(record.get("stage_name") or "")
        if record.get("created_in_current_run") is not True:
            raise RuntimeError(f"L4_gemini_audit: {name} is not created_in_current_run")
        if record.get("legacy_contaminated") is not False:
            raise RuntimeError(f"L4_gemini_audit: {name} is legacy contaminated")
        if record.get("valid_for_pipeline") is not True:
            raise RuntimeError(f"L4_gemini_audit: {name} is not valid_for_pipeline")
        _assert_current_run_path(record.get("artifact_path"), base, name, consumer_stage="L4_gemini_audit")
        for output in (record.get("outputs") or {}).values():
            _assert_current_run_path(output, base, name, consumer_stage="L4_gemini_audit")


def _require_fresh_prior_for_l5(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"L5_deepseek_acceptance: requires fresh L1/L2/L2_5/L3/L4 stages in order, got={actual}")
    base = Path(base_dir).resolve()
    for record in stages:
        name = str(record.get("stage_name") or "")
        if record.get("created_in_current_run") is not True:
            raise RuntimeError(f"L5_deepseek_acceptance: {name} is not created_in_current_run")
        if record.get("legacy_contaminated") is not False:
            raise RuntimeError(f"L5_deepseek_acceptance: {name} is legacy contaminated")
        if record.get("valid_for_pipeline") is not True:
            raise RuntimeError(f"L5_deepseek_acceptance: {name} is not valid_for_pipeline")
        _assert_current_run_path(record.get("artifact_path"), base, name, consumer_stage="L5_deepseek_acceptance")
        for output in (record.get("outputs") or {}).values():
            _assert_current_run_path(output, base, name, consumer_stage="L5_deepseek_acceptance")


def _require_accepted_research_packet_for_intelligence(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"intelligence_layer: requires accepted fresh RESEARCH L1-L5 stages in order, got={actual}")
    research_validation = validate_pipeline(ENGINE_RESEARCH, {"stages": stages}, base_dir=base_dir)
    if not research_validation.get("valid"):
        raise RuntimeError(
            "intelligence_layer: accepted research packet validation failed: "
            + "; ".join(research_validation.get("errors", []))
        )
    base = Path(base_dir).resolve()
    l5 = stages[-1]
    if l5.get("status") != "accepted":
        raise RuntimeError("intelligence_layer: L5 research packet is not accepted")
    packet_path = Path(str(l5.get("artifact_path") or "")).resolve()
    _assert_current_run_path(packet_path, base, "L5_deepseek_acceptance", consumer_stage="intelligence_layer")
    packet_text = packet_path.read_text(encoding="utf-8", errors="replace")
    if not _l5_acceptance_text_is_accepted(packet_text):
        raise RuntimeError("intelligence_layer: research_evidence_packet.md is not accepted")
    for record in stages:
        name = str(record.get("stage_name") or "")
        if record.get("created_in_current_run") is not True:
            raise RuntimeError(f"intelligence_layer: {name} is not created_in_current_run")
        if record.get("legacy_contaminated") is not False:
            raise RuntimeError(f"intelligence_layer: {name} is legacy contaminated")
        if record.get("valid_for_pipeline") is not True:
            raise RuntimeError(f"intelligence_layer: {name} is not valid_for_pipeline")
        _assert_current_run_path(record.get("artifact_path"), base, name, consumer_stage="intelligence_layer")
        for output in (record.get("outputs") or {}).values():
            _assert_current_run_path(output, base, name, consumer_stage="intelligence_layer")


def _require_fresh_prior_for_supplementary_search(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"supplementary_search: requires fresh L1-L5 plus intelligence_layer in order, got={actual}")
    _require_accepted_research_packet_for_intelligence(stages[:6], base_dir=base_dir)
    base = Path(base_dir).resolve()
    intelligence = stages[-1]
    if intelligence.get("created_in_current_run") is not True:
        raise RuntimeError("supplementary_search: intelligence_layer is not created_in_current_run")
    if intelligence.get("legacy_contaminated") is not False:
        raise RuntimeError("supplementary_search: intelligence_layer is legacy contaminated")
    if intelligence.get("valid_for_pipeline") is not True:
        raise RuntimeError("supplementary_search: intelligence_layer is not valid_for_pipeline")
    _assert_current_run_path(
        intelligence.get("artifact_path"),
        base,
        "intelligence_layer",
        consumer_stage="supplementary_search",
    )
    for output in (intelligence.get("outputs") or {}).values():
        _assert_current_run_path(output, base, "intelligence_layer", consumer_stage="supplementary_search")


def _require_fresh_prior_for_structure_mapper(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
        "supplementary_search",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"structure_mapper: requires fresh L1-L8 stages in order, got={actual}")
    _require_fresh_prior_for_supplementary_search(stages[:7], base_dir=base_dir)
    base = Path(base_dir).resolve()
    supplementary = stages[-1]
    if supplementary.get("created_in_current_run") is not True:
        raise RuntimeError("structure_mapper: supplementary_search is not created_in_current_run")
    if supplementary.get("legacy_contaminated") is not False:
        raise RuntimeError("structure_mapper: supplementary_search is legacy contaminated")
    if supplementary.get("valid_for_pipeline") is not True:
        raise RuntimeError("structure_mapper: supplementary_search is not valid_for_pipeline")
    _assert_current_run_path(
        supplementary.get("artifact_path"),
        base,
        "supplementary_search",
        consumer_stage="structure_mapper",
    )
    for output in (supplementary.get("outputs") or {}).values():
        _assert_current_run_path(output, base, "supplementary_search", consumer_stage="structure_mapper")


def _require_fresh_prior_for_evidence_judge(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
        "supplementary_search",
        "structure_mapper",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"evidence_judge: requires fresh L1-L9 stages in order, got={actual}")
    _require_fresh_prior_for_structure_mapper(stages[:8], base_dir=base_dir)
    base = Path(base_dir).resolve()
    structure = stages[-1]
    if structure.get("created_in_current_run") is not True:
        raise RuntimeError("evidence_judge: structure_mapper is not created_in_current_run")
    if structure.get("legacy_contaminated") is not False:
        raise RuntimeError("evidence_judge: structure_mapper is legacy contaminated")
    if structure.get("valid_for_pipeline") is not True:
        raise RuntimeError("evidence_judge: structure_mapper is not valid_for_pipeline")
    _assert_current_run_path(
        structure.get("artifact_path"),
        base,
        "structure_mapper",
        consumer_stage="evidence_judge",
    )
    for output in (structure.get("outputs") or {}).values():
        _assert_current_run_path(output, base, "structure_mapper", consumer_stage="evidence_judge")


def _require_fresh_prior_for_premise_auditor(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
        "supplementary_search",
        "structure_mapper",
        "evidence_judge",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"premise_auditor: requires fresh L1-L10 stages in order, got={actual}")
    _require_fresh_prior_for_evidence_judge(stages[:9], base_dir=base_dir)
    base = Path(base_dir).resolve()
    evidence = stages[-1]
    if evidence.get("created_in_current_run") is not True:
        raise RuntimeError("premise_auditor: evidence_judge is not created_in_current_run")
    if evidence.get("legacy_contaminated") is not False:
        raise RuntimeError("premise_auditor: evidence_judge is legacy contaminated")
    if evidence.get("valid_for_pipeline") is not True:
        raise RuntimeError("premise_auditor: evidence_judge is not valid_for_pipeline")
    _assert_current_run_path(
        evidence.get("artifact_path"),
        base,
        "evidence_judge",
        consumer_stage="premise_auditor",
    )
    for output in (evidence.get("outputs") or {}).values():
        _assert_current_run_path(output, base, "evidence_judge", consumer_stage="premise_auditor")


def _require_fresh_prior_for_alternative_generator(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
        "supplementary_search",
        "structure_mapper",
        "evidence_judge",
        "premise_auditor",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"alternative_generator: requires fresh L1-L11 stages in order, got={actual}")
    _require_fresh_prior_for_premise_auditor(stages[:10], base_dir=base_dir)
    base = Path(base_dir).resolve()
    premise = stages[-1]
    if premise.get("created_in_current_run") is not True:
        raise RuntimeError("alternative_generator: premise_auditor is not created_in_current_run")
    if premise.get("legacy_contaminated") is not False:
        raise RuntimeError("alternative_generator: premise_auditor is legacy contaminated")
    if premise.get("valid_for_pipeline") is not True:
        raise RuntimeError("alternative_generator: premise_auditor is not valid_for_pipeline")
    _assert_current_run_path(
        premise.get("artifact_path"),
        base,
        "premise_auditor",
        consumer_stage="alternative_generator",
    )
    for output in (premise.get("outputs") or {}).values():
        _assert_current_run_path(output, base, "premise_auditor", consumer_stage="alternative_generator")


def _require_fresh_prior_for_insight_harvester(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
        "supplementary_search",
        "structure_mapper",
        "evidence_judge",
        "premise_auditor",
        "alternative_generator",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"insight_harvester: requires fresh L1-L12 stages in order, got={actual}")
    _require_fresh_prior_for_alternative_generator(stages[:11], base_dir=base_dir)
    base = Path(base_dir).resolve()
    alternative = stages[-1]
    if alternative.get("created_in_current_run") is not True:
        raise RuntimeError("insight_harvester: alternative_generator is not created_in_current_run")
    if alternative.get("legacy_contaminated") is not False:
        raise RuntimeError("insight_harvester: alternative_generator is legacy contaminated")
    if alternative.get("valid_for_pipeline") is not True:
        raise RuntimeError("insight_harvester: alternative_generator is not valid_for_pipeline")
    _assert_current_run_path(
        alternative.get("artifact_path"),
        base,
        "alternative_generator",
        consumer_stage="insight_harvester",
    )
    for output in (alternative.get("outputs") or {}).values():
        _assert_current_run_path(output, base, "alternative_generator", consumer_stage="insight_harvester")


def _require_fresh_prior_for_convergence_report(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
        "supplementary_search",
        "structure_mapper",
        "evidence_judge",
        "premise_auditor",
        "alternative_generator",
        "insight_harvester",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"convergence_report: requires fresh L1-L13 stages in order, got={actual}")
    _require_fresh_prior_for_insight_harvester(stages[:12], base_dir=base_dir)
    base = Path(base_dir).resolve()
    for record in stages:
        name = str(record.get("stage_name") or "")
        if record.get("created_in_current_run") is not True:
            raise RuntimeError(f"convergence_report: {name} is not created_in_current_run")
        if record.get("legacy_contaminated") is not False:
            raise RuntimeError(f"convergence_report: {name} is legacy contaminated")
        if record.get("valid_for_pipeline") is not True:
            raise RuntimeError(f"convergence_report: {name} is not valid_for_pipeline")
        _assert_current_run_path(record.get("artifact_path"), base, name, consumer_stage="convergence_report")
        for output in (record.get("outputs") or {}).values():
            _assert_current_run_path(output, base, name, consumer_stage="convergence_report")
    divergence_roles = [
        "structure_mapper",
        "evidence_judge",
        "premise_auditor",
        "alternative_generator",
        "insight_harvester",
    ]
    by_name = {str(record.get("stage_name") or ""): record for record in stages}
    missing = [role for role in divergence_roles if role not in by_name]
    if missing:
        raise RuntimeError(f"convergence_report: missing divergence roles: {', '.join(missing)}")
    unique_models = {str(by_name[role].get("model") or "") for role in divergence_roles}
    if len(unique_models) < 4:
        raise RuntimeError(f"convergence_report: unique divergence models < 4: {sorted(unique_models)}")


def _require_fresh_prior_for_external_calibration(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
        "supplementary_search",
        "structure_mapper",
        "evidence_judge",
        "premise_auditor",
        "alternative_generator",
        "insight_harvester",
        "convergence_report",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"external_calibration: requires fresh L1-L14 stages in order, got={actual}")
    _require_fresh_prior_for_convergence_report(stages[:13], base_dir=base_dir)
    base = Path(base_dir).resolve()
    convergence = stages[-1]
    if convergence.get("created_in_current_run") is not True:
        raise RuntimeError("external_calibration: convergence_report is not created_in_current_run")
    if convergence.get("legacy_contaminated") is not False:
        raise RuntimeError("external_calibration: convergence_report is legacy contaminated")
    if convergence.get("valid_for_pipeline") is not True:
        raise RuntimeError("external_calibration: convergence_report is not valid_for_pipeline")
    if convergence.get("model") != R1_32B:
        raise RuntimeError("external_calibration: convergence_report model mismatch")
    _assert_current_run_path(
        convergence.get("artifact_path"),
        base,
        "convergence_report",
        consumer_stage="external_calibration",
    )
    for output in (convergence.get("outputs") or {}).values():
        _assert_current_run_path(output, base, "convergence_report", consumer_stage="external_calibration")


def _require_fresh_prior_for_final_controller_report(stages: list[dict[str, Any]], *, base_dir: str | Path) -> None:
    expected = [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
        "supplementary_search",
        "structure_mapper",
        "evidence_judge",
        "premise_auditor",
        "alternative_generator",
        "insight_harvester",
        "convergence_report",
        "external_calibration",
    ]
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"final_controller_report: requires fresh L1-L15 stages in order, got={actual}")
    _require_fresh_prior_for_external_calibration(stages[:14], base_dir=base_dir)
    base = Path(base_dir).resolve()
    external = stages[-1]
    if external.get("created_in_current_run") is not True:
        raise RuntimeError("final_controller_report: external_calibration is not created_in_current_run")
    if external.get("legacy_contaminated") is not False:
        raise RuntimeError("final_controller_report: external_calibration is legacy contaminated")
    if external.get("valid_for_pipeline") is not True:
        raise RuntimeError("final_controller_report: external_calibration is not valid_for_pipeline")
    if external.get("model") != GPT_OR_GEMINI_EXTERNAL:
        raise RuntimeError("final_controller_report: external_calibration model mismatch")
    for record in stages:
        name = str(record.get("stage_name") or "")
        _assert_current_run_path(record.get("artifact_path"), base, name, consumer_stage="final_controller_report")
        for output in (record.get("outputs") or {}).values():
            _assert_current_run_path(output, base, name, consumer_stage="final_controller_report")


def _assert_current_run_path(path_value: Any, base: Path, stage_name: str, *, consumer_stage: str = "L3_r1_synthesis") -> None:
    path = Path(str(path_value or "")).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise RuntimeError(f"{consumer_stage}: {stage_name} artifact outside current run: {path}") from exc
    if not path.exists():
        raise RuntimeError(f"{consumer_stage}: {stage_name} artifact missing: {path}")


def _research_acceptance_packet_from_artifacts(stages: list[dict[str, Any]], *, base_dir: str | Path, query: str = "") -> dict[str, Any]:
    base = Path(base_dir).resolve()
    missing: list[str] = []
    audit_text = ""
    artifact_summaries: dict[str, str] = {}
    for record in stages:
        name = str(record.get("stage_name") or "")
        paths = [record.get("artifact_path")] + list((record.get("outputs") or {}).values())
        seen: set[Path] = set()
        snippets: list[str] = []
        for raw_path in paths:
            path = Path(str(raw_path or "")).resolve()
            if path in seen:
                continue
            seen.add(path)
            try:
                path.relative_to(base)
            except ValueError:
                missing.append(f"{name}:outside_current_run")
                continue
            if not path.exists():
                missing.append(f"{name}:{path.name}:missing")
                continue
            if path.is_dir():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            snippets.append(text[:1200])
            if name == "L4_gemini_audit":
                audit_text += "\n" + text
        artifact_summaries[name] = "\n".join(snippets)[:2000]
    profiles = _task_engine_profiles_from_query(query)
    if PROFILE_FORESIGHT_MECHANISM in profiles:
        artifact_summaries["_foresight_requirement_map"] = _foresight_requirement_map_text(
            "\n".join(str(value or "") for value in artifact_summaries.values())
        )
    return {
        "query": query,
        "research_packet_profile": profiles,
        "profile_acceptance_requirements": _research_profile_acceptance_requirements(profiles),
        "checked_stages": [stage.get("stage_name") for stage in stages],
        "missing_or_invalid_artifacts": missing,
        "artifact_summaries": artifact_summaries,
        "audit_text": audit_text,
        "audit_summary": _audit_summary(audit_text),
    }


def _audit_summary(audit_text: str) -> str:
    stripped = " ".join((audit_text or "").split())
    if not stripped:
        return "L4 audit artifact is empty."
    return stripped[:600]


def _audit_text_rejects(audit_text: str) -> bool:
    lowered = (audit_text or "").lower()
    reject_markers = (
        "verdict: rejected",
        "accepted: false",
        "evidence_packet_ready_for_decision: false",
        "reject",
        "rejected",
    )
    return any(marker in lowered for marker in reject_markers)


def _research_profile_acceptance_requirements(profiles: list[str]) -> list[str]:
    requirements: list[str] = []
    if PROFILE_EVIDENCE_GROUNDED in profiles:
        requirements.extend([
            "evidence strength, source support, gaps, and disputes remain required for evidence_grounded tasks",
        ])
    if PROFILE_FORESIGHT_MECHANISM in profiles:
        requirements.extend([
            "evidence / inference / hypothesis distinction",
            "mechanism_chain: input variables -> mediating mechanisms -> output variables",
            "uncertainty_boundary: assumptions, confidence limits, and where evidence stops",
            "counterexample_or_failure: conditions that would falsify or reverse the hypothesis",
            "foresight hypotheses must not be presented as medical facts or settled conclusions",
        ])
    if PROFILE_IMPLEMENTATION_PLAN in profiles:
        requirements.extend([
            "implementation evidence foundation without requiring a single direct study for every step",
        ])
    return requirements


RESEARCH_PACKET_FIXED_HEADINGS = (
    "evidence_strength",
    "controversy",
    "evidence_gap",
    "evidence_supported",
    "reasonable_inference",
    "foresight_hypothesis",
)


def _compact_research_evidence_sections(packet: dict[str, Any], *, accepted: bool) -> list[str]:
    summaries = packet.get("artifact_summaries") if isinstance(packet.get("artifact_summaries"), dict) else {}
    l1_l2 = _compact_material_excerpt(summaries, ("L1_gemini_search", "L2_ddgs_supplement", "L2_5_codex_evidence_organizer"))
    l3 = _compact_material_excerpt(summaries, ("L3_r1_synthesis",))
    l4 = _compact_material_excerpt(summaries, ("L4_gemini_audit",))
    all_material = _compact_material_excerpt(summaries, ("L1_gemini_search", "L2_ddgs_supplement", "L2_5_codex_evidence_organizer", "L3_r1_synthesis", "L4_gemini_audit"), limit=520)
    profiles = _normalize_profiles(packet.get("research_packet_profile"))
    if not accepted:
        status = "L5 did not accept the packet; use only for diagnostics, not DECISION handoff."
    else:
        status = "Accepted compact packet for DECISION handoff; each section is synthesized from L1-L4 materials without raw artifact dumps."

    foresight_note = (
        "For foresight_mechanism tasks, future-facing claims below are bounded hypotheses, not settled medical facts."
        if PROFILE_FORESIGHT_MECHANISM in profiles
        else "For evidence_grounded tasks, use the strength/gap/controversy boundaries before carrying claims forward."
    )
    sections = {
        "evidence_strength": (
            f"{status} Stronger support comes from convergent L1-L4 material and L4 audit-accepted claims. "
            f"Use as high/medium/low evidence, not as raw citation text. Compact basis: {_section_basis(l1_l2 or all_material)}"
        ),
        "controversy": (
            "Controversy remains where L1-L4 materials depend on context, population differences, tool quality, or disputed translation "
            f"from current evidence to the user scenario. Compact basis: {_section_basis(l4 or all_material)}"
        ),
        "evidence_gap": (
            "Direct gaps include missing long-horizon, individual-level, and future-AI-environment evidence; DECISION must preserve these "
            f"as uncertainty boundaries. Compact basis: {_section_basis(l4 or all_material)}"
        ),
        "evidence_supported": (
            "Evidence-supported material is limited to claims grounded in current research artifacts, audit-accepted synthesis, and stable "
            f"mechanisms already present in L1-L4. Compact basis: {_section_basis(l1_l2 or l3 or all_material)}"
        ),
        "reasonable_inference": (
            "Reasonable inference may connect existing ADHD/executive-function, learning-support, feedback, and mechanism material to the "
            f"decision scenario when the intermediate mechanism is explicit. Compact basis: {_section_basis(l3 or all_material)}"
        ),
        "foresight_hypothesis": (
            f"{foresight_note} Treat future structural reversals as conditional on stated drivers, failure conditions, and counter-signals. "
            f"Compact basis: {_section_basis(l3 or l4 or all_material)}"
        ),
    }
    lines: list[str] = []
    for heading in RESEARCH_PACKET_FIXED_HEADINGS:
        lines.extend([f"## {heading}", sections[heading], ""])
    return lines[:-1]


def _compact_material_excerpt(summaries: dict[str, Any], names: tuple[str, ...], *, limit: int = 360) -> str:
    parts: list[str] = []
    for name in names:
        text = _strip_raw_artifact_metadata_for_final_body(str(summaries.get(name) or ""))
        text = _remove_research_packet_raw_metadata(text)
        if not text.strip():
            continue
        parts.append(_compact_single_line(text, limit=max(120, limit // max(1, len(names)))))
    return _compact_single_line(" | ".join(parts), limit=limit)


def _section_basis(text: str) -> str:
    value = _compact_single_line(text, limit=300)
    return value or "L1-L4 materials were present but too sparse for a richer digest; preserve uncertainty and avoid overclaiming."


def _compact_single_line(text: str, *, limit: int = 300) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _remove_research_packet_raw_metadata(text: str) -> str:
    forbidden_prefixes = (
        "artifact_path:",
        "executor_model:",
        "valid_for_pipeline:",
        "stage_name:",
        "owner=",
        "owner:",
        "model:",
    )
    kept: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if any(prefix in lowered for prefix in forbidden_prefixes):
            continue
        kept.append(raw_line)
    return "\n".join(kept)


def _research_evidence_packet_quality_error(text: str) -> str:
    value = (text or "").strip()
    lowered = value.lower()
    if not value:
        return "empty_research_evidence_packet"
    for token in ("artifact_path", "executor_model", "valid_for_pipeline", "stage_name", "owner="):
        if token in lowered:
            return "raw_metadata_leak"
    if "verdict: accepted" not in lowered or "accepted: true" not in lowered:
        return ""
    missing = [heading for heading in RESEARCH_PACKET_FIXED_HEADINGS if f"## {heading}" not in lowered]
    if missing:
        return "missing_research_packet_sections:" + ",".join(missing)
    for heading in RESEARCH_PACKET_FIXED_HEADINGS:
        body = _markdown_section_body(value, heading)
        if len(body) < 60:
            return f"thin_research_packet_section:{heading}"
    section_text = "\n".join(_markdown_section_body(value, heading).lower() for heading in RESEARCH_PACKET_FIXED_HEADINGS)
    if not section_text.strip():
        return "acceptance_summary_only"
    acceptance_only_terms = (
        "requirements satisfied",
        "requirement satisfied",
        "accepted",
        "acceptance gate",
        "audit accepted",
        "ready for decision",
    )
    substantive_terms = (
        "evidence",
        "证据",
        "inference",
        "推断",
        "hypothesis",
        "假设",
        "gap",
        "缺口",
        "controvers",
        "争议",
        "mechanism",
        "机制",
        "uncertainty",
        "不确定",
    )
    if any(term in section_text for term in acceptance_only_terms) and not any(term in section_text for term in substantive_terms):
        return "acceptance_summary_only"
    return ""


def _markdown_section_body(text: str, heading: str) -> str:
    marker = f"## {heading}"
    lowered = text.lower()
    start = lowered.find(marker.lower())
    if start < 0:
        return ""
    body_start = start + len(marker)
    next_index = lowered.find("\n## ", body_start)
    if next_index < 0:
        next_index = len(text)
    return text[body_start:next_index].strip()


def _normalize_profiles(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = [part.strip() for part in raw.strip("[]").split(",")]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(part).strip() for part in raw]
    else:
        values = []
    normalized: list[str] = []
    for value in values:
        if value in {
            PROFILE_EVIDENCE_GROUNDED,
            PROFILE_FORESIGHT_MECHANISM,
            PROFILE_FUTURE_SCENARIO,
            PROFILE_IMPLEMENTATION_PLAN,
        } and value not in normalized:
            normalized.append(value)
    return normalized or [PROFILE_EVIDENCE_GROUNDED]


def _research_packet_profile_acceptance_issues(packet: dict[str, Any]) -> list[str]:
    profiles = _normalize_profiles(packet.get("research_packet_profile"))
    summaries = packet.get("artifact_summaries") if isinstance(packet.get("artifact_summaries"), dict) else {}
    combined = "\n".join(str(value or "") for value in summaries.values())
    issues: list[str] = []
    if PROFILE_FORESIGHT_MECHANISM in profiles:
        missing = _foresight_research_packet_missing_requirements(combined)
        issues.extend(f"foresight_mechanism_missing:{name}" for name in missing)
    if PROFILE_IMPLEMENTATION_PLAN in profiles:
        missing = _implementation_research_packet_missing_requirements(combined)
        issues.extend(f"implementation_plan_missing:{name}" for name in missing)
    return issues


def _foresight_research_packet_missing_requirements(text: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    requirements = {
        "evidence_basis": ("证据", "evidence", "研究", "source", "基础"),
        "inference_hypothesis_distinction": ("合理推断", "前瞻假设", "假设", "inference", "hypothesis", "speculative"),
        "mechanism_chain": ("机制", "因果", "链条", "输入变量", "中介机制", "输出变量", "mechanism", "causal"),
        "uncertainty_boundary": (
            "不确定",
            "边界",
            "边界条件",
            "成立条件",
            "失效条件",
            "不成立",
            "置信",
            "uncertainty",
            "boundary",
            "confidence",
            "confidence limit",
            "condition limit",
        ),
        "counterexample_or_failure": (
            "反例",
            "反证",
            "反证信号",
            "失败条件",
            "失效条件",
            "不成立",
            "观察指标",
            "counterexample",
            "failure condition",
            "falsification",
            "disconfirming signal",
        ),
    }
    missing: list[str] = []
    for name, terms in requirements.items():
        if not any(term in value or term in lowered for term in terms):
            missing.append(name)
    return missing


def _foresight_requirement_map_text(text: str) -> str:
    value = text or ""
    lowered = value.lower()
    synonyms = {
        "uncertainty_boundary": (
            "uncertainty_boundary",
            "不确定",
            "边界",
            "边界条件",
            "成立条件",
            "失效条件",
            "置信",
            "uncertainty",
            "boundary",
            "confidence",
        ),
        "counterexample_or_failure": (
            "counterexample_or_failure",
            "反例",
            "反证",
            "反证信号",
            "失败条件",
            "失效条件",
            "不成立",
            "观察指标",
            "counterexample",
            "failure condition",
            "falsification",
        ),
    }
    lines = [
        "foresight_requirement_map:",
        "purpose: normalize equivalent Chinese/English section labels before L5 acceptance; this does not create evidence.",
    ]
    for name, terms in synonyms.items():
        matched = [term for term in terms if term in value or term in lowered]
        if matched:
            lines.append(f"{name}: detected via {', '.join(matched[:5])}")
        else:
            lines.append(f"{name}: missing")
    return "\n".join(lines)


def _implementation_research_packet_missing_requirements(text: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    requirements = {
        "support_basis": ("证据", "支撑", "研究", "evidence", "basis"),
        "bounded_steps": ("步骤", "周期", "频率", "记录", "调整", "step", "frequency", "measure"),
    }
    return [name for name, terms in requirements.items() if not any(term in value or term in lowered for term in terms)]


def _foresight_research_prompt_guidance(stage_name: str) -> list[str]:
    return [
        f"Internal research_packet_profile includes {PROFILE_FORESIGHT_MECHANISM}; {stage_name} must support a foresight mechanism packet.",
        "Do not require direct evidence proving the future scenario, but do distinguish clearly among: evidence_support, reasonable_inference, and foresight_hypothesis.",
        "Surface mechanism_chain material: input variables -> mediating mechanisms -> output variables.",
        "Surface uncertainty_boundary material: confidence limits, assumptions, and where evidence stops.",
        "Surface counterexample_or_failure material: conditions under which the hypothesis would fail or reverse.",
        "Do not present foresight hypotheses as medical facts or settled conclusions.",
    ]


def _profiles_require_foresight_template(profiles: list[str]) -> bool:
    return PROFILE_FORESIGHT_MECHANISM in profiles or PROFILE_FUTURE_SCENARIO in profiles


def _convergence_foresight_template_lines(profiles: list[str]) -> list[str]:
    if not _profiles_require_foresight_template(profiles):
        return []
    return [
        "Because output_quality_profile includes foresight_mechanism/future_scenario, the convergence artifact MUST use this hard template.",
        "Do not rename these headings. Do not translate these headings. Do not merge these headings. Do not omit these headings.",
        "Use the exact English headings below, each on its own line:",
        "## key_drivers",
        "## mechanism_chain",
        "## scenario_branches",
        "Include at least two branches under scenario_branches: Scenario A and Scenario B.",
        "## counter_signals",
        "counter_signals may include falsification_signals, but the heading counter_signals must remain present.",
        "## certainty_levels",
        "Use high / medium / low or 高 / 中 / 低 under certainty_levels for each major claim.",
        "## uncertainty_boundary",
    ]


def _l5_acceptance_text_is_accepted(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "verdict: accepted" in lowered
        and "accepted: true" in lowered
        and "evidence_packet_ready_for_decision: true" in lowered
    )


def _require_decision_prior(
    stages: list[dict[str, Any]],
    expected: list[str],
    *,
    base_dir: str | Path,
    consumer_stage: str,
) -> None:
    actual = [stage.get("stage_name") for stage in stages]
    if actual != expected:
        raise RuntimeError(f"{consumer_stage}: requires DECISION stages {expected} in order, got={actual}")
    base = Path(base_dir).resolve()
    for record in stages:
        name = str(record.get("stage_name") or "")
        if name.startswith("L"):
            raise RuntimeError(f"{consumer_stage}: RESEARCH-only stage is not allowed in DECISION mode: {name}")
        if record.get("created_in_current_run") is not True:
            raise RuntimeError(f"{consumer_stage}: {name} is not created_in_current_run")
        if record.get("legacy_contaminated") is not False:
            raise RuntimeError(f"{consumer_stage}: {name} is legacy contaminated")
        if record.get("valid_for_pipeline") is not True:
            raise RuntimeError(f"{consumer_stage}: {name} is not valid_for_pipeline")
        _assert_current_run_path(record.get("artifact_path"), base, name, consumer_stage=consumer_stage)
        for output in (record.get("outputs") or {}).values():
            _assert_current_run_path(output, base, name, consumer_stage=consumer_stage)


def _decision_trace(stages: list[dict[str, Any]], *, base_dir: str | Path) -> list[dict[str, Any]]:
    base = Path(base_dir).resolve()
    return [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "executor_model": record.get("executor_model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve().relative_to(base)),
        }
        for record in stages
    ]


def _decision_excerpts(stages: list[dict[str, Any]], *, limit: int = 2500) -> dict[str, str]:
    excerpts: dict[str, str] = {}
    for record in stages:
        name = str(record.get("stage_name") or "")
        path = Path(str(record.get("artifact_path") or "")).resolve()
        excerpts[name] = path.read_text(encoding="utf-8", errors="replace")[:limit]
    return excerpts


def _decision_research_packet_context(research_packet_path: str | Path | None, *, limit: int = 2500) -> str:
    if not research_packet_path:
        return ""
    path = Path(research_packet_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"DECISION research_packet_path not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    digest = _research_packet_fixed_section_digest(text, limit=limit)
    excerpt = digest or _safe_final_excerpt(text, limit=limit)
    return "\n".join(
        [
            f"research_packet_path: {path}",
            "boundary: use as decision context only; do not dump raw research packet into the final report.",
            "research_packet_digest:",
            excerpt,
        ]
    )


def _research_packet_fixed_section_digest(text: str, *, limit: int = 2500) -> str:
    sections: list[str] = []
    for heading in RESEARCH_PACKET_FIXED_HEADINGS:
        body = _markdown_section_body(text or "", heading)
        if body:
            sections.append(f"## {heading}\n{_safe_final_excerpt(body, limit=max(220, limit // 6))}")
    return _safe_final_excerpt("\n\n".join(sections), limit=limit) if sections else ""


CONVERGENCE_FIXED_HEADINGS = (
    "key_drivers",
    "mechanism_chain",
    "scenario_branches",
    "counter_signals",
    "certainty_levels",
    "uncertainty_boundary",
)


def _convergence_fixed_section_digest(text: str, *, limit: int = 3200) -> str:
    sections: list[str] = []
    for heading in CONVERGENCE_FIXED_HEADINGS:
        body = _markdown_section_body(text or "", heading)
        if body:
            sections.append(f"## {heading}\n{_safe_final_excerpt(body, limit=max(260, limit // 6))}")
    return "\n\n".join(sections)[:limit] if sections else ""


def _decision_intelligence_prompt(
    query: str,
    *,
    base_dir: str | Path,
    research_packet_path: str | Path | None = None,
) -> str:
    base = Path(base_dir).resolve()
    context = _decision_research_packet_context(research_packet_path)
    lines = [
        "Run DECISION stage 1: intelligence_layer through AGY/Gemini.",
        "Use Gemini 3.5 Flash (High) only. Do not use CCPA, Controller, R1, or divergence models.",
        (
            "Input scope is restricted to the user's original decision question plus the supplied research_evidence_packet.md excerpt. This is DECISION mode, so do not run or invent RESEARCH L1-L5 artifacts."
            if context
            else "Input scope is restricted to the user's original decision question. This is DECISION mode, so do not require or invent RESEARCH L1-L5 artifacts."
        ),
        "Produce a high-level structured mapping of the decision problem, uncertainty, constraints, and later-stage evidence needs.",
        "Return only these sections: user_question_map, decision_dimensions_for_later_stages, evidence_needs_for_stage2, open_items_for_stage2.",
        "Do not add conclusions, clinical action plans, final advice, or user-facing guidance.",
        "Do not perform later-stage work: supplementary_search, structure_mapper, evidence_judge, premise_auditor, alternative_generator, insight_harvester, convergence_report.",
        f"Current run root: {base}",
        "",
        "## User original decision question",
        query,
    ]
    if context:
        lines.extend(["", "## optional_research_evidence_packet_context", context])
    return "\n".join(lines)


def _decision_supplementary_search_report(
    hits: list[dict[str, str]],
    *,
    stages: list[dict[str, Any]],
    query: str,
    base_dir: str | Path,
    research_packet_path: str | Path | None = None,
) -> str:
    fresh_hits = [hit for hit in hits if hit.get("url")]
    if not fresh_hits:
        raise RuntimeError("supplementary_search: DDGS returned no fresh result URLs")
    base = Path(base_dir).resolve()
    intelligence = Path(str(stages[0].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2500]
    lines = [
        "# parent_training_supplement",
        "",
        "stage_name: supplementary_search",
        "tool: DDGS",
        "mode: DECISION",
        "scope: fresh supplemental search for parent training, school accommodations, inattentive ADHD, mind wandering, and cognitive disengagement syndrome.",
        "boundary: source supplement only; no user-facing plan and no replacement for structure_mapper or evidence_judge.",
        "",
        "## user_question_anchor",
        query.strip()[:1200],
        "",
        "## current_run_inputs",
        f"- intelligence_layer: {Path(str(stages[0].get('artifact_path') or '')).resolve().relative_to(base)}",
        "",
        "## intelligence_layer_excerpt",
        intelligence,
    ]
    context = _decision_research_packet_context(research_packet_path, limit=1200)
    if context:
        lines.extend(["", "## optional_research_evidence_packet_context", context])
    lines.extend(["", "## fresh_ddgs_result_summary"])
    for idx, hit in enumerate(fresh_hits, start=1):
        lines.extend(
            [
                f"### result_{idx}",
                f"- query: {hit.get('query', '')}",
                f"- title: {hit.get('title', '')}",
                f"- url: {hit.get('url', '')}",
                f"- snippet: {hit.get('snippet', '')}",
                "",
            ]
        )
    lines.extend(
        [
            "## handoff_notes_for_stage3",
            "- Use these fresh URLs as supplemental evidence candidates.",
            "- Keep user-facing guidance out of this stage.",
            "- Stage 3 must still independently map structure; this stage only supplies fresh search material.",
        ]
    )
    return "\n".join(lines)


def _decision_stage_prompt(
    stage: StageSpec,
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
    research_packet_path: str | Path | None = None,
) -> str:
    base = Path(base_dir).resolve()
    excerpts = _decision_excerpts(stages, limit=3000)
    context = _decision_research_packet_context(research_packet_path)
    profiles = _task_engine_profiles_from_query(query)
    foresight_sections = _convergence_foresight_template_lines(profiles) if stage.stage_name == "convergence_report" else []
    duties = {
        "structure_mapper": "Map the problem space, decision axes, constraints, uncertainties, stakeholders, and evaluation criteria.",
        "evidence_judge": "Judge evidence quality, strength, applicability, gaps, and over/under-supported claims.",
        "premise_auditor": "Audit hidden premises, premise risks, counterexamples, cultural/school-system differences, and failure modes.",
        "alternative_generator": "Generate mutually exclusive intervention intensity options and action paths under different risk assumptions.",
        "insight_harvester": "Extract cross-model insights, conflicts, anomalies, high-impact low-confidence ideas, and decision turning points.",
        "convergence_report": "Synthesize the five divergence roles into a convergence decision framework with conflicts and uncertainty boundaries.",
    }
    forbidden = {
        "structure_mapper": "Do not do evidence_judge, premise_auditor, alternative_generator, convergence, or final report.",
        "evidence_judge": "Do not do premise_auditor, alternative_generator, convergence_report, or final report.",
        "premise_auditor": "Do not do alternative_generator, convergence_report, or final report.",
        "alternative_generator": "Do not do insight_harvester, convergence_report, or final report.",
        "insight_harvester": "Do not do convergence_report or final report.",
        "convergence_report": "Do not call search, AGY, DDGS, web_search, api_call, codex_exec, or final_controller_report.",
    }
    lines = [
        f"Run DECISION stage: {stage.stage_name}.",
        f"Canonical model: {stage.model}. Do not substitute another model.",
        (
            "Input scope is restricted to current-run DECISION artifacts already listed below, the user's original question, and the supplied research_evidence_packet.md excerpt."
            if context
            else "Input scope is restricted to current-run DECISION artifacts already listed below and the user's original question."
        ),
        duties[stage.stage_name],
        forbidden[stage.stage_name],
        "Internal output_quality_profile: " + ", ".join(profiles) + ".",
        *foresight_sections,
        f"Current run root: {base}",
        "",
        "## User original decision question",
        query,
        "",
        "## Prior DECISION StageRecords",
        json.dumps(_decision_trace(stages, base_dir=base_dir), ensure_ascii=False, indent=2),
        "",
        "## Prior DECISION artifact excerpts",
        json.dumps(excerpts, ensure_ascii=False, indent=2),
    ]
    if context:
        lines.extend(["", "## optional_research_evidence_packet_context", context])
    return "\n".join(lines)


def _decision_external_calibration_prompt(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
    research_packet_path: str | Path | None = None,
) -> str:
    base = Path(base_dir).resolve()
    excerpts = _decision_excerpts(stages, limit=5000)
    context = _decision_research_packet_context(research_packet_path)
    lines = [
        "Run DECISION stage 9: external_calibration.",
        "Executor policy: GPT Bridge primary; Gemini/agy Gemini 3.1 Pro (High) fallback only if GPT Bridge is unavailable.",
        "Do not use Nemotron, R1, DeepSeek Controller, Qwen, Llama, Gemma, DDGS, or web_search.",
        (
            "Input scope is restricted to current-run DECISION artifacts: convergence_report.md, D1-D8 StageRecords, the user's original question, and the supplied research_evidence_packet.md excerpt."
            if context
            else "Input scope is restricted to current-run DECISION artifacts: convergence_report.md, D1-D8 StageRecords, and the user's original question."
        ),
        "Output duty: calibrate the evidence strength of convergence_report; mark claims as supported, plausible, speculative, or contradicted; check over-inference; give a calibration verdict.",
        "Return these required sections with substantive body text, even if you mostly agree with convergence_report: calibration_verdict, agreement_points, disagreement_or_risk_points, missing_considerations, final_adjustment_recommendation.",
        "You may also include calibration_scope, claim_strength_table, over_inference_checks, contradiction_checks, and handoff_notes_for_final_controller, but never return only headers.",
        "Do not write the final controller stage, PIPELINE_COMPLETE markers, final user advice, or a final report.",
        f"Current run root: {base}",
        "",
        "## User original decision question",
        query,
        "",
        "## D1-D8 StageRecords",
        json.dumps(_decision_trace(stages, base_dir=base_dir), ensure_ascii=False, indent=2),
        "",
        "## Current-run DECISION artifact excerpts",
        json.dumps(excerpts, ensure_ascii=False, indent=2),
    ]
    if context:
        lines.extend(["", "## optional_research_evidence_packet_context", context])
    return "\n".join(lines)


def _decision_final_controller_packet(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
    research_packet_path: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(base_dir).resolve()
    excerpts: dict[str, str] = {}
    raw_convergence = ""
    for record in stages:
        stage_name = str(record.get("stage_name") or "")
        text = Path(str(record.get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")
        excerpts[stage_name] = _safe_final_excerpt(text)
        if stage_name == "convergence_report":
            raw_convergence = text
    trace = [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "executor_model": record.get("executor_model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve().relative_to(base)),
            "valid_for_pipeline": record.get("valid_for_pipeline"),
        }
        for record in stages
    ]
    packet = {
        "mode": ENGINE_DECISION,
        "query": query,
        "base_dir": str(base),
        "output_quality_profile": _task_engine_profiles_from_query(query),
        "stage_trace": trace,
        "excerpts": excerpts,
    }
    convergence_digest = _convergence_fixed_section_digest(raw_convergence)
    if convergence_digest:
        packet["convergence_fixed_section_digest"] = convergence_digest
    research_context = _decision_research_packet_context(research_packet_path)
    if research_context:
        packet["research_evidence_packet_context"] = research_context
        profiles = _normalize_profiles(packet.get("output_quality_profile"))
        if PROFILE_EVIDENCE_GROUNDED in profiles:
            packet["final_report_requirements"] = {
                "evidence_boundary_required": True,
                "evidence_boundary_heading": "## 证据边界",
                "evidence_boundary_keys": ["evidence_strength", "controversy", "evidence_gap"],
                "evidence_boundary_policy": "Keep this as a short boundary statement, not a literature review; do not raw dump research packet metadata.",
            }
    return packet


def _intelligence_layer_prompt_from_research_packet(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
) -> str:
    base = Path(base_dir).resolve()
    l5 = stages[-1]
    packet_path = Path(str(l5.get("artifact_path") or "")).resolve()
    packet_text = packet_path.read_text(encoding="utf-8", errors="replace")[:10000]
    trace = [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve()),
        }
        for record in stages
    ]
    return "\n".join(
        [
            "Run RESEARCH_DECISION stage 7: intelligence_layer through AGY/Gemini.",
            "Use Gemini 3.5 Flash (High) only. Do not use CCPA, Controller, R1, or divergence models.",
            "Input scope is restricted to the accepted current-run research_evidence_packet.md, L1-L5 StageRecords, and the user's original question.",
            "Produce a high-level structured mapping between the research packet and the user question.",
            "Return only these sections: user_question_map, research_packet_map, decision_dimensions_for_later_stages, open_items_for_stage8.",
            "Do not add conclusions, clinical action plans, or user-facing guidance.",
            "Do not perform later-stage work: supplementary_search, structure_mapper, evidence_judge, premise_auditor, alternative_generator, insight_harvester, convergence_report.",
            f"Current run root: {base}",
            "",
            "## User original question",
            query,
            "",
            "## L1-L5 StageRecords",
            json.dumps(trace, ensure_ascii=False, indent=2),
            "",
            "## Accepted research_evidence_packet.md",
            packet_text,
        ]
    )


def _supplementary_search_queries(query: str) -> list[str]:
    return [
        "ADHD parent training children",
        "behavioral parent training ADHD inattentive children",
        "CLAS ADHD inattentive children parent training",
        "third grade ADHD executive function organization skills",
        "ADHD school accommodations inattentive children",
        "ADHD mind wandering children inattentive",
        "cognitive disengagement syndrome ADHD children parent training",
    ]


def _supplementary_search_report(
    hits: list[dict[str, str]],
    *,
    stages: list[dict[str, Any]],
    query: str,
    base_dir: str | Path,
) -> str:
    fresh_hits = [hit for hit in hits if hit.get("url")]
    if not fresh_hits:
        raise RuntimeError("supplementary_search: DDGS returned no fresh result URLs")
    base = Path(base_dir).resolve()
    packet = Path(str(stages[5].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2500]
    intelligence = Path(str(stages[6].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2500]
    lines = [
        "# parent_training_supplement",
        "",
        "stage_name: supplementary_search",
        "tool: DDGS",
        "scope: fresh supplemental search for parent training, school accommodations, inattentive ADHD, mind wandering, and cognitive disengagement syndrome.",
        "boundary: source supplement only; no user-facing plan and no replacement for structure_mapper or evidence_judge.",
        "",
        "## user_question_anchor",
        query.strip()[:1200],
        "",
        "## current_run_inputs",
        f"- research_packet: {Path(str(stages[5].get('artifact_path') or '')).resolve().relative_to(base)}",
        f"- intelligence_layer: {Path(str(stages[6].get('artifact_path') or '')).resolve().relative_to(base)}",
        "",
        "## accepted_research_packet_excerpt",
        packet,
        "",
        "## intelligence_layer_excerpt",
        intelligence,
        "",
        "## fresh_ddgs_result_summary",
    ]
    for idx, hit in enumerate(fresh_hits, start=1):
        lines.extend(
            [
                f"### result_{idx}",
                f"- query: {hit.get('query', '')}",
                f"- title: {hit.get('title', '')}",
                f"- url: {hit.get('url', '')}",
                f"- snippet: {hit.get('snippet', '')}",
                "",
            ]
        )
    lines.extend(
        [
            "## handoff_notes_for_stage9",
            "- Use these fresh URLs as supplemental evidence candidates.",
            "- Keep user-facing guidance out of this stage.",
            "- Stage 9 must still independently map structure; this stage only supplies fresh search material.",
        ]
    )
    return "\n".join(lines)


def _structure_mapper_prompt_from_artifacts(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
) -> str:
    base = Path(base_dir).resolve()
    packet = Path(str(stages[5].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3500]
    intelligence = Path(str(stages[6].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3500]
    supplement = Path(str(stages[7].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3500]
    trace = [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "executor_model": record.get("executor_model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve().relative_to(base)),
        }
        for record in stages
    ]
    return "\n".join(
        [
            "Run RESEARCH_DECISION stage 9: structure_mapper using Qwen72B only.",
            f"Canonical model: {QWEN72B}. Do not use 9B, Flash, DeepSeek Controller, or R1.",
            "Input scope is restricted to current-run fresh artifacts: research_evidence_packet.md, intelligence_layer_report.md, parent_training_supplement.md, L1-L8 StageRecords, and the user's original question.",
            "Output duty: map the problem space structure only.",
            "Return only these sections: problem_axes, actor_map, decision_questions, evidence_slots, unknowns_for_later_stages.",
            "Do not judge evidence, audit premises, generate alternatives, combine views, or write any user-facing plan.",
            f"Current run root: {base}",
            "",
            "## User original question",
            query,
            "",
            "## L1-L8 StageRecords",
            json.dumps(trace, ensure_ascii=False, indent=2),
            "",
            "## research_evidence_packet.md",
            packet,
            "",
            "## intelligence_layer_report.md",
            intelligence,
            "",
            "## parent_training_supplement.md",
            supplement,
        ]
    )


def _structure_mapper_forbidden_tokens(text: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    tokens = []
    if "final_controller_report" in lowered:
        tokens.append("final_controller_report")
    if "pipeline_status=pipeline_complete" in lowered:
        tokens.append("pipeline_status=PIPELINE_COMPLETE")

    heading_lines = [line.strip() for line in value.splitlines() if line.strip().startswith("#")]
    if any(_is_forbidden_stage_heading(line, {"convergence_report", "evidence_judge"}) for line in heading_lines):
        tokens.append("later_stage_heading")
    if any(_is_final_report_heading(line) for line in heading_lines):
        tokens.append("final_report_heading")
    if any(_is_chinese_final_advice_heading(line) for line in heading_lines):
        tokens.append("chinese_final_advice_heading")
    if any(_is_forbidden_structure_mapper_final_conclusion_heading(line) for line in heading_lines):
        tokens.append("final_conclusion_heading")
    return tokens


def _is_forbidden_structure_mapper_final_conclusion_heading(line: str) -> bool:
    normalized = line.strip("# ").strip()
    return normalized in {"最终结论", "最终判断", "最终决策", "结论报告"}


def _evidence_judge_prompt_from_artifacts(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
) -> str:
    base = Path(base_dir).resolve()
    packet = Path(str(stages[5].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3500]
    intelligence = Path(str(stages[6].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3500]
    supplement = Path(str(stages[7].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3500]
    structure = Path(str(stages[8].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3500]
    trace = [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "executor_model": record.get("executor_model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve().relative_to(base)),
        }
        for record in stages
    ]
    return "\n".join(
        [
            "Run RESEARCH_DECISION stage 10: evidence_judge using Nemotron-120B only.",
            f"Canonical model: {NEMOTRON120B}. Do not use Qwen72B, 9B, Flash, DeepSeek Controller, or R1.",
            "Input scope is restricted to current-run fresh artifacts: research_evidence_packet.md, intelligence_layer_report.md, parent_training_supplement.md, structure_mapper.md, L1-L9 StageRecords, and the user's original question.",
            "Output duty: judge evidence quality, strength, uncertainty, and applicability only.",
            "Return only these sections: evidence_quality_map, strength_by_claim, applicability_to_user_context, uncertainty_and_limits, evidence_gaps_for_later_stages.",
            "Do not audit premises, generate alternatives, combine views, or write any user-facing plan.",
            f"Current run root: {base}",
            "",
            "## User original question",
            query,
            "",
            "## L1-L9 StageRecords",
            json.dumps(trace, ensure_ascii=False, indent=2),
            "",
            "## research_evidence_packet.md",
            packet,
            "",
            "## intelligence_layer_report.md",
            intelligence,
            "",
            "## parent_training_supplement.md",
            supplement,
            "",
            "## structure_mapper.md",
            structure,
        ]
    )


def _evidence_judge_forbidden_tokens(text: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    tokens = []
    if "final_controller_report" in lowered:
        tokens.append("final_controller_report")
    if "pipeline_status=pipeline_complete" in lowered:
        tokens.append("pipeline_status=PIPELINE_COMPLETE")

    heading_lines = [line.strip() for line in value.splitlines() if line.strip().startswith("#")]
    if any(_is_forbidden_stage_heading(line, {"convergence_report", "premise_auditor"}) for line in heading_lines):
        tokens.append("later_stage_heading")
    if any(_is_final_report_heading(line) for line in heading_lines):
        tokens.append("final_report_heading")
    if any(_is_chinese_final_advice_heading(line) for line in heading_lines):
        tokens.append("chinese_final_advice_heading")
    return tokens


def _is_forbidden_stage_heading(line: str, stage_names: set[str]) -> bool:
    stripped = line.lstrip("#").strip().lower().replace(" ", "_")
    return any(stripped == name or stripped.startswith(f"{name}:") for name in stage_names)


def _write_invalid_stage_debug(stage: StageSpec, content: Any, *, base_dir: str | Path) -> Path:
    stage_dir = Path(base_dir) / stage.stage_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / f"{stage.stage_name}.invalid.md"
    path.write_text(_stringify_artifact(content), encoding="utf-8")
    return path


def _premise_auditor_prompt_from_artifacts(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
) -> str:
    base = Path(base_dir).resolve()
    packet = Path(str(stages[5].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3000]
    intelligence = Path(str(stages[6].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3000]
    supplement = Path(str(stages[7].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3000]
    structure = Path(str(stages[8].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3000]
    evidence = Path(str(stages[9].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:3000]
    trace = [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "executor_model": record.get("executor_model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve().relative_to(base)),
        }
        for record in stages
    ]
    return "\n".join(
        [
            "Run RESEARCH_DECISION stage 11: premise_auditor using Llama70B only.",
            f"Canonical model: {LLAMA70B}. Do not use Nemotron, Qwen, 9B, Flash, DeepSeek Controller, or R1.",
            "Input scope is restricted to current-run fresh artifacts: research_evidence_packet.md, intelligence_layer_report.md, parent_training_supplement.md, structure_mapper.md, evidence_judge.md, L1-L10 StageRecords, and the user's original question.",
            "Output duty: audit hidden assumptions, premise risks, counterexamples, and culture/school-system differences only.",
            "Return only these sections: implicit_premises, premise_risks, counterexamples, culture_and_school_system_differences, assumptions_for_later_stages.",
            "Do not generate alternatives, converge views, or write any user-facing plan.",
            f"Current run root: {base}",
            "",
            "## User original question",
            query,
            "",
            "## L1-L10 StageRecords",
            json.dumps(trace, ensure_ascii=False, indent=2),
            "",
            "## research_evidence_packet.md",
            packet,
            "",
            "## intelligence_layer_report.md",
            intelligence,
            "",
            "## parent_training_supplement.md",
            supplement,
            "",
            "## structure_mapper.md",
            structure,
            "",
            "## evidence_judge.md",
            evidence,
        ]
    )


def _premise_auditor_forbidden_tokens(text: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    tokens = []
    if "final_controller_report" in lowered:
        tokens.append("final_controller_report")
    if "pipeline_status=pipeline_complete" in lowered:
        tokens.append("pipeline_status=PIPELINE_COMPLETE")
    heading_lines = [line.strip() for line in value.splitlines() if line.strip().startswith("#")]
    if any(_is_forbidden_stage_heading(line, {"convergence_report", "alternative_generator"}) for line in heading_lines):
        tokens.append("later_stage_heading")
    if any(_is_final_report_heading(line) for line in heading_lines):
        tokens.append("final_report_heading")
    if any(_is_chinese_final_advice_heading(line) for line in heading_lines):
        tokens.append("chinese_final_advice_heading")
    return tokens


def _alternative_generator_prompt_from_artifacts(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
) -> str:
    base = Path(base_dir).resolve()
    packet = Path(str(stages[5].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2600]
    intelligence = Path(str(stages[6].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2600]
    supplement = Path(str(stages[7].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2600]
    structure = Path(str(stages[8].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2600]
    evidence = Path(str(stages[9].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2600]
    premise = Path(str(stages[10].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2600]
    trace = [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "executor_model": record.get("executor_model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve().relative_to(base)),
        }
        for record in stages
    ]
    return "\n".join(
        [
            "Run RESEARCH_DECISION stage 12: alternative_generator using Gemma-4-31B only.",
            f"Canonical model: {GEMMA431B}. Do not use Llama, Nemotron, Qwen, 9B, Flash, DeepSeek Controller, or R1.",
            "Input scope is restricted to current-run fresh artifacts: research_evidence_packet.md, intelligence_layer_report.md, parent_training_supplement.md, structure_mapper.md, evidence_judge.md, premise_auditor.md, L1-L11 StageRecords, and the user's original question.",
            "Output duty: generate mutually exclusive alternatives, different intervention-intensity paths, and action options under different risk assumptions.",
            "Return only these sections: mutually_exclusive_alternatives, intervention_intensity_paths, risk_assumption_branches, option_tradeoffs_for_later_stages.",
            "Do not harvest insights, converge views, rank a final choice, or write any user-facing plan.",
            f"Current run root: {base}",
            "",
            "## User original question",
            query,
            "",
            "## L1-L11 StageRecords",
            json.dumps(trace, ensure_ascii=False, indent=2),
            "",
            "## research_evidence_packet.md",
            packet,
            "",
            "## intelligence_layer_report.md",
            intelligence,
            "",
            "## parent_training_supplement.md",
            supplement,
            "",
            "## structure_mapper.md",
            structure,
            "",
            "## evidence_judge.md",
            evidence,
            "",
            "## premise_auditor.md",
            premise,
        ]
    )


def _alternative_generator_forbidden_tokens(text: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    tokens = []
    if "final_controller_report" in lowered:
        tokens.append("final_controller_report")
    if "pipeline_status=pipeline_complete" in lowered:
        tokens.append("pipeline_status=PIPELINE_COMPLETE")
    heading_lines = [line.strip() for line in value.splitlines() if line.strip().startswith("#")]
    if any(_is_forbidden_stage_heading(line, {"convergence_report", "insight_harvester"}) for line in heading_lines):
        tokens.append("later_stage_heading")
    if any(_is_final_report_heading(line) for line in heading_lines):
        tokens.append("final_report_heading")
    if any(_is_chinese_final_advice_heading(line) for line in heading_lines):
        tokens.append("chinese_final_advice_heading")
    return tokens


def _insight_harvester_prompt_from_artifacts(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
) -> str:
    base = Path(base_dir).resolve()
    packet = Path(str(stages[5].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2300]
    intelligence = Path(str(stages[6].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2300]
    supplement = Path(str(stages[7].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2300]
    structure = Path(str(stages[8].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2300]
    evidence = Path(str(stages[9].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2300]
    premise = Path(str(stages[10].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2300]
    alternatives = Path(str(stages[11].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2300]
    trace = [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "executor_model": record.get("executor_model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve().relative_to(base)),
        }
        for record in stages
    ]
    return "\n".join(
        [
            "Run RESEARCH_DECISION stage 13: insight_harvester using Gemma-4-31B only.",
            f"Canonical model: {GEMMA431B}. This is a separate call from alternative_generator even though it uses the same actual model.",
            "Do not use Llama, Nemotron, Qwen, 9B, Flash, DeepSeek Controller, or R1.",
            "Input scope is restricted to current-run fresh artifacts: research_evidence_packet.md, intelligence_layer_report.md, parent_training_supplement.md, structure_mapper.md, evidence_judge.md, premise_auditor.md, alternative_generator.md, L1-L12 StageRecords, and the user's original question.",
            "Output duty: extract cross-model insights, conflicts, outliers, high-impact low-confidence points, and decision turning points.",
            "Return only these sections: cross_model_insights, conflicts_and_tensions, outliers, high_impact_low_confidence_points, decision_turning_points.",
            "Do not converge views, rank a final choice, or write any user-facing plan.",
            f"Current run root: {base}",
            "",
            "## User original question",
            query,
            "",
            "## L1-L12 StageRecords",
            json.dumps(trace, ensure_ascii=False, indent=2),
            "",
            "## research_evidence_packet.md",
            packet,
            "",
            "## intelligence_layer_report.md",
            intelligence,
            "",
            "## parent_training_supplement.md",
            supplement,
            "",
            "## structure_mapper.md",
            structure,
            "",
            "## evidence_judge.md",
            evidence,
            "",
            "## premise_auditor.md",
            premise,
            "",
            "## alternative_generator.md",
            alternatives,
        ]
    )


def _insight_harvester_forbidden_tokens(text: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    tokens = []
    if "final_controller_report" in lowered:
        tokens.append("final_controller_report")
    if "pipeline_status=pipeline_complete" in lowered:
        tokens.append("pipeline_status=PIPELINE_COMPLETE")
    heading_lines = [line.strip() for line in value.splitlines() if line.strip().startswith("#")]
    if any(_is_forbidden_stage_heading(line, {"convergence_report"}) for line in heading_lines):
        tokens.append("later_stage_heading")
    if any(_is_final_report_heading(line) for line in heading_lines):
        tokens.append("final_report_heading")
    if any(_is_chinese_final_advice_heading(line) for line in heading_lines):
        tokens.append("chinese_final_advice_heading")
    return tokens


def _convergence_report_prompt_from_artifacts(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
) -> str:
    base = Path(base_dir).resolve()
    packet = Path(str(stages[5].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2200]
    intelligence = Path(str(stages[6].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2200]
    supplement = Path(str(stages[7].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2200]
    structure = Path(str(stages[8].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2200]
    evidence = Path(str(stages[9].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2200]
    premise = Path(str(stages[10].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2200]
    alternatives = Path(str(stages[11].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2200]
    insights = Path(str(stages[12].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:2200]
    trace = [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "executor_model": record.get("executor_model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve().relative_to(base)),
        }
        for record in stages
    ]
    profiles = _task_engine_profiles_from_query(query)
    foresight_sections = _convergence_foresight_template_lines(profiles)
    return "\n".join(
        [
            "Run RESEARCH_DECISION stage 14: convergence_report using R1-32B only.",
            f"Canonical model: {R1_32B}. Actual OMLX model must be {R1_ACTUAL_MODEL_DEFAULT}.",
            "This is a separate fresh R1 call from L3_r1_synthesis. Do not reuse r1_synthesis.md.",
            "Do not use AGY, DDGS, web_search, api_call, codex_exec, Controller, Flash, Qwen, Nemotron, Llama, Gemma, or 9B.",
            "Input scope is restricted to current-run fresh artifacts: research_evidence_packet.md, intelligence_layer_report.md, parent_training_supplement.md, structure_mapper.md, evidence_judge.md, premise_auditor.md, alternative_generator.md, insight_harvester.md, L1-L13 StageRecords, and the user's original question.",
            "Output duty: synthesize the five divergence roles, identify conflicts, and form a convergence decision framework.",
            "Internal output_quality_profile: " + ", ".join(profiles) + ".",
            "If foresight_mechanism is present, include key driving variables, input variables -> mediating mechanisms -> output variables, scenario branches, uncertainty/failure conditions, observable counter-signals, and certainty levels.",
            *foresight_sections,
            "If implementation_plan is present, include cycle, frequency, steps, metrics, and adjustment rules only when the user asks for implementation.",
            (
                "Return the hard-template headings exactly as listed above; include divergence_role_summary, conflicts_to_resolve, convergence_decision_framework, uncertainty_boundaries, and handoff_questions_for_external_calibration content inside those headings."
                if foresight_sections
                else "Return only these sections: divergence_role_summary, conflicts_to_resolve, convergence_decision_framework, uncertainty_boundaries, handoff_questions_for_external_calibration."
            ),
            "Do not write final_controller_report, PIPELINE_COMPLETE markers, or a final user-facing report.",
            f"Current run root: {base}",
            "",
            "## User original question",
            query,
            "",
            "## L1-L13 StageRecords",
            json.dumps(trace, ensure_ascii=False, indent=2),
            "",
            "## research_evidence_packet.md",
            packet,
            "",
            "## intelligence_layer_report.md",
            intelligence,
            "",
            "## parent_training_supplement.md",
            supplement,
            "",
            "## structure_mapper.md",
            structure,
            "",
            "## evidence_judge.md",
            evidence,
            "",
            "## premise_auditor.md",
            premise,
            "",
            "## alternative_generator.md",
            alternatives,
            "",
            "## insight_harvester.md",
            insights,
        ]
    )


def _convergence_report_forbidden_tokens(text: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    tokens = []
    if "final_controller_report" in lowered:
        tokens.append("final_controller_report")
    if "pipeline_status=pipeline_complete" in lowered:
        tokens.append("pipeline_status=PIPELINE_COMPLETE")
    for token in ("web_search", "api_call", "codex_exec", "delegate_task"):
        if token in lowered:
            tokens.append(token)
    if any(_is_final_report_heading(line.strip()) for line in value.splitlines() if line.strip().startswith("#")):
        tokens.append("final_report_heading")
    if any(_is_chinese_final_advice_heading(line.strip()) for line in value.splitlines() if line.strip().startswith("#")):
        tokens.append("chinese_final_advice_heading")
    return tokens


def _external_calibration_prompt_from_artifacts(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
) -> str:
    base = Path(base_dir).resolve()
    packet = Path(str(stages[5].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:5000]
    convergence = Path(str(stages[13].get("artifact_path") or "")).resolve().read_text(encoding="utf-8", errors="replace")[:8000]
    trace = [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "executor_model": record.get("executor_model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve().relative_to(base)),
        }
        for record in stages
    ]
    return "\n".join(
        [
            "Run RESEARCH_DECISION stage 15: external_calibration.",
            "Executor policy: GPT Bridge primary; Gemini/agy Gemini 3.1 Pro (High) fallback only if GPT Bridge is unavailable.",
            "Do not use Nemotron, R1, DeepSeek Controller, Qwen, Llama, Gemma, DDGS, or web_search.",
            "Input scope is restricted to current-run fresh artifacts: convergence_report.md, research_evidence_packet.md, L1-L14 StageRecords, and the user's original question.",
            "Output duty: calibrate the evidence strength of convergence_report; mark claims as supported, plausible, speculative, or contradicted; check over-inference; give a calibration verdict.",
            "Return only these sections: calibration_scope, claim_strength_table, over_inference_checks, contradiction_checks, calibration_verdict, handoff_notes_for_final_controller.",
            "Do not write the final controller stage, PIPELINE_COMPLETE markers, final user advice, or a final report.",
            f"Current run root: {base}",
            "",
            "## User original question",
            query,
            "",
            "## L1-L14 StageRecords",
            json.dumps(trace, ensure_ascii=False, indent=2),
            "",
            "## research_evidence_packet.md",
            packet,
            "",
            "## convergence_report.md",
            convergence,
        ]
    )


def _external_calibration_forbidden_tokens(text: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    tokens = []
    if "final_controller_report" in lowered:
        tokens.append("final_controller_report")
    if "pipeline_status=pipeline_complete" in lowered:
        tokens.append("pipeline_status=PIPELINE_COMPLETE")
    if any(_is_final_report_heading(line.strip()) for line in value.splitlines() if line.strip().startswith("#")):
        tokens.append("final_report_heading")
    if any(_is_chinese_final_advice_heading(line.strip()) for line in value.splitlines() if line.strip().startswith("#")):
        tokens.append("chinese_final_advice_heading")
    return tokens


def _final_controller_packet_from_artifacts(
    stages: list[dict[str, Any]],
    *,
    query: str,
    base_dir: str | Path,
) -> dict[str, Any]:
    base = Path(base_dir).resolve()
    names = [
        "L5_deepseek_acceptance",
        "intelligence_layer",
        "supplementary_search",
        "structure_mapper",
        "evidence_judge",
        "premise_auditor",
        "alternative_generator",
        "insight_harvester",
        "convergence_report",
        "external_calibration",
    ]
    by_name = {str(record.get("stage_name") or ""): record for record in stages}
    excerpts: dict[str, str] = {}
    for name in names:
        path = Path(str(by_name[name].get("artifact_path") or "")).resolve()
        text = path.read_text(encoding="utf-8", errors="replace")
        excerpts[name] = _safe_final_excerpt(text)
    trace = [
        {
            "stage_name": record.get("stage_name"),
            "owner": record.get("owner"),
            "model": record.get("model"),
            "executor_model": record.get("executor_model"),
            "artifact_path": str(Path(str(record.get("artifact_path") or "")).resolve().relative_to(base)),
            "valid_for_pipeline": record.get("valid_for_pipeline"),
        }
        for record in stages
    ]
    return {
        "mode": ENGINE_RESEARCH_DECISION,
        "query": query,
        "output_quality_profile": _task_engine_profiles_from_query(query),
        "stage_trace": trace,
        "excerpts": excerpts,
    }


def _final_controller_report_from_packet(packet: dict[str, Any]) -> str:
    query = str(packet.get("query") or "").strip()
    mode = str(packet.get("mode") or ENGINE_RESEARCH_DECISION)
    excerpts = packet.get("excerpts") if isinstance(packet.get("excerpts"), dict) else {}
    calibration = _safe_final_excerpt(str(excerpts.get("external_calibration") or ""))
    convergence = _safe_final_excerpt(str(excerpts.get("convergence_report") or ""))
    evidence = _safe_final_excerpt(str(excerpts.get("evidence_judge") or ""))
    alternatives = _safe_final_excerpt(str(excerpts.get("alternative_generator") or ""))
    premise = _safe_final_excerpt(str(excerpts.get("premise_auditor") or ""))
    if mode == ENGINE_DECISION:
        include_evidence_boundary = _decision_final_requires_evidence_boundary(packet)
        profiles = _normalize_profiles(packet.get("output_quality_profile"))
        if (
            _profiles_require_foresight_template(profiles)
            or _decision_query_requests_future_inversion_structure(query)
            or _decision_query_forbids_advice(query)
        ):
            return _decision_future_inversion_report(
                query,
                include_evidence_boundary=include_evidence_boundary,
                convergence_digest=str(packet.get("convergence_fixed_section_digest") or ""),
            )
        return _generic_decision_final_report(query, include_evidence_boundary=include_evidence_boundary)
    profiles = _normalize_profiles(packet.get("output_quality_profile"))
    if PROFILE_FORESIGHT_MECHANISM in profiles:
        return _foresight_mechanism_final_report(query)
    return "\n".join(
        [
            "# ADHD 儿童研究决策报告",
            "",
            "## 结论摘要",
            "基于当前 16 阶段证据链，本轮建议采用主动但分层的干预策略：先以家长行为培训、学校支持和执行功能脚手架为主，持续观察注意力、发呆/走神、作业独立性、情绪压力和课堂适应；如功能损害持续明显，再与专业医生讨论进一步评估和药物/非药物组合方案。",
            "",
            "## 与孩子情况的匹配",
            "用户补充的核心画像是注意力缺陷为主，不多动，主要表现为大脑放空、发呆、沉浸在内部想法，而不是被外界分心。因此路线应重点关注任务启动、持续注意、工作记忆、时间感、课堂跟随和自我监控，而不是把重点放在抑制外显多动上。",
            "",
            "## 主动干预程度",
            "- 立即做：家长行为培训、家庭作业结构化、睡眠和运动节律、课堂座位/提示/任务拆分、三年级前的组织系统。",
            "- 观察 6-12 周：记录作业时长、课堂反馈、丢三落四、发呆频率、亲子冲突和孩子自尊。",
            "- 升级条件：如果学习效率、课堂参与、情绪或家庭冲突仍明显受损，应预约儿童精神科/发育行为儿科/心理评估，讨论完整 ADHD inattentive presentation 与相关情况的鉴别。",
            "",
            "## 家长行为培训详细方案",
            "建议以 4-6 周为一个周期执行；频率上每天只练一个小目标，每周固定复盘一次。",
            "1. 明确一个行为目标：一次只训练一个可观察行为，例如 15 分钟内开始作业、书包按清单整理、听完指令后复述第一步。",
            "2. 前置提示：在任务前给短句提示和视觉清单，不在孩子已经失败后长篇说教。",
            "3. 拆小步骤：把作业、洗漱、收拾书包拆成 2-4 个小步骤，每步完成后立即反馈。",
            "4. 正向强化：用具体描述表扬努力和策略，例如“你刚才先看清单再收拾，这一步很好”。",
            "5. 代币/积分：短周期、低门槛、即时兑换，目标是建立习惯，不是用奖励压孩子。",
            "6. 减少冲突：指令短、靠近孩子、眼神确认、让孩子复述；避免在情绪高峰复盘。",
            "7. 每周复盘：只看数据和流程，问“哪个步骤卡住”，不要把注意力问题解释成态度问题；记录指标包括启动时间、完成率、提醒次数、冲突次数和孩子压力。",
            "8. 调整规则：连续两天失败就降难度、缩短任务、减少步骤；连续三天稳定再小幅提高要求。",
            "",
            "## 三年级准备路线",
            "- 建立固定作业启动仪式：喝水、摆文具、看清单、定时器。",
            "- 训练书包和文件夹系统：一进一出两个文件夹，家长每天只检查系统，不替孩子全包。",
            "- 预演课堂策略：听到老师指令后写下关键词，不懂时举手或课后问。",
            "- 和老师提前沟通：说明孩子以内在走神为主，请老师给轻提示、拆分任务、确认理解。",
            "- 保留轻量数据：每周记录 3-5 个指标，作为是否升级干预的依据。",
            "",
            "## 证据与校准边界",
            f"证据强度、争议和缺口需要分开看；外部校准摘要：{calibration[:900]}",
            "",
            "## 收敛依据",
            f"收敛框架摘要：{convergence[:900]}",
            "",
            "## 需要谨慎的地方",
            f"证据强弱与前提风险摘要：{(evidence + ' ' + premise)[:900]}",
            "",
            "## 可选路径",
            f"替代方案摘要：{alternatives[:900]}",
            "",
            "## 下一步",
            "建议先执行低风险、高结构化的家庭和学校支持方案，并预约专业评估作为并行准备；干预强度根据 6-12 周功能数据逐步升级，而不是一次性推到最高强度。",
            "",
            "## 用户原始问题锚点",
            query[:1200],
        ]
    )



def _decision_final_requires_evidence_boundary(packet: dict[str, Any]) -> bool:
    if str(packet.get("mode") or "") != ENGINE_DECISION:
        return False
    if not packet.get("research_evidence_packet_context"):
        return False
    profiles = _normalize_profiles(packet.get("output_quality_profile"))
    return PROFILE_EVIDENCE_GROUNDED in profiles


def _decision_evidence_boundary_section() -> list[str]:
    return [
        "## 证据边界",
        "evidence_strength: 强证据主要在 ADHD 执行功能、行为支持、学习脚手架和身体训练反馈的基础方向；中等证据在个性化反馈、任务结构和注意调节的可迁移机制；弱证据在未来十年 AI 降低知识获取成本 100 倍后的个体轨迹预测。",
        "controversy: ADHD 特征是否转化为优势，依赖外部结构、学校评价方式、AI 使用方式和孩子是否保留验证习惯；IQ 与柔术训练是调节因素，不是确定因果保证。",
        "evidence_gap: 目前缺少直接追踪“AI 知识获取成本极低”环境下单个 ADHD 儿童十年发展的长期证据，未来判断和个体化判断都必须保留观察边界。",
        "",
    ]


def _decision_future_inversion_report(
    query: str,
    *,
    include_evidence_boundary: bool = False,
    convergence_digest: str = "",
) -> str:
    lines = [
            "# 决策任务最终报告",
            "",
            "decision_mode=true",
            "",
            "## 未来优势变陷阱 Top5",
            "关键驱动变量：AI 降低知识获取成本、即时反馈密度上升、验证成本相对变高。确定性等级：中。",
            "1. 高理解力在知识获取成本极低时，可能变成快速接受未经验证解释的入口；真正瓶颈会从吸收转向筛选。",
            "2. 兴趣启动强、厌烦启动弱，可能在 AI 无限素材环境中变成持续换题、难以收束的探索惯性。",
            "3. 柔术带来的即时身体反馈很有价值，但也可能让抽象任务显得过慢、过虚，降低对长期反馈任务的耐受。",
            "4. 发散联想和内部世界丰富，可能在观点生成廉价化后变成观点过剩、验证不足。",
            "5. 对无意义重复的低耐受，可能在未来被误读成只适合追新，反而削弱必要的事实核查和长期积累。",
            "",
            "## 未来缺陷变优势 Top5",
            "输入变量 → 中介机制 → 输出变量：低价值重复减少 → 对任务价值的敏感度被放大 → 可能转化为筛选任务和发现异常的优势。",
            "1. 对低价值重复的抗拒，可能成为识别可被 AI 外包任务的敏感雷达。",
            "2. 注意漂移和联想跳跃，在问题发现、跨域类比、异常模式识别中可能变成优势。",
            "3. 不按线性教材节奏推进，在个性化工具足够强时，可能更适合按问题网络学习。",
            "4. 内在想法多，如果配合外部记录和收束机制，可能转化为高密度创意池。",
            "5. 身体训练形成的纪律和反馈感，可能成为调节注意、承受挫败、维持长期项目的底座。",
            "",
            "## 最危险的错误培养路径",
            "情景分叉：情景 A 是把 AI 当加速器但保留验证；情景 B 是把 AI 当替代判断的即时答案机。",
            "把孩子塑造成 AI 加速下的高产出答题机器：不断提高信息吞吐、题目完成量和即时反馈密度，却没有同步训练目标选择、延迟验证、事实核查、任务收束和错误复盘。这样最容易把聪明、兴趣和速度变成逃避慢变量的工具。",
            "",
            "## 最反直觉但值得追踪的假设",
            "未来稀缺的可能不是知道得快，而是在答案极易获得时仍能停下来确认问题是否值得、证据是否足够、结论是否过度。孩子对无意义任务的低耐受不一定只是弱点；在正确边界下，它可能变成识别低价值任务的能力。",
            "",
        ]
    if include_evidence_boundary:
        lines.extend(_decision_evidence_boundary_section())
    digest = convergence_digest.strip()
    if digest:
        lines.extend(
            [
                "## convergence_fixed_section_digest",
                digest,
                "",
            ]
        )
    lines.extend(
        [
            "## danger_flag",
            "可观察指标 / 反证信号：如果孩子能保留推理痕迹、主动核查事实、完成慢速闭环，则上述风险判断应下调。",
            "若长期出现这些信号，需要把风险级别上调：只追求即时答案、不愿保留推理痕迹；频繁换主题但很少完成闭环；用 AI 输出替代自己判断；身体训练之外的任务都要求即时反馈；对事实核查和慢速练习越来越排斥。",
        ]
    )
    return "\n".join(lines)


def _foresight_mechanism_final_report(query: str) -> str:
    return "\n".join(
        [
            "# 前瞻机制研究决策报告",
            "",
            "## 关键驱动变量",
            "核心驱动变量包括：AI 降低知识获取成本、即时反馈变多、验证与收束能力变稀缺、学校评价方式可能滞后。确定性等级：中。",
            "",
            "## 机制链",
            "输入变量 → 中介机制 → 输出变量：知识获取成本下降 → 信息筛选和延迟验证成为瓶颈 → ADHD 注意力特征中的发散、厌烦低价值重复、内部想法丰富，可能分别转化为机会或陷阱。",
            "",
            "## 情景分叉",
            "情景 A：孩子学会保留推理痕迹、核查事实、完成慢速闭环，部分注意漂移可转化为问题发现和跨域联想。情景 B：孩子把 AI 当即时答案机，兴趣跳转和未收束想法会放大为浅尝辄止。",
            "",
            "## 成立条件与失效条件",
            "成立条件：有外部结构、反馈节律、事实核查习惯和任务收束训练。失效条件：只有速度奖励、没有验证、没有完成标准、成人把所有困难都解释成天赋或态度。",
            "",
            "## 证据强度、争议和缺口",
            "证据强度：关于 ADHD 执行功能、行为支持和学习脚手架的基础证据较强；关于 AI 环境下优势/缺陷结构性反转属于合理推断和前瞻假设。争议在于不同孩子、学校和工具环境差异很大；缺口是缺少直接证明未来十年具体反转路径的长期研究。",
            "",
            "## 可观察指标 / 反证信号",
            "可观察指标包括：是否能说明自己为什么相信一个答案、是否能完成慢任务闭环、是否主动核查事实、是否能从大量选项中收束到一个目标。反证信号是：AI 使用越多，越不愿留下推理痕迹、越频繁换题、越少完成。",
            "",
            "## 用户问题锚点",
            query[:1200],
        ]
    )


def _generic_decision_final_report(query: str, *, include_evidence_boundary: bool = False) -> str:
    prompt_anchor = query[:600].strip() or "本轮 DECISION 输入未提供可显示的问题文本。"
    lines = [
            "# 决策任务最终报告",
            "",
            "decision_mode=true",
            "",
            "## 决策问题",
            prompt_anchor,
            "",
            "## 决策判断",
            "本轮 DECISION 管线完成了问题结构、证据强弱、前提风险、替代路径、洞见收束和外部校准的闭环；以下只呈现最终整合后的判断，不拼接中间 artifact 原文。",
            "",
            "## 关键依据",
            "结论仅使用当前 run 的有效 StageRecord 和已校准 artifact；未执行 RESEARCH L1-L5，因此不把本轮输出包装成研究综述。证据强度、争议和缺口需要显式保留。",
            "",
        ]
    if include_evidence_boundary:
        lines.extend(_decision_evidence_boundary_section())
    lines.extend(
        [
            "## 风险边界",
            "高不确定、依赖外部事实或需要专业角色确认的部分，应保持条件化表述。",
            "",
            "## 可选路径",
            "保留低强度、可逆路径；中强度路径；以及仅在关键风险升高时才进入的高强度路径。",
            "",
            "## 复盘指标",
            "周期可先设为 4-6 周；频率为每天记录、每周复盘；步骤是观察、执行、反馈、复盘；记录指标使用少量可观察指标检查判断是否偏离事实；调整规则是在失败时降难度，在稳定后再升级。",
        ]
    )
    return "\n".join(lines)

def _safe_final_excerpt(text: str, *, limit: int = 1200) -> str:
    value = _strip_raw_artifact_metadata_for_final_body(text or "")
    value = " ".join(value.split())
    for token in ("web_search", "api_call", "codex_exec", "delegate_task", "persona:"):
        value = value.replace(token, "[removed]")
    return value[:limit]


def _strip_raw_artifact_metadata_for_final_body(text: str) -> str:
    skipped_prefixes = (
        "executor_model:",
        "fallback_reasons:",
        "artifact_path:",
        "valid_for_pipeline:",
        "stage_name:",
        "owner=",
        "owner:",
        "model:",
    )
    skipped_exact = {
        "external_calibration",
        "convergence_report",
        "evidence_judge",
        "premise_auditor",
        "alternative_generator",
        "insight_harvester",
        "structure_mapper",
        "supplementary_search",
        "intelligence_layer",
    }
    kept: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not line:
            continue
        if lowered in skipped_exact:
            continue
        if any(lowered.startswith(prefix) for prefix in skipped_prefixes):
            continue
        if "external_calibration executor_model" in lowered:
            continue
        if lowered.startswith("pipeline ") or lowered.startswith("pipeline_"):
            continue
        kept.append(raw_line)
    return "\n".join(kept)


def _final_controller_report_forbidden_tokens(text: str) -> list[str]:
    lowered = (text or "").lower()
    tokens = []
    for token in ("web_search", "api_call", "codex_exec", "delegate_task", "persona:"):
        if token in lowered:
            tokens.append(token)
    if "r1 convergence body" in lowered or "persona raw" in lowered:
        tokens.append("raw_intermediate_dump")
    return tokens


def _intelligence_output_forbidden_tokens(text: str) -> list[str]:
    value = text or ""
    lowered = value.lower()
    tokens = []
    lines = [line.strip() for line in value.splitlines()]
    heading_lines = [line for line in lines if line.startswith("#")]

    if "final_controller_report" in lowered:
        tokens.append("final_controller_report")
    if "pipeline_status=pipeline_complete" in lowered:
        tokens.append("pipeline_status=PIPELINE_COMPLETE")
    if any(_is_final_report_heading(line) for line in heading_lines):
        tokens.append("final_report_heading")
    if any(_is_chinese_final_advice_heading(line) for line in heading_lines):
        tokens.append("chinese_final_advice_heading")

    has_action_plan = any("action plan" in line.lower() or "行动计划" in line or "行动建议" in line for line in lines)
    has_recommendation = any("recommendation" in line.lower() or "建议" in line for line in lines)
    has_direct_advice = any(_contains_direct_user_advice(line) for line in lines)
    if has_action_plan and has_recommendation and has_direct_advice:
        tokens.append("action_plan_recommendation_direct_advice")
    return tokens


def _is_final_report_heading(line: str) -> bool:
    normalized = line.strip("# ").strip().lower()
    return normalized in {
        "final controller report",
        "final report",
        "controller final report",
        "最终报告",
        "最终决策报告",
        "最终控制器报告",
    }


def _is_chinese_final_advice_heading(line: str) -> bool:
    normalized = line.strip("# ").strip()
    return normalized in {"最终建议", "行动建议", "最终行动建议", "最终决策建议"}


def _contains_direct_user_advice(line: str) -> bool:
    lowered = line.lower()
    english = (
        "you should",
        "you need to",
        "i recommend you",
        "recommended next step",
        "take the following action",
    )
    chinese = ("你应该", "你需要", "建议你", "请立即", "可以直接")
    return any(token in lowered for token in english) or any(token in line for token in chinese)


def _r1_synthesis_prompt_from_artifacts(stages: list[dict[str, Any]], *, base_dir: str | Path, query: str = "") -> str:
    base = Path(base_dir).resolve()
    chunks = [
        "Run RESEARCH stage L3_r1_synthesis using R1-32B only.",
        "Use only the fresh artifacts from L1_gemini_search, L2_ddgs_supplement, and L2_5_codex_evidence_organizer.",
        "Produce a concise research evidence synthesis. Do not audit, calibrate, decide, or write a final report.",
    ]
    if PROFILE_FORESIGHT_MECHANISM in _task_engine_profiles_from_query(query):
        chunks.extend(_foresight_research_prompt_guidance("L3_r1_synthesis"))
        chunks.append(
            "Return explicit sections named evidence_support, reasonable_inference, foresight_hypothesis, "
            "mechanism_chain, uncertainty_boundary, and counterexample_or_failure."
        )
    for record in stages:
        chunks.append(f"\n## {record.get('stage_name')}")
        paths = [record.get("artifact_path")] + list((record.get("outputs") or {}).values())
        for raw_path in paths:
            path = Path(str(raw_path or "")).resolve()
            try:
                path.relative_to(base)
            except ValueError:
                continue
            if path.is_dir():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")[:6000]
            chunks.append(f"\n### {path.name}\n{text}")
    return "\n".join(chunks)


def _gemini_audit_prompt_from_artifacts(stages: list[dict[str, Any]], *, base_dir: str | Path, query: str = "") -> str:
    base = Path(base_dir).resolve()
    chunks = [
        "Run RESEARCH stage L4_gemini_audit through AGY/Gemini.",
        "Use Gemini 3.1 Pro (High) only. Do not use Gemini 3.5 Flash, Controller, DeepSeek, or R1.",
        "Audit the L3 R1 synthesis against fresh L1/L2/L2.5 evidence artifacts.",
        "Return an audit report only. Do not produce final acceptance, final advice, or a final report.",
        "If evidence is missing or unsupported, mark it clearly as a defect or gap.",
    ]
    if PROFILE_FORESIGHT_MECHANISM in _task_engine_profiles_from_query(query):
        chunks.extend(_foresight_research_prompt_guidance("L4_gemini_audit"))
        chunks.append(
            "Audit whether L3 explicitly separates evidence_support, reasonable_inference, and foresight_hypothesis; "
            "whether it includes mechanism_chain, uncertainty_boundary, and counterexample_or_failure; "
            "and whether it avoids presenting foresight hypotheses as settled medical facts."
        )
    for record in stages:
        chunks.append(f"\n## {record.get('stage_name')}")
        paths = [record.get("artifact_path")] + list((record.get("outputs") or {}).values())
        for raw_path in paths:
            path = Path(str(raw_path or "")).resolve()
            try:
                path.relative_to(base)
            except ValueError:
                continue
            if path.is_dir():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")[:8000]
            chunks.append(f"\n### {path.name}\n{text}")
    return "\n".join(chunks)


def _omlx_timeout_s() -> int:
    try:
        return max(30, min(int(os.getenv("HERMES_OMLX_R1_TIMEOUT_S", "600")), 1800))
    except ValueError:
        return 600


def _omlx_max_tokens() -> int:
    try:
        return max(512, min(int(os.getenv("HERMES_OMLX_R1_MAX_TOKENS", "4096")), 12000))
    except ValueError:
        return 4096


def _omlx_max_tokens_for_stage(stage: StageSpec) -> int:
    if stage.stage_name == "evidence_judge":
        try:
            return max(128, min(int(os.getenv("HERMES_OMLX_EVIDENCE_JUDGE_MAX_TOKENS", "512")), 2048))
        except ValueError:
            return 512
    return _omlx_max_tokens()


def _loaded_omlx_model_ids(admin: Any) -> list[str]:
    try:
        models = admin.get_models()
    except Exception:
        return []
    loaded: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "")
        if not model_id:
            continue
        state = str(item.get("state") or item.get("status") or "").lower()
        if bool(item.get("loaded") or item.get("is_loaded") or state == "loaded"):
            loaded.append(model_id)
    return loaded


def _omlx_request_diagnostic_context(
    stage: StageSpec,
    prompt: str,
    actual_model: str,
    *,
    loaded_models_before_unload: list[str],
    loaded_models_after_unload: list[str],
    loaded_models_after_load: list[str],
    retry_attempt: str,
) -> dict[str, Any]:
    user_chars = len(prompt or "")
    max_tokens = _omlx_max_tokens_for_stage(stage)
    return {
        "prompt_chars": user_chars,
        "prompt_estimated_tokens": max(1, (user_chars + 3) // 4),
        "prompt_hash": hashlib.sha256((prompt or "").encode("utf-8")).hexdigest(),
        "prompt_preview_head": _redact_secret_text((prompt or "")[:240]),
        "prompt_preview_tail": _redact_secret_text((prompt or "")[-240:]),
        "message_count": 1,
        "system_message_chars": 0,
        "user_message_chars": user_chars,
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
        "actual_model": actual_model,
        "endpoint": f"{_omlx_base_url()}/v1/chat/completions",
        "loaded_models_before_unload": loaded_models_before_unload,
        "loaded_models_after_unload": loaded_models_after_unload,
        "loaded_models_after_load": loaded_models_after_load,
        "compact_mode_used": "compact_evidence_judge_packet" in (prompt or ""),
        "compact_budget": _extract_compact_budget_marker(prompt),
        "retry_attempt": retry_attempt,
    }


def _extract_compact_budget_marker(prompt: str) -> int | None:
    if "compact_evidence_judge_packet" not in (prompt or ""):
        return None
    return 6500


def _is_omlx_prefill_memory_text(text: str) -> bool:
    lowered = str(text or "").lower()
    return "prefill_memory_exceeded" in lowered or "prefill memory guard" in lowered


def _is_omlx_prefill_memory_diagnostic(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    return _is_omlx_prefill_memory_text(json.dumps(data, ensure_ascii=False, default=str))


def _omlx_prefill_memory_exception_diagnostic(
    stage: StageSpec,
    actual_model: str,
    exc: Exception,
    *,
    attempt: str,
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_summary = _redact_secret_text(str(exc))
    diagnostic = {
        "stage_name": stage.stage_name,
        "canonical_model": stage.model,
        "actual_model": actual_model,
        "attempt": attempt,
        "blocked_reason": "OMLX_PREFILL_MEMORY_GUARD_BLOCKED",
        "empty_content_kind": "prefill_memory_exception",
        "response_type": "exception",
        "response_keys": [],
        "error_type": type(exc).__name__,
        "error_summary": raw_summary,
        "raw_error_code": _omlx_raw_error_code_from_text(raw_summary),
        "raw_error_summary": raw_summary,
        "choices_type": "missing",
        "choices_len": 0,
        "first_choice_keys": [],
        "message_keys": [],
        "content_type": "missing",
        "content_length": 0,
        "empty_content": True,
    }
    if request_context:
        diagnostic.update(request_context)
    return diagnostic


def _omlx_empty_content_diagnostic(
    stage: StageSpec,
    actual_model: str,
    data: Any,
    *,
    attempt: str,
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    choices = data.get("choices") if isinstance(data, dict) else None
    first_choice = choices[0] if isinstance(choices, list) and choices else None
    message = first_choice.get("message") if isinstance(first_choice, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    error_value = data.get("error") if isinstance(data, dict) else None
    if isinstance(error_value, dict):
        error_summary = json.dumps(error_value, ensure_ascii=False, default=str)
    else:
        error_summary = str(error_value or "")
    if isinstance(data, dict) and error_value is not None and choices is None:
        empty_kind = "response_error_object"
    elif choices is None:
        empty_kind = "missing_choices"
    elif isinstance(choices, list) and not choices:
        empty_kind = "empty_choices"
    elif isinstance(content, str) and not content.strip():
        empty_kind = "empty_content_string"
    else:
        empty_kind = "parse_or_unknown"
    is_prefill = _is_omlx_prefill_memory_text(error_summary)
    diagnostic = {
        "stage_name": stage.stage_name,
        "canonical_model": stage.model,
        "actual_model": actual_model,
        "attempt": attempt,
        "blocked_reason": "OMLX_PREFILL_MEMORY_GUARD_BLOCKED" if is_prefill else "OMLX_EMPTY_CONTENT_BLOCKED",
        "empty_content_kind": empty_kind,
        "response_type": type(data).__name__,
        "response_keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "error_type": str(data.get("type") or "") if isinstance(data, dict) else "",
        "error_summary": _redact_secret_text(error_summary),
        "raw_error_code": _omlx_raw_error_code(data),
        "raw_error_summary": _redact_secret_text(error_summary),
        "choices_type": type(choices).__name__ if choices is not None else "missing",
        "choices_len": len(choices) if isinstance(choices, list) else 0,
        "first_choice_keys": sorted(first_choice.keys()) if isinstance(first_choice, dict) else [],
        "message_keys": sorted(message.keys()) if isinstance(message, dict) else [],
        "content_type": type(content).__name__ if content is not None else "missing",
        "content_length": len(content) if isinstance(content, str) else 0,
        "empty_content": True,
    }
    if request_context:
        diagnostic.update(request_context)
    return diagnostic


def _omlx_raw_error_code(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or error.get("omlx_code") or "")
    return ""


def _omlx_raw_error_code_from_text(text: str) -> str:
    value = str(text or "")
    for key in ("prefill_memory_exceeded", "invalid_request_error"):
        if key in value:
            return key
    return ""


def _write_omlx_stage_diagnostic(stage: StageSpec, executor: TaskEngineExecutor, *, base_dir: str | Path) -> Path | None:
    diagnostics = getattr(executor, "last_omlx_diagnostics", None)
    if not isinstance(diagnostics, dict):
        return None
    data = diagnostics.get(stage.stage_name)
    if not isinstance(data, dict):
        return None
    stage_dir = Path(base_dir) / stage.stage_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / f"{stage.stage_name}.diagnostic.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _extract_chat_content(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
            if isinstance(first.get("text"), str):
                return first["text"]
    if isinstance(data.get("content"), str):
        return data["content"]
    return ""


def _agy_timeout_for_stage(stage: StageSpec) -> int:
    if stage.stage_name == "L1_gemini_search":
        return 600
    if stage.stage_name == "L4_gemini_audit":
        return 600
    if stage.stage_name == "intelligence_layer":
        return 360
    if stage.stage_name == "external_calibration":
        return 600
    return 240


def _agy_subprocess_cwd() -> str:
    """Return a stable non-hidden cwd for AGY subprocesses.

    WebUI often launches Hermes from ~/.hermes/hermes-agent. AGY/Antigravity
    treats hidden project roots differently, which can destabilize keychain and
    project URI handling. Artifacts still stay in the task run directory; only
    the AGY process cwd is moved to a visible, stable location.
    """
    raw_override = os.getenv("HERMES_AGY_CWD", "").strip()
    candidates: list[Path] = []
    if raw_override:
        candidates.append(Path(raw_override).expanduser())
    candidates.extend([AGY_STABLE_CWD_DEFAULT, Path("/private/tmp")])
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_absolute() or not resolved.exists():
            continue
        if any(part == ".hermes" for part in resolved.parts):
            continue
        return str(resolved)
    return "/private/tmp"


def _agy_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("GEMINI_DIR", "AGY_GEMINI_DIR", "GOOGLE_GEMINI_DIR"):
        value = env.get(key)
        if not value:
            continue
        expanded = Path(value).expanduser()
        if not expanded.is_absolute():
            env[key] = str((Path.home() / expanded).resolve())
    return env


def _agy_gemini_dir_is_absolute(env: dict[str, str]) -> bool | None:
    value = env.get("GEMINI_DIR")
    if not value:
        return None
    return Path(value).expanduser().is_absolute()


def _agy_preflight_result(
    status: str,
    *,
    command: list[str],
    elapsed: float,
    stdout: str,
    stderr: str,
    models: list[str],
    missing_models: list[str] | None = None,
    agy_cwd: str = "",
    gemini_dir_absolute: bool | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "blocked_stage": "" if status == "AGY_OK" else "agy_preflight",
        "blocked_reason": "" if status == "AGY_OK" else status,
        "command": command,
        "elapsed_seconds": round(elapsed, 2),
        "stdout_len": len(stdout or ""),
        "stdout_tail": _tail_text(stdout),
        "stderr_tail": _tail_text(stderr),
        "models": models,
        "required_models": list(AGY_PREFLIGHT_REQUIRED_MODELS),
        "missing_models": missing_models or [],
        "agy_cwd": agy_cwd,
        "gemini_dir_absolute": gemini_dir_absolute,
        "authorization_code_note": (
            "" if status == "AGY_OK" else "authorization code must be entered by user manually"
        ),
    }


def _agy_preflight_blocked(
    reason: str,
    *,
    command: list[str],
    elapsed: float,
    stdout: str,
    stderr: str,
    models: list[str],
    missing_models: list[str] | None = None,
    agy_cwd: str = "",
    gemini_dir_absolute: bool | None = None,
) -> dict[str, Any]:
    result = _agy_preflight_result(
        reason,
        command=command,
        elapsed=elapsed,
        stdout=stdout,
        stderr=stderr,
        models=models,
        missing_models=missing_models,
        agy_cwd=agy_cwd,
        gemini_dir_absolute=gemini_dir_absolute,
    )
    result["status"] = "BLOCKED_STATUS"
    result["blocked_reason"] = reason
    return result


def _classify_agy_preflight_block(stdout: str, stderr: str) -> str:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    lowered = combined.lower()
    if "authentication timed out" in lowered or ("silent auth" in lowered and "timed out" in lowered):
        return "AGY_AUTH_TIMEOUT"
    if _agy_timeout_response(combined):
        if _agy_printmode_timeout_after_auth_success(combined, ""):
            return AGY_PRINTMODE_TIMEOUT_AFTER_AUTH_SUCCESS
        if _agy_printmode_timeout_auth_uncertain(combined):
            return AGY_PRINTMODE_TIMEOUT_AUTH_UNCERTAIN
        return AGY_TIMEOUT_BLOCKED
    if _agy_keychain_false_negative(combined):
        return AGY_KEYCHAIN_FALSE_NEGATIVE
    if "authorization code" in lowered or "verification code" in lowered or "oauth" in lowered or "browser" in lowered:
        return "AGY_AUTH_REQUIRES_USER"
    if "not logged" in lowered or "not authenticated" in lowered or "login" in lowered or "authorize" in lowered:
        return "AGY_AUTH_REQUIRES_USER"
    return "AGY_AUTH_REQUIRES_USER"


def _agy_keychain_false_negative(output: str) -> bool:
    lowered = (output or "").lower()
    auth_negative = (
        "you are not logged into antigravity" in lowered
        or "not logged into antigravity" in lowered
        or "not authenticated" in lowered
    )
    auth_success = (
        "authenticated via keyring" in lowered
        or "oauth: authenticated successfully" in lowered
        or "oauth authenticated successfully" in lowered
        or "silent auth succeeded" in lowered
    )
    return auth_negative and auth_success and not _agy_timeout_response(output)


def _agy_auth_success(output: str) -> bool:
    lowered = (output or "").lower()
    return (
        "authenticated via keyring" in lowered
        or "oauth: authenticated successfully" in lowered
        or "oauth authenticated successfully" in lowered
        or "silent auth succeeded" in lowered
    )


def _agy_auth_negative(output: str) -> bool:
    lowered = (output or "").lower()
    return (
        "you are not logged into antigravity" in lowered
        or "not logged into antigravity" in lowered
        or "not authenticated" in lowered
    )


def _agy_timeout_response(output: str) -> bool:
    lowered = (output or "").lower()
    return "error: timed out waiting for response" in lowered or "print mode: timed out" in lowered


def _agy_printmode_timeout_after_auth_success(output: str, actual_model: str) -> bool:
    lowered = (output or "").lower()
    actual = actual_model.strip().lower()
    auth_success = _agy_auth_success(output)
    model_override = (
        f"resolving model {actual}" in lowered
        or f'propagating selected model override to backend: label="{actual}"' in lowered
        or (not actual and "propagating selected model override" in lowered)
    )
    return (
        auth_success
        and model_override
        and "streamgeneratecontent" in lowered
        and "print mode: timed out" in lowered
    )


def _agy_printmode_timeout_auth_uncertain(output: str) -> bool:
    return _agy_timeout_response(output) and _agy_auth_negative(output) and not _agy_auth_success(output)


def _agy_timeout_blocker_reason(output: str, actual_model: str, *, attempt: int) -> str:
    if _agy_printmode_timeout_after_auth_success(output, actual_model):
        return AGY_PRINTMODE_TIMEOUT_AFTER_AUTH_SUCCESS
    if _agy_printmode_timeout_auth_uncertain(output):
        return AGY_PRINTMODE_TIMEOUT_AUTH_UNCERTAIN
    return AGY_TIMEOUT_RESPONSE if attempt == 0 else AGY_TIMEOUT_BLOCKED


def _parse_agy_models(stdout: str) -> list[str]:
    models: list[str] = []
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cleaned = line.lstrip("-*•0123456789. ").strip()
        if cleaned:
            models.append(cleaned)
    return models


def _tail_text(value: str, *, limit: int = 2000) -> str:
    return (value or "")[-limit:]


def _settings_agy_model() -> str:
    path = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    model = data.get("model")
    return str(model).strip() if isinstance(model, str) else ""


def _env_file_agy_model(env_key: str) -> str:
    path = Path(os.getenv("HERMES_AGY_MODEL_ALIAS_ENV", "work/agy_model_alias.env"))
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    prefix = f"{env_key}="
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("export "):
            stripped = stripped[len("export "):]
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip().strip('"').strip("'")
    return ""


def _agy_model_alias_failed(output: str, actual_model: str) -> bool:
    lowered = output.lower()
    actual = actual_model.strip().lower()
    if actual == "ccpa":
        return True
    resolved_actual = (
        f"resolving model {actual}" in lowered
        or f'propagating selected model override to backend: label="{actual}"' in lowered
    )
    defaulted_ccpa = (
        "not in local config" in lowered
        or "defaulting to ccpa" in lowered
        or ("model resolved via default" in lowered and "ccpa" in lowered)
    )
    return defaulted_ccpa and not resolved_actual


def _format_agy_failure(
    *,
    stage: StageSpec,
    command: list[str],
    canonical_model: str,
    actual_model: str,
    log_file: Path,
    stdout: str,
    stderr: str,
    log_text: str,
    elapsed: float,
    agy_cwd: str,
    reason: str,
) -> str:
    key_lines = _agy_key_lines(stdout, stderr, log_text)
    return (
        f"{stage.stage_name}: AGY_CALL_BLOCKED\n"
        f"reason={reason}\n"
        f"canonical_model={canonical_model!r}\n"
        f"actual_model={actual_model!r}\n"
        f"log_file={str(log_file)!r}\n"
        f"agy_cwd={agy_cwd!r}\n"
        f"elapsed_seconds={elapsed:.1f}\n"
        f"command={json.dumps(command, ensure_ascii=False)}\n"
        f"key_lines={json.dumps(key_lines, ensure_ascii=False)}"
    )


def _agy_key_lines(stdout: str, stderr: str, log_text: str) -> list[str]:
    interesting = (
        "not in local config",
        "defaulting to ccpa",
        "model resolved",
        "resolving model",
        "propagating selected model",
        "authenticated via keyring",
        "oauth: authenticated successfully",
        "oauth authenticated successfully",
        "silent auth succeeded",
        "print mode",
        "error",
        "failed",
        "timeout",
        "operation not permitted",
    )
    lines: list[str] = []
    for label, text in (("stdout", stdout), ("stderr", stderr), ("log", log_text)):
        for line in (text or "").splitlines():
            lowered = line.lower()
            if any(token in lowered for token in interesting):
                lines.append(f"{label}: {line}"[:1000])
            if len(lines) >= 24:
                return lines
    if stdout.strip():
        lines.append(f"stdout: {stdout.strip()[:1000]}")
    if stderr.strip():
        lines.append(f"stderr: {stderr.strip()[:1000]}")
    if log_text.strip():
        lines.append(f"log: {log_text.strip()[:1000]}")
    return lines[:24]


def _decode_timeout_part(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = [
    "GEMMA431B_ACTUAL_MODEL_DEFAULT",
    "LLAMA70B_ACTUAL_MODEL_DEFAULT",
    "LocalTaskEngineExecutor",
    "NEMOTRON120B_ACTUAL_MODEL_DEFAULT",
    "QWEN72B_ACTUAL_MODEL_DEFAULT",
    "R1_ACTUAL_MODEL_DEFAULT",
    "TaskEngineExecutor",
    "resolve_gemma431b_omlx_model_alias",
    "resolve_llama70b_omlx_model_alias",
    "resolve_nemotron120b_omlx_model_alias",
    "resolve_agy_model_alias",
    "resolve_qwen72b_omlx_model_alias",
    "resolve_r1_omlx_model_alias",
    "run_agy_preflight",
    "run_decision_final_smoke",
    "run_research_decision_alternative_generator_smoke",
    "run_research_decision_evidence_judge_smoke",
    "run_research_decision_external_calibration_smoke",
    "run_research_decision_final_controller_smoke",
    "run_research_decision_intelligence_smoke",
    "run_research_decision_insight_harvester_smoke",
    "run_research_decision_convergence_smoke",
    "run_research_decision_l1_l10_smoke",
    "run_research_decision_l1_l11_smoke",
    "run_research_decision_l1_l12_smoke",
    "run_research_decision_l1_l13_smoke",
    "run_research_decision_l1_l14_smoke",
    "run_research_decision_l1_l15_smoke",
    "run_research_decision_l1_l16_smoke",
    "run_research_decision_l1_l7_smoke",
    "run_research_decision_l1_l8_smoke",
    "run_research_decision_l1_l9_smoke",
    "run_research_decision_premise_auditor_smoke",
    "run_research_decision_structure_mapper_smoke",
    "run_research_decision_supplementary_search_smoke",
    "run_research_l2_5_codex_handoff_smoke",
    "run_research_l1_l2_smoke",
    "run_research_l1_l3_smoke",
    "run_research_l1_l4_smoke",
    "run_research_l1_l5_smoke",
    "run_research_l3_synthesis_smoke",
    "run_research_l4_gemini_audit_smoke",
    "run_research_l5_acceptance_smoke",
    "run_simulated_pipeline",
]
