"""Live Hermes wrapper for the Research/Decision task engine runner.

The WebUI bridge loads tools from the configured hermes-agent ``--agent-root``.
This file is therefore intentionally a bounded delegation wrapper: it preserves
Hermes' local registry/schema compatibility while verifying and delegating the
actual Research/Decision runner implementation to the RD repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.registry import registry

RD_REPO = Path(
    os.getenv(
        "HERMES_RESEARCH_DECISION_REPO",
        "/Users/xqdwww/Workspace/AI_Core/hermes-agent-research-decision",
    )
).expanduser().resolve()
RD_RUNNER_RELATIVE_PATH = Path("tools/task_engine_runner.py")
EXPECTED_RD_HEAD = os.getenv(
    "HERMES_RESEARCH_DECISION_EXPECTED_HEAD",
    "7a58d875efc8be2528d922ff5727000f9da825e6",
)
EXPECTED_RD_RUNNER_SHA256 = os.getenv(
    "HERMES_RESEARCH_DECISION_EXPECTED_RUNNER_SHA256",
    "1082c019a9b53f500caa1093ca985dcd89d6d9f48d7decea2b3c4ca596e91d76",
)
WRAPPER_STRATEGY = "bounded_delegation_wrapper_to_rd_repo_runner"

DIRECT_LEGACY_RESEARCH_DECISION_FULL = "research_decision_combined_full_requires_fresh_two_stage_production_path"
TERMINOLOGY_LEAKAGE = "TERMINOLOGY_LEAKAGE"
TASK_ENGINE_RUNNER_ENTRYPOINT = "task_engine_runner"
TASK_ENGINE_RUNNER_MODULE = "tools.task_engine_runner"
TASK_ENGINE_RUNNER_SOURCE = "tools/task_engine_runner.py"
LEGACY_RESEARCH_DECISION_BANNED_TERMS = (
    "RESEARCH_DECISION 16-stage smoke",
    "完整 RESEARCH_DECISION 16-stage",
    "direct RESEARCH_DECISION full",
    "archived 16-stage full",
    "legacy full",
    "16-stage smoke",
)
LEGACY_RESEARCH_DECISION_ALLOWED_TERMS = (
    "stage_count: 16",
    "L1-L14 + external_calibration + final_controller",
    "two-step E2E validation",
    "RESEARCH full + DECISION full",
    "current-run validation",
)
LEGACY_RESEARCH_DECISION_AUDIT_CONTEXTS = {"legacy_term_audit", "banned_term_check", "test_assertion"}
TASK_ENGINE_RUNNER_SIDECAR_STAGES = [
    "status_only",
    "source_registry_gate",
    "fulltext_handoff_gate",
    "evidence_packet_gate",
    "final_traceability_gate",
    "advisory_report_gate",
]

_ALLOWED_ARGS = {
    "query",
    "mode",
    "action",
    "run",
    "base_dir",
    "artifact_dir",
    "research_packet_path",
    "allow_archived_research_decision",
    "execution_intent",
    "explicit_smoke_intent",
    "passive_guard_debug",
    "emit_topic_refinement_advisory",
    "topic_refinement_advisory_output_dir",
    "topic_refinement_advisory_strict",
    "emit_evidence_backed_sidecar",
    "evidence_backed_sidecar_stage",
    "dry_run",
}

TASK_ENGINE_RUNNER_SCHEMA = {
    "name": "task_engine_runner",
    "description": (
        "Hermes RESEARCH/DECISION task engine entrypoint. The live agent-root "
        "tool is an audited wrapper that verifies and delegates to the current "
        "hermes-agent-research-decision repo runner."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {"type": "string", "description": "Original user request."},
            "mode": {
                "type": "string",
                "enum": ["RESEARCH", "DECISION", "RESEARCH_DECISION", "AUTO"],
                "default": "AUTO",
            },
            "action": {
                "type": "string",
                "enum": [
                    "contract",
                    "status",
                    "mechanism-check",
                    "agy-preflight",
                    "omlx-preflight",
                    "full",
                    "dry-run",
                    "simulated-run",
                    "validate",
                    "render",
                    "smoke-decision-final",
                    "smoke-research-l1-l2",
                    "smoke-research-l1-l3",
                    "smoke-research-l1-l4",
                    "smoke-research-l1-l5",
                    "smoke-research-decision-intelligence",
                    "smoke-research-decision-d1",
                    "smoke-research-decision-search",
                    "smoke-research-decision-d2",
                    "smoke-research-decision-structure",
                    "smoke-research-decision-d3",
                    "smoke-research-decision-evidence",
                    "smoke-research-decision-d4",
                    "smoke-research-decision-premise",
                    "smoke-research-decision-d5",
                    "smoke-research-decision-alternative",
                    "smoke-research-decision-d6",
                    "smoke-research-decision-insight",
                    "smoke-research-decision-d7",
                    "smoke-research-decision-convergence",
                    "smoke-research-decision-d8",
                    "smoke-research-decision-calibration",
                    "smoke-research-decision-d9",
                    "smoke-research-decision-final",
                    "smoke-research-decision-d10",
                ],
                "default": "contract",
            },
            "run": {"type": "object"},
            "base_dir": {"type": "string"},
            "artifact_dir": {"type": "string"},
            "research_packet_path": {"type": "string"},
            "allow_archived_research_decision": {"type": "boolean", "default": False},
            "execution_intent": {
                "type": "string",
                "enum": [
                    "production",
                    "production_full",
                    "fresh_two_stage",
                    "integration_smoke",
                    "explicit_smoke",
                    "archived_test",
                    "mechanism_test",
                    "dry_run",
                ],
            },
            "explicit_smoke_intent": {"type": "boolean", "default": False},
            "passive_guard_debug": {"type": "boolean", "default": False},
            "emit_topic_refinement_advisory": {"type": "boolean", "default": False},
            "topic_refinement_advisory_output_dir": {"type": "string"},
            "topic_refinement_advisory_strict": {"type": "boolean", "default": True},
            "emit_evidence_backed_sidecar": {"type": "boolean", "default": False},
            "evidence_backed_sidecar_stage": {
                "type": "string",
                "enum": TASK_ENGINE_RUNNER_SIDECAR_STAGES,
                "default": "status_only",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Compatibility alias: when true and action is omitted/default, run action='dry-run'.",
                "default": False,
            },
        },
        "required": ["query"],
    },
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_git_head() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=RD_REPO,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _runner_python() -> str:
    configured = os.getenv("HERMES_RESEARCH_DECISION_RUNNER_PYTHON", "").strip()
    if configured:
        return configured
    venv_python = RD_REPO / ".venv" / "bin" / "python"
    if venv_python.exists() and os.access(venv_python, os.X_OK):
        return str(venv_python)
    return "python"


def _source_metadata(verified: bool, error: str | None = None) -> dict[str, Any]:
    runner = RD_REPO / RD_RUNNER_RELATIVE_PATH
    actual_hash = _sha256(runner) if runner.exists() else None
    actual_head = _run_git_head() if RD_REPO.exists() else None
    return {
        "strategy": WRAPPER_STRATEGY,
        "wrapper_path": str(Path(__file__).resolve()),
        "rd_repo": str(RD_REPO),
        "rd_runner_path": str(runner),
        "rd_head": actual_head,
        "expected_rd_head": EXPECTED_RD_HEAD,
        "rd_runner_hash": actual_hash,
        "expected_rd_runner_hash": EXPECTED_RD_RUNNER_SHA256,
        "verified": verified,
        "error": error,
    }


def _verify_rd_source() -> tuple[bool, str | None, dict[str, Any]]:
    runner = RD_REPO / RD_RUNNER_RELATIVE_PATH
    if not RD_REPO.exists():
        return False, "rd_repo_missing", _source_metadata(False, "rd_repo_missing")
    if not runner.exists():
        return False, "rd_runner_missing", _source_metadata(False, "rd_runner_missing")
    actual_head = _run_git_head()
    if actual_head != EXPECTED_RD_HEAD:
        return False, "rd_head_mismatch", _source_metadata(False, "rd_head_mismatch")
    actual_hash = _sha256(runner)
    if actual_hash != EXPECTED_RD_RUNNER_SHA256:
        return False, "rd_runner_hash_mismatch", _source_metadata(False, "rd_runner_hash_mismatch")
    return True, None, _source_metadata(True)


def _coerce_task_engine_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _task_engine_validation_error(*, unknown_args: list[str] | None = None, message: str = "invalid task_engine_runner arguments") -> str:
    return json.dumps(
        {
            "status": "validation_error",
            "blocked_stage": "tool_schema_validation",
            "blocked_reason": "unknown_or_invalid_task_engine_runner_args",
            "message": message,
            "unknown_args": unknown_args or [],
            "allowed_args": sorted(_ALLOWED_ARGS),
            "selected_entrypoint": TASK_ENGINE_RUNNER_ENTRYPOINT,
            "schema_empty_blocker": False,
            "no_real_executor_called": True,
            "loaded_source": _source_metadata(False, "argument_validation_failed"),
        },
        ensure_ascii=False,
        indent=2,
    )


def _normalize_task_engine_handler_args(args: dict[str, Any]) -> dict[str, Any] | str:
    if not isinstance(args, dict):
        return _task_engine_validation_error(message="task_engine_runner arguments must be an object")
    unknown = sorted(set(args) - _ALLOWED_ARGS)
    if unknown:
        return _task_engine_validation_error(unknown_args=unknown)

    normalized = dict(args)
    if not normalized.get("base_dir") and normalized.get("artifact_dir"):
        normalized["base_dir"] = normalized.get("artifact_dir")

    if _coerce_task_engine_bool(normalized.get("dry_run"), default=False):
        action_supplied = "action" in normalized and str(normalized.get("action") or "").strip()
        current_action = str(normalized.get("action") or "contract").strip().lower().replace("_", "-")
        if not action_supplied or current_action == "contract":
            normalized["action"] = "dry-run"
    normalized.pop("dry_run", None)
    return normalized


def audit_legacy_research_decision_terms(value: Any, *, context: str = "normal") -> list[dict[str, str]]:
    if context in LEGACY_RESEARCH_DECISION_AUDIT_CONTEXTS:
        return []
    violations: list[dict[str, str]] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if key_text in LEGACY_RESEARCH_DECISION_AUDIT_CONTEXTS:
                    continue
                visit(child, child_path)
            return
        if isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
            return
        if not isinstance(item, str):
            return
        lowered = item.lower()
        for term in LEGACY_RESEARCH_DECISION_BANNED_TERMS:
            if term.lower() in lowered:
                violations.append({"term": term, "path": path, "context": item[:300]})

    visit(value, "")
    return violations


def apply_legacy_research_decision_term_guard(payload: dict[str, Any], *, context: str = "normal") -> dict[str, Any]:
    violations = audit_legacy_research_decision_terms(payload, context=context)
    if not violations:
        return payload
    guarded = dict(payload)
    guarded["status"] = TERMINOLOGY_LEAKAGE
    guarded["pipeline_status"] = "PIPELINE_BLOCKED"
    guarded["blocked_stage"] = "legacy_research_decision_terminology"
    guarded["blocked_reason"] = TERMINOLOGY_LEAKAGE
    guarded["legacy_term_audit"] = {"violations": violations}
    return guarded


def _blocked(reason: str, *, stage: str = "RD_RUNNER_SOURCE_RESOLUTION", metadata: dict[str, Any] | None = None) -> str:
    payload = {
        "status": "blocked",
        "pipeline_status": "PIPELINE_BLOCKED",
        "blocked_stage": stage,
        "blocked_reason": reason,
        "artifact_dir": "",
        "loaded_source": metadata or _source_metadata(False, reason),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _attach_metadata(raw: str, metadata: dict[str, Any]) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"status": "ok", "raw_result": raw}
    if isinstance(payload, dict):
        payload["loaded_source"] = metadata
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return json.dumps({"status": "ok", "result": payload, "loaded_source": metadata}, ensure_ascii=False, indent=2)


def _local_status(*, mode: str, metadata: dict[str, Any]) -> str:
    return json.dumps(
        {
            "status": "ok",
            "selected_entrypoint": TASK_ENGINE_RUNNER_ENTRYPOINT,
            "entrypoint_module": TASK_ENGINE_RUNNER_MODULE,
            "entrypoint_source": TASK_ENGINE_RUNNER_SOURCE,
            "mode": mode,
            "schema_non_empty": True,
            "sidecar_default_off": True,
            "main_result_contract_changed_by_sidecar": False,
            "no_real_executor_called": True,
            "loaded_source": metadata,
        },
        ensure_ascii=False,
        indent=2,
    )


def _local_mechanism_check(*, mode: str, base_dir: str | None, metadata: dict[str, Any]) -> str:
    return json.dumps(
        {
            "status": "ok",
            "selected_entrypoint": TASK_ENGINE_RUNNER_ENTRYPOINT,
            "entrypoint_module": TASK_ENGINE_RUNNER_MODULE,
            "entrypoint_source": TASK_ENGINE_RUNNER_SOURCE,
            "mode": mode,
            "action": "mechanism-check",
            "artifact_dir": str(Path(base_dir).resolve()) if base_dir else "",
            "schema_non_empty": True,
            "dispatch_payload_valid": True,
            "sidecar_default_off": True,
            "main_result_contract_changed_by_sidecar": False,
            "no_real_executor_called": True,
            "loaded_source": metadata,
        },
        ensure_ascii=False,
        indent=2,
    )


def _local_omlx_preflight() -> str:
    from tools.task_engine_executors import run_omlx_preflight

    return json.dumps(run_omlx_preflight(), ensure_ascii=False, indent=2)


def _archived_full_block(*, mode: str, base_dir: str | None, sidecar_requested: bool, sidecar_stage: str, metadata: dict[str, Any]) -> str:
    return json.dumps(
        {
            "status": "blocked",
            "BLOCKED_STATUS": "PIPELINE_BLOCKED",
            "pipeline_status": "PIPELINE_BLOCKED",
            "blocked_stage": "research_decision_archived",
            "blocked_reason": DIRECT_LEGACY_RESEARCH_DECISION_FULL,
            "entrypoint_guard": DIRECT_LEGACY_RESEARCH_DECISION_FULL,
            "selected_entrypoint": TASK_ENGINE_RUNNER_ENTRYPOINT,
            "artifact_dir": str(Path(base_dir).resolve()) if base_dir else "",
            "mode": mode,
            "two_step_recommendation": [
                "RESEARCH full -> research_evidence_packet.md",
                "DECISION full with research_packet_path=<path to research_evidence_packet.md>",
            ],
            "allow_override": {
                "function_arg": "allow_archived_research_decision=True",
                "execution_intent": "archived_test",
            },
            "sidecar_policy": {
                "evidence_backed_sidecar_default": False,
                "evidence_backed_sidecar_requested": sidecar_requested,
                "evidence_backed_sidecar_stage": sidecar_stage,
                "main_result_contract_changed_by_sidecar": False,
            },
            "loaded_source": metadata,
        },
        ensure_ascii=False,
        indent=2,
    )


def _query_requests_latest_research_packet(query: str) -> bool:
    text = (query or "").lower()
    patterns = (
        "最新研究成果包",
        "最新的研究成果包",
        "基于最新研究成果包",
        "使用最新研究成果包",
        "研究成果包=最新",
        "研究成果包 = 最新",
        "研究成果包=latest",
        "研究成果包 = latest",
        "latest research packet",
        "research_packet=latest",
        "research packet=latest",
    )
    return any(pattern in text for pattern in patterns)


def _extract_research_packet_path(query: str) -> str | None:
    match = re.search(r"研究成果包[：:]\s*([^\s，。；;]+)", query or "")
    if not match:
        return None
    return match.group(1).strip()


def _candidate_research_roots(base_dir: str | Path | None) -> list[Path]:
    roots: list[Path] = []
    env_root = os.getenv("HERMES_TASK_ENGINE_ARTIFACT_DIR", "").strip()
    if env_root:
        roots.append(Path(env_root).expanduser())
    if base_dir:
        base = Path(base_dir).expanduser()
        roots.extend([base, base.parent])
    roots.append(Path.cwd())
    deduped: list[Path] = []
    for root in roots:
        resolved = root.resolve()
        if resolved not in deduped:
            deduped.append(resolved)
    return deduped


def _is_valid_latest_research_packet(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    required = (
        "verdict: accepted",
        "accepted: true",
        "evidence_packet_ready_for_decision: true",
        "## evidence_strength",
        "## controversy",
        "## evidence_gap",
        "## evidence_supported",
        "## reasonable_inference",
        "## foresight_hypothesis",
    )
    return all(token in text for token in required)


def _find_latest_research_packet(base_dir: str | Path | None) -> Path | None:
    candidates: list[Path] = []
    for root in _candidate_research_roots(base_dir):
        if not root.exists():
            continue
        candidates.extend(path for path in root.rglob("research_evidence_packet.md") if _is_valid_latest_research_packet(path))
    if not candidates:
        return None
    candidates.sort(key=lambda path: (path.stat().st_mtime_ns, str(path.resolve())), reverse=True)
    return candidates[0].resolve()


def run_decision_final_smoke(
    query: str,
    *,
    base_dir: str | Path,
    research_packet_path: str | Path | None = None,
) -> dict[str, Any]:
    from tools.task_engine_executors import run_decision_final_smoke as _run_decision_final_smoke

    return _run_decision_final_smoke(query, base_dir=base_dir, research_packet_path=research_packet_path)


def _local_decision_final_smoke(kwargs: dict[str, Any]) -> str:
    query = str(kwargs.get("query") or "")
    base_dir = kwargs.get("base_dir") or kwargs.get("artifact_dir") or "outputs/task_engine_runner"
    research_packet_path = kwargs.get("research_packet_path") or _extract_research_packet_path(query)
    if not research_packet_path and _query_requests_latest_research_packet(query):
        latest = _find_latest_research_packet(base_dir)
        if latest is None:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "blocked_stage": "research_packet_discovery",
                    "blocked_reason": "no_valid_new_research_packet_found",
                    "artifact_dir": str(Path(base_dir).resolve()),
                },
                ensure_ascii=False,
                indent=2,
            )
        research_packet_path = str(latest)
    if research_packet_path:
        result = run_decision_final_smoke(query, base_dir=base_dir, research_packet_path=research_packet_path)
    else:
        result = run_decision_final_smoke(query, base_dir=base_dir)
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        result.setdefault("artifact_dir", str(Path(base_dir).resolve()))
    return json.dumps(result, ensure_ascii=False, indent=2)


def _inject_passive_guard_debug(json_str: str, query: str, passive_guard_debug: bool) -> str:
    """Inject passive-guard diagnostic fields when debug is opt-in.

    Returns the original json_str unchanged when debug is disabled or when
    the payload cannot be parsed, so default contracts are never affected.
    """
    if not passive_guard_debug:
        return json_str
    try:
        payload = json.loads(json_str)
    except json.JSONDecodeError:
        return json_str
    if not isinstance(payload, dict):
        return json_str
    from tools.passive_intelligence_guard import classify_skill_triggers

    payload["passive_intelligence_guard"] = {
        "skill_triggers": classify_skill_triggers(query),
        "production_behavior_change": False,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def task_engine_runner(**kwargs: Any) -> str:
    normalized = _normalize_task_engine_handler_args(kwargs)
    if isinstance(normalized, str):
        return normalized
    kwargs = normalized

    passive_guard_debug = kwargs.pop("passive_guard_debug", False)

    action = str(kwargs.get("action") or "contract").strip().lower().replace("_", "-")
    mode = str(kwargs.get("mode") or "AUTO").strip().upper().replace("-", "_")

    verified, reason, metadata = _verify_rd_source()
    if action == "status":
        return _inject_passive_guard_debug(_local_status(mode=mode, metadata=metadata), kwargs.get("query", ""), passive_guard_debug)
    if action == "mechanism-check":
        return _inject_passive_guard_debug(_local_mechanism_check(mode=mode, base_dir=kwargs.get("base_dir"), metadata=metadata), kwargs.get("query", ""), passive_guard_debug)
    if action == "omlx-preflight":
        return _inject_passive_guard_debug(_local_omlx_preflight(), kwargs.get("query", ""), passive_guard_debug)
    if action == "full" and mode == "RESEARCH_DECISION" and not _coerce_task_engine_bool(kwargs.get("allow_archived_research_decision"), default=False):
        return _inject_passive_guard_debug(
            _archived_full_block(
                mode=mode,
                base_dir=kwargs.get("base_dir"),
                sidecar_requested=_coerce_task_engine_bool(kwargs.get("emit_evidence_backed_sidecar"), default=False),
                sidecar_stage=str(kwargs.get("evidence_backed_sidecar_stage") or "status_only"),
                metadata=metadata,
            ),
            kwargs.get("query", ""),
            passive_guard_debug,
        )
    if action == "smoke-decision-final":
        return _inject_passive_guard_debug(_local_decision_final_smoke(kwargs), kwargs.get("query", ""), passive_guard_debug)
    if not verified:
        return _inject_passive_guard_debug(_blocked(str(reason), metadata=metadata), kwargs.get("query", ""), passive_guard_debug)

    script = """\
