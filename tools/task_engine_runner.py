"""Hermes task-engine entrypoint for research and decision pipelines."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tools.registry import registry
from tools.task_engine_contracts import (
    CANONICAL_STAGES,
    ENGINE_DECISION,
    ENGINE_RESEARCH,
    ENGINE_RESEARCH_DECISION,
    PIPELINE_BLOCKED,
    build_dry_run_plan,
    build_engine_contract,
    canonical_schema,
    detect_task_engine_mode,
    make_stage_record,
    planned_outputs,
    render_final_markdown,
    normalize_mode,
    validate_pipeline,
)
from tools.passive_intelligence_guard import (
    build_document_validation_observer_plan,
    build_document_validation_warning,
    build_final_report_consistency_warnings,
    build_long_run_observer_plan,
    build_passive_runtime_ledger,
    check_final_report_consistency,
    classify_action_permission,
    classify_ledger_completion_state,
    classify_document_validation_requirements,
    classify_long_run_event,
    classify_pdf_validation_result,
    classify_skill_triggers,
    coerce_passive_runtime_ledger,
    get_stage_timeout_policy,
    initialize_status_ledger,
    ledger_to_final_report_warnings,
    safe_document_validation_summary,
    safe_long_run_status_summary,
    summarize_document_validation_plan,
    summarize_long_run_observer_plan,
    summarize_passive_runtime_ledger,
)
from tools.task_engine_executors import (
    _research_evidence_packet_quality_error,
    run_decision_final_smoke,
    run_agy_preflight,
    run_omlx_preflight,
    run_research_decision_l1_l16_smoke,
    run_research_decision_l1_l15_smoke,
    run_research_decision_l1_l14_smoke,
    run_research_decision_l1_l10_smoke,
    run_research_decision_l1_l11_smoke,
    run_research_decision_l1_l12_smoke,
    run_research_decision_l1_l13_smoke,
    run_research_decision_l1_l7_smoke,
    run_research_decision_l1_l8_smoke,
    run_research_decision_l1_l9_smoke,
    run_research_l1_l2_smoke,
    run_research_l1_l3_smoke,
    run_research_l1_l4_smoke,
    run_research_l1_l5_smoke,
    run_simulated_pipeline,
)

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
DIRECT_LEGACY_RESEARCH_DECISION_FULL = "DIRECT_LEGACY_RESEARCH_DECISION_FULL"
TERMINOLOGY_LEAKAGE = "TERMINOLOGY_LEAKAGE"


TASK_ENGINE_RUNNER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "task_engine_runner",
        "description": (
            "Strict fail-closed entrypoint for Hermes RESEARCH, DECISION, and "
            "RESEARCH_DECISION engines. Generates the canonical 72B-first "
            "contract, validates completed stage artifacts, and renders only "
            "the final controller report when validation passes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": [ENGINE_RESEARCH, ENGINE_DECISION, ENGINE_RESEARCH_DECISION, "AUTO"],
                    "description": "Task engine mode. AUTO detects only the three heavy task classes.",
                    "default": "AUTO",
                },
                "query": {
                    "type": "string",
                    "description": "Original user request.",
                },
                "action": {
                    "type": "string",
                    "enum": [
                        "contract",
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
                    "description": (
                        "contract: return canonical contract. agy-preflight: check AGY auth/model list only. omlx-preflight: check OMLX auth/admin/model visibility only. dry-run: return StageRecord plan without model calls. "
                        "simulated-run: write fake artifacts and validate/render. smoke-decision-final: complete real DECISION 10-stage smoke without RESEARCH L1-L5. validate: validate run. "
                        "render: validate and render final output. smoke-research-l1-l2: real AGY/DDGS smoke for RESEARCH L1/L2 only. "
                        "smoke-research-l1-l3: real RESEARCH L1/L2/L2.5/L3 smoke only. "
                        "smoke-research-l1-l4: real RESEARCH L1/L2/L2.5/L3/L4 smoke only. "
                        "smoke-research-l1-l5: real RESEARCH L1/L2/L2.5/L3/L4/L5 smoke only. "
                        "smoke-research-decision-intelligence: real RESEARCH L1-L5 plus Decision intelligence_layer only. "
                        "smoke-research-decision-search: real RESEARCH L1-L5 plus intelligence_layer and supplementary_search only. "
                        "smoke-research-decision-structure: real RESEARCH L1-L5 plus Decision stages 7-9 only. "
                        "smoke-research-decision-evidence: real RESEARCH L1-L5 plus Decision stages 7-10 only. "
                        "smoke-research-decision-premise: real RESEARCH L1-L5 plus Decision stages 7-11 only. "
                        "smoke-research-decision-alternative: real RESEARCH L1-L5 plus Decision stages 7-12 only. "
                        "smoke-research-decision-insight: real RESEARCH L1-L5 plus Decision stages 7-13 only. "
                        "smoke-research-decision-convergence: real RESEARCH L1-L5 plus Decision stages 7-14 only. "
                        "smoke-research-decision-calibration: real RESEARCH L1-L5 plus Decision stages 7-15 only. "
                        "smoke-research-decision-final: disabled integration-only combined-mode action; "
                        "production validation must use RESEARCH full + DECISION full with a current-run research packet."
                    ),
                    "default": "contract",
                },
                "run": {
                    "type": "object",
                    "description": "Completed run metadata with stages[]. Required for validate/render.",
                },
                "base_dir": {
                    "type": "string",
                    "description": "Optional base directory used to resolve relative artifact paths.",
                },
                "research_packet_path": {
                    "type": "string",
                    "description": "Optional research_evidence_packet.md path for two-step RESEARCH -> DECISION runs.",
                },
                "allow_archived_research_decision": {
                    "type": "boolean",
                    "description": "Explicitly allow archived RESEARCH_DECISION real execution. Defaults to false.",
                    "default": False,
                },
                "passive_guard_debug": {
                    "type": "boolean",
                    "description": "Opt-in debug report of deterministic passive-intelligence guard trigger matches.",
                    "default": False,
                },
                "passive_guard_mode": {
                    "type": "string",
                    "enum": ["off", "debug", "warn", "block_destructive"],
                    "description": "Opt-in passive-intelligence guard mode. Defaults to off; passive_guard_debug maps to debug.",
                    "default": "off",
                },
                "passive_guard_action": {
                    "type": "object",
                    "description": "Optional caller-provided action descriptor for passive permission checks.",
                },
                "passive_guard_ledger": {
                    "type": "object",
                    "description": "Optional caller-provided status ledger seed for passive debug/warn checks.",
                },
                "passive_guard_report_text": {
                    "type": "string",
                    "description": "Optional report text to check for warning-only final report consistency.",
                },
                "passive_guard_document_validation": {
                    "type": "object",
                    "description": "Optional caller-provided document validation observations for debug/warn overclaim checks.",
                },
                "passive_guard_watchdog_state": {
                    "type": "object",
                    "description": "Optional caller-provided long-run process state for debug/warn watchdog classification.",
                },
                "passive_runtime_events": {
                    "type": "array",
                    "description": "Optional caller-provided passive runtime events for debug/warn ledger metadata.",
                },
                "passive_runtime_ledger": {
                    "type": "object",
                    "description": "Optional caller-provided passive runtime ledger snapshot for debug/warn metadata.",
                },
            },
            "required": ["query"],
        },
    },
}


def task_engine_runner(
    *,
    query: str,
    mode: str = "AUTO",
    action: str = "contract",
    run: dict[str, Any] | None = None,
    base_dir: str | None = None,
    research_packet_path: str | None = None,
    allow_archived_research_decision: bool = False,
    passive_guard_debug: bool = False,
    passive_guard_mode: str = "off",
    passive_guard_action: dict[str, Any] | None = None,
    passive_guard_ledger: dict[str, Any] | None = None,
    passive_guard_report_text: str | None = None,
    passive_guard_document_validation: dict[str, Any] | None = None,
    passive_guard_watchdog_state: dict[str, Any] | None = None,
    passive_runtime_events: list[dict[str, Any]] | None = None,
    passive_runtime_ledger: dict[str, Any] | None = None,
) -> str:
    resolved_mode = _resolve_mode(mode, query)
    action = (action or "contract").strip().lower().replace("_", "-")
    guard_mode = _resolve_passive_guard_mode(passive_guard_mode, passive_guard_debug)

    if resolved_mode is None:
        return json.dumps(
            {
                "status": "not_applicable",
                "message": "No RESEARCH/DECISION/RESEARCH_DECISION task engine mode detected.",
                "ordinary_chat_model_replaced": False,
            },
            ensure_ascii=False,
            indent=2,
        )

    if action == "full" and normalize_mode(resolved_mode) == ENGINE_RESEARCH_DECISION:
        if not _research_decision_archive_allowed(allow_archived_research_decision):
            return json.dumps(
                _archived_research_decision_response(action="full"),
                ensure_ascii=False,
                indent=2,
            )
        action = "smoke-research-decision-final"
    elif action == "full":
        action = _full_action_for_mode(resolved_mode)

    pre_action_block = _passive_guard_pre_action_block(
        query=query,
        mode=resolved_mode,
        action=action,
        guard_mode=guard_mode,
        passive_guard_action=passive_guard_action,
        passive_guard_ledger=passive_guard_ledger,
        passive_guard_document_validation=passive_guard_document_validation,
        passive_guard_watchdog_state=passive_guard_watchdog_state,
        passive_runtime_events=passive_runtime_events,
        passive_runtime_ledger=passive_runtime_ledger,
    )
    if pre_action_block is not None:
        return json.dumps(pre_action_block, ensure_ascii=False, indent=2)

    if action == "contract":
        payload = {
            "status": "ok",
            "mode": resolved_mode,
            "contract": build_engine_contract(resolved_mode, query),
            "schema": canonical_schema(resolved_mode),
        }
        _attach_passive_guard_metadata(
            payload,
            query=query,
            mode=resolved_mode,
            action=action,
            guard_mode=guard_mode,
            passive_guard_action=passive_guard_action,
            passive_guard_ledger=passive_guard_ledger,
            report_text=passive_guard_report_text,
            document_validation=passive_guard_document_validation,
            watchdog_state=passive_guard_watchdog_state,
            runtime_events=passive_runtime_events,
            runtime_ledger=passive_runtime_ledger,
        )
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )

    if action == "agy-preflight":
        return json.dumps(run_agy_preflight(), ensure_ascii=False, indent=2)

    if action == "omlx-preflight":
        return json.dumps(run_omlx_preflight(), ensure_ascii=False, indent=2)

    if action == "dry-run":
        payload = {
            "status": "ok",
            "mode": resolved_mode,
            "plan": build_dry_run_plan(resolved_mode, base_dir=base_dir),
        }
        _attach_passive_guard_metadata(
            payload,
            query=query,
            mode=resolved_mode,
            action=action,
            guard_mode=guard_mode,
            passive_guard_action=passive_guard_action,
            passive_guard_ledger=passive_guard_ledger,
            report_text=passive_guard_report_text,
            document_validation=passive_guard_document_validation,
            watchdog_state=passive_guard_watchdog_state,
            runtime_events=passive_runtime_events,
            runtime_ledger=passive_runtime_ledger,
        )
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )

    if action == "simulated-run":
        target_dir = _resolve_artifact_dir(base_dir, resolved_mode, "simulated")
        result = run_simulated_pipeline(resolved_mode, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action == "archived-research-decision":
        return json.dumps(
            _archived_research_decision_response(action="full"),
            ensure_ascii=False,
            indent=2,
        )

    if _is_archived_research_decision_real_action(resolved_mode, action) and not _research_decision_archive_allowed(allow_archived_research_decision):
        return json.dumps(
            _archived_research_decision_response(action=action),
            ensure_ascii=False,
            indent=2,
        )

    if action == "smoke-research-l1-l2":
        if normalize_mode(resolved_mode) not in {ENGINE_RESEARCH, ENGINE_RESEARCH_DECISION}:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "L1/L2 smoke is only valid for RESEARCH or RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH, "real_smoke_l1_l2")
        result = run_research_l1_l2_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action == "smoke-research-l1-l3":
        if normalize_mode(resolved_mode) not in {ENGINE_RESEARCH, ENGINE_RESEARCH_DECISION}:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "L1/L3 smoke is only valid for RESEARCH or RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH, "real_smoke_l1_l3")
        result = run_research_l1_l3_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action == "smoke-research-l1-l4":
        if normalize_mode(resolved_mode) not in {ENGINE_RESEARCH, ENGINE_RESEARCH_DECISION}:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "L1/L4 smoke is only valid for RESEARCH or RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH, "real_smoke_l1_l4")
        result = run_research_l1_l4_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action == "smoke-research-l1-l5":
        if normalize_mode(resolved_mode) not in {ENGINE_RESEARCH, ENGINE_RESEARCH_DECISION}:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "L1/L5 smoke is only valid for RESEARCH or RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH, "real_smoke_l1_l5")
        result = run_research_l1_l5_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action == "smoke-decision-final":
        if normalize_mode(resolved_mode) != ENGINE_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision final smoke is only valid for DECISION.",
                },
                ensure_ascii=False,
                indent=2,
        )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_DECISION, "real_smoke_decision_final")
        try:
            resolved_research_packet_path = _resolve_decision_research_packet_path(
                query=query,
                mode=resolved_mode,
                base_dir=base_dir,
                research_packet_path=research_packet_path,
            )
        except _ResearchPacketDiscoveryBlocked as exc:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": PIPELINE_BLOCKED,
                    "blocked_stage": "research_packet_discovery",
                    "blocked_reason": str(exc),
                    "artifact_dir": str(target_dir),
                    "message": "DECISION requested latest research packet, but no valid new RESEARCH packet was found.",
                },
                ensure_ascii=False,
                indent=2,
            )
        kwargs: dict[str, Any] = {"base_dir": target_dir}
        if resolved_research_packet_path:
            kwargs["research_packet_path"] = resolved_research_packet_path
        result = run_decision_final_smoke(query, **kwargs)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in {"smoke-research-decision-intelligence", "smoke-research-decision-d1"}:
        if normalize_mode(resolved_mode) != ENGINE_RESEARCH_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision intelligence smoke is only valid for RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH_DECISION, "real_smoke_research_decision_intelligence")
        result = run_research_decision_l1_l7_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in {"smoke-research-decision-search", "smoke-research-decision-d2"}:
        if normalize_mode(resolved_mode) != ENGINE_RESEARCH_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision supplementary search smoke is only valid for RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH_DECISION, "real_smoke_research_decision_search")
        result = run_research_decision_l1_l8_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in {"smoke-research-decision-structure", "smoke-research-decision-d3"}:
        if normalize_mode(resolved_mode) != ENGINE_RESEARCH_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision structure mapper smoke is only valid for RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH_DECISION, "real_smoke_research_decision_structure")
        result = run_research_decision_l1_l9_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in {"smoke-research-decision-evidence", "smoke-research-decision-d4"}:
        if normalize_mode(resolved_mode) != ENGINE_RESEARCH_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision evidence judge smoke is only valid for RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH_DECISION, "real_smoke_research_decision_evidence")
        result = run_research_decision_l1_l10_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in {"smoke-research-decision-premise", "smoke-research-decision-d5"}:
        if normalize_mode(resolved_mode) != ENGINE_RESEARCH_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision premise auditor smoke is only valid for RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH_DECISION, "real_smoke_research_decision_premise")
        result = run_research_decision_l1_l11_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in {"smoke-research-decision-alternative", "smoke-research-decision-d6"}:
        if normalize_mode(resolved_mode) != ENGINE_RESEARCH_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision alternative generator smoke is only valid for RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH_DECISION, "real_smoke_research_decision_alternative")
        result = run_research_decision_l1_l12_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in {"smoke-research-decision-insight", "smoke-research-decision-d7"}:
        if normalize_mode(resolved_mode) != ENGINE_RESEARCH_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision insight harvester smoke is only valid for RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH_DECISION, "real_smoke_research_decision_insight")
        result = run_research_decision_l1_l13_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in {"smoke-research-decision-convergence", "smoke-research-decision-d8"}:
        if normalize_mode(resolved_mode) != ENGINE_RESEARCH_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision convergence smoke is only valid for RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH_DECISION, "real_smoke_research_decision_convergence")
        result = run_research_decision_l1_l14_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in {"smoke-research-decision-calibration", "smoke-research-decision-d9"}:
        if normalize_mode(resolved_mode) != ENGINE_RESEARCH_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision external calibration smoke is only valid for RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH_DECISION, "real_smoke_research_decision_calibration")
        result = run_research_decision_l1_l15_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action in {"smoke-research-decision-final", "smoke-research-decision-d10"}:
        if normalize_mode(resolved_mode) != ENGINE_RESEARCH_DECISION:
            return json.dumps(
                {
                    "status": "blocked",
                    "pipeline_status": "PIPELINE_BLOCKED",
                    "error": "Decision final controller smoke is only valid for RESEARCH_DECISION.",
                },
                ensure_ascii=False,
                indent=2,
            )
        target_dir = _resolve_artifact_dir(base_dir, ENGINE_RESEARCH_DECISION, "real_smoke_research_decision_final")
        result = run_research_decision_l1_l16_smoke(query, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action not in {"validate", "render"}:
        return json.dumps(
            {"status": "error", "error": f"Unknown action: {action!r}"},
            ensure_ascii=False,
            indent=2,
        )

    if not isinstance(run, dict):
        return json.dumps(
            {
                "status": "blocked",
                "pipeline_status": "PIPELINE_BLOCKED",
                "error": "run metadata is required for validate/render",
            },
            ensure_ascii=False,
            indent=2,
        )

    validation = validate_pipeline(resolved_mode, run, base_dir=base_dir)
    if action == "validate":
        payload = {"status": "ok" if validation["valid"] else "blocked", "validation": validation}
        _attach_passive_guard_metadata(
            payload,
            query=query,
            mode=resolved_mode,
            action=action,
            guard_mode=guard_mode,
            passive_guard_action=passive_guard_action,
            passive_guard_ledger=passive_guard_ledger,
            report_text=passive_guard_report_text,
            document_validation=passive_guard_document_validation,
            watchdog_state=passive_guard_watchdog_state,
            runtime_events=passive_runtime_events,
            runtime_ledger=passive_runtime_ledger,
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    markdown = render_final_markdown(resolved_mode, run, validation, base_dir=base_dir)
    payload = {
        "status": "ok" if validation["valid"] else "blocked",
        "validation": validation,
        "markdown": markdown,
    }
    _attach_passive_guard_metadata(
        payload,
        query=query,
        mode=resolved_mode,
        action=action,
        guard_mode=guard_mode,
        passive_guard_action=passive_guard_action,
        passive_guard_ledger=passive_guard_ledger,
        report_text=passive_guard_report_text or markdown,
        document_validation=passive_guard_document_validation,
        watchdog_state=passive_guard_watchdog_state,
        runtime_events=passive_runtime_events,
        runtime_ledger=passive_runtime_ledger,
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _resolve_passive_guard_mode(mode: str, debug_enabled: bool) -> str:
    normalized = (mode or "off").strip().casefold().replace("-", "_")
    if normalized not in {"off", "debug", "warn", "block_destructive"}:
        normalized = "off"
    if normalized == "off" and debug_enabled:
        return "debug"
    return normalized


def _attach_passive_guard_metadata(
    payload: dict[str, Any],
    *,
    query: str,
    mode: str,
    action: str,
    guard_mode: str,
    passive_guard_action: dict[str, Any] | None = None,
    passive_guard_ledger: dict[str, Any] | None = None,
    report_text: str | None = None,
    document_validation: dict[str, Any] | None = None,
    watchdog_state: dict[str, Any] | None = None,
    runtime_events: list[dict[str, Any]] | None = None,
    runtime_ledger: dict[str, Any] | None = None,
) -> None:
    if guard_mode == "off":
        return
    ledger = _build_passive_status_ledger(mode=mode, action=action, ledger_seed=passive_guard_ledger)
    permission = classify_action_permission(passive_guard_action) if isinstance(passive_guard_action, dict) else None
    consistency = None
    warnings: tuple[dict[str, str], ...] = ()
    skill_triggers = classify_skill_triggers(query)
    if guard_mode in {"warn", "block_destructive"} and report_text:
        consistency = check_final_report_consistency(ledger, report_text)
        warnings = build_final_report_consistency_warnings(ledger, report_text)
    payload["passive_intelligence_guard"] = {
        "mode": guard_mode,
        "skill_triggers": skill_triggers,
        "debug_only": guard_mode == "debug",
        "production_behavior_change": False,
        "status_ledger": asdict(ledger),
    }
    if permission is not None:
        payload["passive_intelligence_guard"]["action_permission"] = asdict(permission)
        payload["passive_intelligence_guard"]["would_block_destructive"] = _is_destructive_permission_decision(permission)
    if consistency is not None:
        payload["passive_intelligence_guard"]["final_report_consistency"] = {
            "consistent": consistency.consistent,
            "violations": list(consistency.violations),
            "warnings": list(warnings),
            "warning_only": True,
        }
    if guard_mode in {"debug", "warn"}:
        observer_metadata = _build_passive_observer_metadata(query=query, guard_mode=guard_mode)
        if observer_metadata:
            payload["passive_intelligence_guard"]["observer_plans"] = observer_metadata
    if isinstance(document_validation, dict):
        payload["passive_intelligence_guard"]["document_validation"] = _build_document_validation_metadata(
            document_validation,
            report_text=report_text,
        )
    if isinstance(watchdog_state, dict):
        payload["passive_intelligence_guard"]["long_run_watchdog"] = _build_long_run_watchdog_metadata(watchdog_state)
    runtime_metadata = _build_passive_runtime_metadata(
        runtime_events=runtime_events,
        runtime_ledger=runtime_ledger,
        task_id=f"{normalize_mode(mode).lower()}:{action}",
        guard_mode=guard_mode,
        report_text=report_text,
    )
    if runtime_metadata:
        payload["passive_intelligence_guard"]["runtime_ledger"] = runtime_metadata


def _passive_guard_pre_action_block(
    *,
    query: str,
    mode: str,
    action: str,
    guard_mode: str,
    passive_guard_action: dict[str, Any] | None,
    passive_guard_ledger: dict[str, Any] | None,
    passive_guard_document_validation: dict[str, Any] | None = None,
    passive_guard_watchdog_state: dict[str, Any] | None = None,
    passive_runtime_events: list[dict[str, Any]] | None = None,
    passive_runtime_ledger: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if guard_mode != "block_destructive" or not isinstance(passive_guard_action, dict):
        return None
    permission = classify_action_permission(passive_guard_action)
    if not _is_destructive_permission_decision(permission):
        return None
    payload = {
        "status": "blocked",
        "pipeline_status": PIPELINE_BLOCKED,
        "blocked_stage": "passive_intelligence_guard",
        "blocked_reason": permission.reason,
        "message": "Passive guard blocked a clearly destructive or impossible action in explicit block_destructive mode.",
    }
    _attach_passive_guard_metadata(
        payload,
        query=query,
        mode=mode,
        action=action,
        guard_mode=guard_mode,
        passive_guard_action=passive_guard_action,
        passive_guard_ledger=passive_guard_ledger,
        document_validation=passive_guard_document_validation,
        watchdog_state=passive_guard_watchdog_state,
        runtime_events=passive_runtime_events,
        runtime_ledger=passive_runtime_ledger,
    )
    return payload


def _is_destructive_permission_decision(permission: Any) -> bool:
    return getattr(permission, "reason", "") in {
        "git_force_push_blocked",
        "report_only_non_report_write_blocked",
        "dry_run_official_update_blocked",
        "official_or_production_update_requires_user_authorization",
        "memory_mutation_requires_user_authorization",
        "file_mutation_requires_user_authorization",
        "browser_gui_execution_requires_openclaw",
    }


def _build_passive_status_ledger(*, mode: str, action: str, ledger_seed: dict[str, Any] | None) -> Any:
    seed = dict(ledger_seed or {})
    seed.setdefault("task_id", f"{normalize_mode(mode).lower()}:{action}")
    seed.setdefault("project_id", "task_engine_runner")
    seed.setdefault("task_status", "pending" if action in {"contract", "dry-run"} else "running")
    seed.setdefault("current_phase", action)
    seed.setdefault("dry_run", action == "dry-run")
    seed.setdefault("report_only", action in {"contract", "validate"})
    return initialize_status_ledger(seed)


def _build_document_validation_metadata(document_validation: dict[str, Any], *, report_text: str | None) -> dict[str, Any]:
    file_path = str(document_validation.get("file_path") or document_validation.get("path") or "")
    intended_use = str(document_validation.get("intended_use") or "")
    plan = classify_document_validation_requirements(file_path, intended_use)
    results = dict(document_validation)
    results.setdefault("plan", plan)
    results.setdefault("required_checks", plan.required_checks)
    decision = classify_pdf_validation_result(results)
    warning = build_document_validation_warning(decision, str(document_validation.get("report_text") or report_text or ""))
    return {
        "plan": asdict(plan),
        "decision": asdict(decision),
        "warning": warning,
        "summary": safe_document_validation_summary(decision),
        "warning_only": True,
    }


def _build_passive_observer_metadata(*, query: str, guard_mode: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    document_plan = build_document_validation_observer_plan(query)
    if document_plan.triggered:
        metadata["document_validation"] = {
            "plan": asdict(document_plan),
            "summary": summarize_document_validation_plan(document_plan),
            "warnings": _observer_document_warnings(document_plan, query) if guard_mode == "warn" else [],
            "warning_only": True,
        }
    long_run_plan = build_long_run_observer_plan(query)
    if long_run_plan.triggered:
        metadata["long_run_watchdog"] = {
            "plan": asdict(long_run_plan),
            "summary": summarize_long_run_observer_plan(long_run_plan),
            "warnings": _observer_long_run_warnings(long_run_plan, query) if guard_mode == "warn" else [],
            "warning_only": True,
        }
    return metadata


def _observer_document_warnings(plan: Any, query: str) -> list[dict[str, str]]:
    lowered = (query or "").casefold()
    warnings: list[dict[str, str]] = []
    for claim in plan.prohibited_claims:
        if claim.casefold() in lowered:
            warnings.append(
                {
                    "code": "PASSIVE_DOCUMENT_OBSERVER_OVERCLAIM_RISK",
                    "offending_phrase": claim,
                    "safe_interpretation": plan.warning_if_checks_missing,
                }
            )
    if not plan.files:
        warnings.append(
            {
                "code": "PASSIVE_DOCUMENT_OBSERVER_FILE_INVENTORY_REQUIRED",
                "offending_phrase": "",
                "safe_interpretation": plan.next_safe_action,
            }
        )
    return warnings


def _observer_long_run_warnings(plan: Any, query: str) -> list[dict[str, str]]:
    lowered = (query or "").casefold()
    warnings: list[dict[str, str]] = []
    for claim in plan.prohibited_claims:
        if re.search(rf"\b{re.escape(claim.casefold())}\b", lowered):
            warnings.append(
                {
                    "code": "PASSIVE_LONG_RUN_OBSERVER_COMPLETION_OVERCLAIM_RISK",
                    "offending_phrase": claim,
                    "safe_interpretation": plan.partial_output_policy,
                }
            )
    if any(term in lowered for term in ("timeout", "stuck", "silent", "no output", "waiting", "running", "卡住", "等待", "没返回")):
        warnings.append(
            {
                "code": "PASSIVE_LONG_RUN_OBSERVER_STATUS_REQUIRED",
                "offending_phrase": "",
                "safe_interpretation": "Collect phase, last output time, elapsed time, retry count, and next safe action before reporting completion.",
            }
        )
    return warnings


def _build_long_run_watchdog_metadata(watchdog_state: dict[str, Any]) -> dict[str, Any]:
    decision = classify_long_run_event(watchdog_state)
    policy = get_stage_timeout_policy(
        str(watchdog_state.get("stage_name") or watchdog_state.get("stage") or ""),
        str(watchdog_state.get("owner_tool") or ""),
    )
    return {
        "policy": asdict(policy),
        "decision": asdict(decision),
        "summary": safe_long_run_status_summary(decision),
        "warning_only": True,
    }


def _build_passive_runtime_metadata(
    *,
    runtime_events: list[dict[str, Any]] | None,
    runtime_ledger: dict[str, Any] | None,
    task_id: str,
    guard_mode: str,
    report_text: str | None,
) -> dict[str, Any]:
    if not runtime_events and not isinstance(runtime_ledger, dict):
        return {}
    ledger = (
        build_passive_runtime_ledger(runtime_events or (), task_id=task_id, mode=guard_mode)
        if runtime_events
        else coerce_passive_runtime_ledger(runtime_ledger, task_id=task_id, mode=guard_mode)
    )
    decision = classify_ledger_completion_state(ledger)
    warnings = ledger_to_final_report_warnings(ledger, report_text) if guard_mode == "warn" else []
    return {
        "summary": summarize_passive_runtime_ledger(ledger),
        "ledger": asdict(ledger),
        "decision": asdict(decision),
        "warnings": warnings,
        "warning_only": True,
        "blocks_expanded": False,
    }


def _resolve_mode(mode: str, query: str) -> str | None:
    normalized = (mode or "AUTO").strip().upper().replace("-", "_")
    if normalized == "AUTO":
        return detect_task_engine_mode(query)
    return normalized


def _full_action_for_mode(mode: str) -> str:
    normalized = normalize_mode(mode)
    if normalized == ENGINE_RESEARCH:
        return "smoke-research-l1-l5"
    if normalized == ENGINE_DECISION:
        return "smoke-decision-final"
    if normalized == ENGINE_RESEARCH_DECISION:
        return "archived-research-decision"
    return "dry-run"


def _research_decision_archive_allowed(explicit: bool = False) -> bool:
    return bool(explicit) or os.getenv("HERMES_ENABLE_RESEARCH_DECISION") == "1"


def _is_archived_research_decision_real_action(mode: str | None, action: str) -> bool:
    return normalize_mode(mode or "") == ENGINE_RESEARCH_DECISION and action.startswith("smoke-research-decision")


def _archived_research_decision_response(*, action: str) -> dict[str, Any]:
    reason = DIRECT_LEGACY_RESEARCH_DECISION_FULL if action == "full" else "RESEARCH_DECISION_ARCHIVED"
    return {
        "status": "blocked",
        "pipeline_status": "PIPELINE_BLOCKED",
        "blocked_stage": "research_decision_archived",
        "blocked_reason": reason,
        "mode": ENGINE_RESEARCH_DECISION,
        "action": action,
        "message": (
            "Combined-mode production validation is disabled. Run RESEARCH full first to produce "
            "a current-run research_evidence_packet.md, then run DECISION full with research_packet_path."
        ),
        "entrypoint_guard": reason,
        "two_step_recommendation": [
            "RESEARCH full -> research_evidence_packet.md",
            "DECISION full with research_packet_path=<path to research_evidence_packet.md>",
        ],
        "allow_override": {
            "function_arg": "allow_archived_research_decision=True",
            "environment": "HERMES_ENABLE_RESEARCH_DECISION=1",
        },
    }


def audit_legacy_research_decision_terms(value: Any, *, context: str = "normal") -> list[dict[str, str]]:
    """Return banned combined-mode terminology leaks outside explicit audit contexts."""
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
    guarded["pipeline_status"] = PIPELINE_BLOCKED
    guarded["blocked_stage"] = "legacy_research_decision_terminology"
    guarded["blocked_reason"] = TERMINOLOGY_LEAKAGE
    guarded["legacy_term_audit"] = {"violations": violations}
    return guarded


def _resolve_artifact_dir(base_dir: str | None, mode: str, label: str) -> Path:
    if base_dir:
        return Path(base_dir).resolve()
    root = Path(
        os.getenv(
            "HERMES_TASK_ENGINE_ARTIFACT_DIR",
            str(Path.cwd() / ".hermes_task_engine_runs"),
        )
    )
    return (root / f"{int(time.time())}_{mode.lower()}_{label}").resolve()


class _ResearchPacketDiscoveryBlocked(Exception):
    pass


def _resolve_decision_research_packet_path(
    *,
    query: str,
    mode: str,
    base_dir: str | None,
    research_packet_path: str | None,
) -> str | None:
    if normalize_mode(mode) != ENGINE_DECISION:
        return research_packet_path
    value = (research_packet_path or "").strip()
    if not value:
        value = _decision_research_packet_alias_from_query(query)
    if not value:
        return None
    if value.strip().lower() in {"latest", "最新"}:
        discovered = _find_latest_valid_research_packet(base_dir=base_dir)
        if discovered is None:
            raise _ResearchPacketDiscoveryBlocked("no_valid_new_research_packet_found")
        return str(discovered)
    return value


def _decision_research_packet_alias_from_query(query: str) -> str | None:
    text = query or ""
    assignment = re.search(
        r"(?:research_packet_path|研究成果包)\s*[=:：]\s*([^\s，。；;]+)",
        text,
        flags=re.IGNORECASE,
    )
    if assignment:
        value = assignment.group(1).strip().strip("`'\"")
        if value.lower() == "latest" or value == "最新":
            return "latest"
        return value
    if "最新研究成果包" in text:
        return "latest"
    return None


def _find_latest_valid_research_packet(*, base_dir: str | None) -> Path | None:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in _research_packet_search_roots(base_dir):
        if not root.exists():
            continue
        try:
            found = list(root.rglob("research_evidence_packet.md")) if root.is_dir() else []
        except OSError:
            continue
        for path in found:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(resolved)

    candidates.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    for path in candidates:
        if _is_valid_new_research_packet(path):
            return path
    return None


def _research_packet_search_roots(base_dir: str | None) -> list[Path]:
    roots: list[Path] = []
    if base_dir:
        base = Path(base_dir).expanduser().resolve()
        roots.extend([base, base.parent])
    env_root = os.getenv("HERMES_TASK_ENGINE_ARTIFACT_DIR", "").strip()
    if env_root:
        roots.append(Path(env_root).expanduser().resolve())
    cwd = Path.cwd().resolve()
    roots.extend([cwd / ".hermes_task_engine_runs", cwd / "validation_outputs", cwd])

    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _is_valid_new_research_packet(path: Path) -> bool:
    if path.name != "research_evidence_packet.md" or path.parent.name != "L5_deepseek_acceptance":
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if _research_evidence_packet_quality_error(text):
        return False
    research_root = path.parent.parent
    stages = []
    for spec in CANONICAL_STAGES[ENGINE_RESEARCH]:
        outputs = planned_outputs(spec, research_root)
        record = make_stage_record(
            spec,
            base_dir=research_root,
            created=True,
            valid=True,
            status="real",
            outputs=outputs,
        )
        stages.append(record.__dict__)
    validation = validate_pipeline(
        ENGINE_RESEARCH,
        {"mode": ENGINE_RESEARCH, "execution_mode": "real-smoke-l1-l5", "stages": stages},
        base_dir=research_root,
    )
    return validation.get("stage_count") == 6 and validation.get("valid") is True


def _task_engine_handler(args: dict[str, Any], **kw) -> str:
    return task_engine_runner(
        query=str(args.get("query", "")),
        mode=str(args.get("mode", "AUTO")),
        action=str(args.get("action", "contract")),
        run=args.get("run"),
        base_dir=args.get("base_dir"),
        research_packet_path=args.get("research_packet_path"),
        allow_archived_research_decision=bool(args.get("allow_archived_research_decision", False)),
        passive_guard_debug=bool(args.get("passive_guard_debug", False)),
        passive_guard_mode=str(args.get("passive_guard_mode", "off")),
        passive_guard_action=args.get("passive_guard_action"),
        passive_guard_ledger=args.get("passive_guard_ledger"),
        passive_guard_report_text=args.get("passive_guard_report_text"),
        passive_guard_document_validation=args.get("passive_guard_document_validation"),
        passive_guard_watchdog_state=args.get("passive_guard_watchdog_state"),
        passive_runtime_events=args.get("passive_runtime_events"),
        passive_runtime_ledger=args.get("passive_runtime_ledger"),
    )


def _check_task_engine_requirements() -> bool:
    return True


registry.register(
    name="task_engine_runner",
    toolset="research",
    schema=TASK_ENGINE_RUNNER_SCHEMA,
    handler=_task_engine_handler,
    check_fn=_check_task_engine_requirements,
    emoji="🧭",
    description="Strict RESEARCH/DECISION/RESEARCH_DECISION contract, validator, and final renderer.",
)


__all__ = [
    "TASK_ENGINE_RUNNER_SCHEMA",
    "LEGACY_RESEARCH_DECISION_BANNED_TERMS",
    "LEGACY_RESEARCH_DECISION_ALLOWED_TERMS",
    "DIRECT_LEGACY_RESEARCH_DECISION_FULL",
    "TERMINOLOGY_LEAKAGE",
    "apply_legacy_research_decision_term_guard",
    "audit_legacy_research_decision_terms",
    "task_engine_runner",
]