import json
import os
import sys
from pathlib import Path
repo = Path(os.environ["HERMES_RD_REPO"]).resolve()
sys.path.insert(0, str(repo))
from tools.task_engine_runner import task_engine_runner
payload = json.loads(sys.stdin.read() or "{}")
result = task_engine_runner(**payload)
if not isinstance(result, str):
    result = json.dumps(result, ensure_ascii=False)
sys.stdout.write(result)
""".strip()

    env = dict(os.environ)
    env["HERMES_RD_REPO"] = str(RD_REPO)
    timeout_s = int(os.getenv("HERMES_RESEARCH_DECISION_RUNNER_TIMEOUT_SECONDS", "7200"))
    query = kwargs.get("query", "")
    try:
        proc = subprocess.run(
            [_runner_python(), "-c", script],
            cwd=RD_REPO,
            env=env,
            input=json.dumps(kwargs, ensure_ascii=False),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return _inject_passive_guard_debug(_blocked("rd_runner_delegate_timeout", stage="RD_RUNNER_DELEGATE", metadata=metadata), query, passive_guard_debug)
    except Exception as exc:
        return _inject_passive_guard_debug(_blocked(f"rd_runner_delegate_error:{type(exc).__name__}", stage="RD_RUNNER_DELEGATE", metadata=metadata), query, passive_guard_debug)

    if proc.returncode != 0:
        fail_meta = dict(metadata)
        fail_meta["delegate_returncode"] = proc.returncode
        fail_meta["delegate_stderr_tail"] = (proc.stderr or "")[-4000:]
        return _inject_passive_guard_debug(_blocked("rd_runner_delegate_failed", stage="RD_RUNNER_DELEGATE", metadata=fail_meta), query, passive_guard_debug)

    return _inject_passive_guard_debug(_attach_metadata(proc.stdout, metadata), query, passive_guard_debug)


def _task_engine_handler(args: dict[str, Any], **kw: Any) -> str:
    normalized = _normalize_task_engine_handler_args(args or {})
    if isinstance(normalized, str):
        return normalized
    return task_engine_runner(**normalized)


def _check_task_engine_requirements() -> bool:
    verified, _reason, _metadata = _verify_rd_source()
    return verified


def _delegate_stub(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("task_engine_runner live wrapper does not expose local executor internals")


run_research_l1_l5_smoke = _delegate_stub
run_research_decision_l1_l16_smoke = _delegate_stub
run_research_decision_l1_l15_smoke = _delegate_stub
run_research_decision_l1_l14_smoke = _delegate_stub

registry.register(
    name="task_engine_runner",
    toolset="research",
    schema=TASK_ENGINE_RUNNER_SCHEMA,
    handler=_task_engine_handler,
    check_fn=_check_task_engine_requirements,
    emoji="🧭",
    description="Live wrapper delegating task_engine_runner to the verified Research/Decision repo runner.",
)


__all__ = [
    "TASK_ENGINE_RUNNER_SCHEMA",
    "LEGACY_RESEARCH_DECISION_BANNED_TERMS",
    "LEGACY_RESEARCH_DECISION_ALLOWED_TERMS",
    "DIRECT_LEGACY_RESEARCH_DECISION_FULL",
    "TERMINOLOGY_LEAKAGE",
    "apply_legacy_research_decision_term_guard",
    "audit_legacy_research_decision_terms",
    "run_decision_final_smoke",
    "task_engine_runner",
]
