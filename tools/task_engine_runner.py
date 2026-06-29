"""Hermes task-engine entrypoint for research and decision pipelines."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from tools.registry import registry
from tools.task_engine_contracts import (
    CANONICAL_STAGES,
    ENGINE_DECISION,
    ENGINE_RESEARCH,
    ENGINE_RESEARCH_DECISION,
    PIPELINE_BLOCKED,
    PIPELINE_COMPLETE,
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
from tools.passive_intelligence_guard import classify_skill_triggers
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
    run_simulated_pipeline as _executor_run_simulated_pipeline,
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
                "emit_topic_refinement_advisory": {
                    "type": "boolean",
                    "description": (
                        "Explicit opt-in report-only post-final Topic Refinement advisory. "
                        "Default false; only runs after PIPELINE_COMPLETE and never executes TOPIC_REFINEMENT."
                    ),
                    "default": False,
                },
                "topic_refinement_advisory_output_dir": {
                    "type": "string",
                    "description": (
                        "Optional sidecar output directory for the report-only Topic Refinement advisory. "
                        "Defaults to <artifact_dir>/topic_refinement_advisory when the advisory flag is true."
                    ),
                },
                "topic_refinement_advisory_strict": {
                    "type": "boolean",
                    "description": "Strict mode passed to the report-only advisory wrapper. Defaults to true.",
                    "default": True,
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
    emit_topic_refinement_advisory: bool = False,
    topic_refinement_advisory_output_dir: str | None = None,
    topic_refinement_advisory_strict: bool = True,
) -> str:
    resolved_mode = _resolve_mode(mode, query)
    action = (action or "contract").strip().lower().replace("_", "-")
    emit_topic_refinement_advisory = _coerce_advisory_bool(emit_topic_refinement_advisory, default=False)
    topic_refinement_advisory_strict = _coerce_advisory_bool(topic_refinement_advisory_strict, default=True)

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

    def _finalize_result(result: dict[str, Any], *, target_dir: Path) -> str:
        result["artifact_dir"] = str(target_dir)
        if emit_topic_refinement_advisory:
            _emit_topic_refinement_advisory_sidecar(
                result=result,
                query=query,
                mode=resolved_mode,
                artifact_dir=target_dir,
                advisory_output_dir=topic_refinement_advisory_output_dir,
                strict=topic_refinement_advisory_strict,
            )
        return json.dumps(result, ensure_ascii=False, indent=2)

    if action == "contract":
        payload = {
            "status": "ok",
            "mode": resolved_mode,
            "contract": build_engine_contract(resolved_mode, query),
            "schema": canonical_schema(resolved_mode),
        }
        _attach_passive_guard_debug(payload, query=query, enabled=passive_guard_debug)
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
        _attach_passive_guard_debug(payload, query=query, enabled=passive_guard_debug)
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )

    if action == "simulated-run":
        target_dir = _resolve_artifact_dir(base_dir, resolved_mode, "simulated")
        result = run_simulated_pipeline(resolved_mode, base_dir=target_dir)
        _write_simulated_run_advisory_aliases(
            resolved_mode,
            query=query,
            base_dir=target_dir,
            result=result,
        )
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return _finalize_result(result, target_dir=target_dir)

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
        return json.dumps(
            {"status": "ok" if validation["valid"] else "blocked", "validation": validation},
            ensure_ascii=False,
            indent=2,
        )

    markdown = render_final_markdown(resolved_mode, run, validation, base_dir=base_dir)
    return json.dumps(
        {
            "status": "ok" if validation["valid"] else "blocked",
            "validation": validation,
            "markdown": markdown,
        },
        ensure_ascii=False,
        indent=2,
    )



# Keep the public runner.run_simulated_pipeline patch point local to this module.
# The executor-side fixture still exists, but this safe entrypoint emits artifacts
# that satisfy the current L5 evidence-packet contract without model/network use.
def run_simulated_pipeline(mode: str, *, base_dir: str | Path) -> dict[str, Any]:
    return _run_safe_simulated_pipeline(mode, base_dir=base_dir)


def _run_safe_simulated_pipeline(mode: str, *, base_dir: str | Path) -> dict[str, Any]:
    """Write deterministic no-network simulated artifacts, then validate/render."""
    normalized = normalize_mode(mode)
    base = Path(base_dir)
    stages: list[dict[str, Any]] = []
    for stage in CANONICAL_STAGES[normalized]:
        content = _safe_simulated_stage_text(stage.stage_name)
        artifact_path, outputs = _write_safe_simulated_stage_outputs(stage, content, base)
        record = make_stage_record(
            stage,
            base_dir=base,
            artifact_path=artifact_path,
            outputs=outputs,
            created=True,
            valid=True,
            status="simulated",
            executor_model=stage.model,
        )
        stages.append(record.__dict__)
    run = {"mode": normalized, "execution_mode": "simulated-run", "stages": stages}
    validation = validate_pipeline(normalized, run, base_dir=base)
    markdown = render_final_markdown(normalized, run, validation, base_dir=base)
    return {
        "status": "ok" if validation["valid"] else "blocked",
        "pipeline_status": validation["pipeline_status"],
        "run": run,
        "validation": validation,
        "markdown": markdown,
    }


def _write_safe_simulated_stage_outputs(stage: Any, content: str, base_dir: Path) -> tuple[Path, dict[str, str]]:
    outputs = planned_outputs(stage, base_dir)
    primary_path: Path | None = None
    for required, raw_path in outputs.items():
        output_path = Path(raw_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            _safe_simulated_output_text(stage.stage_name, required, output_path.name, content),
            encoding="utf-8",
        )
        if primary_path is None:
            primary_path = output_path
    if primary_path is None:
        primary_path = base_dir / stage.stage_name / "report.md"
        primary_path.parent.mkdir(parents=True, exist_ok=True)
        primary_path.write_text(content, encoding="utf-8")
    return primary_path, outputs


def _safe_simulated_output_text(stage_name: str, required: str, filename: str, content: str) -> str:
    if filename.endswith(".json"):
        payload = {
            "simulated_fixture": True,
            "stage": stage_name,
            "required_output": required,
            "source_basis": "deterministic_no_network_fixture",
            "full_text_verified": False,
        }
        if filename == "source_candidates.json":
            payload["source_candidates"] = [
                {
                    "source_id": "SIM-S1",
                    "title": "Simulated fixture source candidate",
                    "basis": "no external fetch; contract-only fixture",
                    "full_text_verified": False,
                }
            ]
        if filename == "ddgs_gap_sources.json":
            payload["gap_sources"] = [
                {
                    "source_id": "SIM-G1",
                    "gap": "fixture evidence boundary retained",
                    "full_text_verified": False,
                }
            ]
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if filename.endswith(".csv"):
        return "field,value\nsimulated_fixture,true\nfull_text_verified,false\nsource_basis,deterministic_no_network_fixture\n"
    return content


def _safe_simulated_stage_text(stage_name: str) -> str:
    if stage_name == "L5_deepseek_acceptance":
        return _safe_simulated_research_evidence_packet()
    if stage_name == "external_calibration":
        return (
            "calibration_scope\n"
            "Deterministic simulated calibration keeps fixture claims bounded to current artifacts and does not upgrade confidence. " * 4
            + "claim_strength_table\n"
            "| Claim | Strength | Calibration Notes |\n"
            "| --- | --- | --- |\n"
            "| Fixture claim A | bounded | Use only as simulated contract material. |\n"
            "| Fixture claim B | plausible | Requires user-visible caveats before final use. |\n"
            "over_inference_checks\n"
            "The simulated calibration prevents confidence inflation and requires caveat preservation. " * 4
            + "calibration_verdict\n"
            "verdict: calibrated_for_final_controller; no model call, no source acquisition, no full-text claim.\n"
            "handoff_notes_for_final_controller\n"
            "Use bounded claims only and preserve source limitations.\n"
        )
    if stage_name == "convergence_report":
        return (
            "convergence_report\n"
            "The deterministic fixture converges on a cautious decision frame, but the simulated final may remain too generic. " * 5
            + "convergence not absorbed signal: final should make tradeoffs, priorities, and stop conditions explicit.\n"
        )
    if stage_name == "final_controller_report":
        return (
            "FINAL CONTROLLER BODY\n\n"
            "This is the simulated final controller report. It gives a bounded answer from deterministic fixture artifacts only, "
            "keeps source limitations visible, and does not claim full-text verification or evidence acquisition.\n\n"
            "Recommendation: use observable signals, run a small reversible pilot, define stop conditions, and keep confidence bounded "
            "to the simulated fixture evidence boundary.\n"
        )
    return (
        f"{stage_name} simulated artifact\n"
        "Deterministic no-network fixture content for task-engine contract validation. " * 6
        + "No model call, no external source acquisition, and no final user advice is generated by this stage.\n"
    )


def _safe_simulated_research_evidence_packet() -> str:
    return "\n".join(
        [
            "research_evidence_packet",
            "verdict: ACCEPTED",
            "accepted: true",
            "checked_stages: [L1_gemini_search, L2_ddgs_supplement, L2_5_codex_evidence_organizer, L3_r1_synthesis, L4_gemini_audit]",
            "missing_or_invalid_artifacts: []",
            "critical_defects: []",
            "noncritical_defects: []",
            "verification_required: []",
            "evidence_gaps: [simulated_fixture_gap, direct_domain_source_gap]",
            "handoff_caveats: [simulated_fixture_grade_only, preserve_source_limitations]",
            "audit_summary: L4 simulated audit accepted the compact fixture packet with explicit limitations.",
            "evidence_packet_ready_for_decision: true",
            "verification_status: simulated_fixture_only; full_text_verified false; no external acquisition performed",
            "evidence_boundary: deterministic simulated packet for validation only; do not treat as full-text verified evidence",
            "source_limitations: source anchors are fixture anchors and not live fetched sources",
            "caveats: use only for no-network/no-LLM validation of pipeline shape and advisory sidecar behavior",
            "unsupported_or_speculative_claims: future or domain-transfer claims remain bounded hypotheses and must not raise confidence",
            "",
            "## evidence_strength",
            "Evidence strength is fixture-grade and bounded. Current simulated artifacts support only pipeline-shape validation, not real-world factual confidence. Direct domain facts, full-text verification, and live evidence acquisition are intentionally absent, so downstream stages must preserve caveats and avoid confidence upgrades.",
            "",
            "## claim_table",
            "- claim_id: SIM-C1",
            "  claim_text: Simulated artifacts can exercise the Research/Decision handoff and advisory sidecar without external calls.",
            "  epistemic_tier: evidence_supported",
            "  evidence_strength: medium_for_fixture_contract_only",
            "  source_anchors: SIM-S1 (simulated_fixture; no_network_fixture; local deterministic artifact)",
            "  full_text_verified: false",
            "  support_level: supported_for_fixture_contract_only",
            "  source_basis: simulated_fixture",
            "  applicability_boundary: Applies only to validating artifact contract shape and safe sidecar behavior.",
            "  counter_signal_or_failure_condition: Any use as real external evidence should block or require source authorization.",
            "  evidence_gap: direct_real_world_evidence_absent",
            "  decision_use: can_support_simulated_pipeline_validation_only",
            "  caveat: Does not verify factual claims or support confidence upgrades.",
            "- claim_id: SIM-C2",
            "  claim_text: Final outputs generated from this packet must preserve source limitations and avoid full-text verification claims.",
            "  epistemic_tier: reasonable_inference",
            "  evidence_strength: bounded_fixture_inference",
            "  source_anchors: SIM-S2 (simulated_fixture; no_external_fetch; local deterministic artifact)",
            "  full_text_verified: false",
            "  support_level: plausible_for_fixture_contract_only",
            "  source_basis: simulated_fixture",
            "  applicability_boundary: Applies to no-network validation and not to domain truth.",
            "  counter_signal_or_failure_condition: If a stronger domain conclusion is needed, request source acquisition or full-text verification.",
            "  evidence_gap: domain_specific_validation_gap",
            "  decision_use: preserve_boundary_in_final_and_advisory",
            "  caveat: Keep confidence bounded to fixture evidence.",
            "",
            "## controversy",
            "Controversy remains because simulated fixture material is not a live literature review. It can prove that the chain carries caveats and structured claims, but it cannot settle domain disputes, quantify effects, or replace user-authorized source work.",
            "",
            "## evidence_gap",
            "Evidence gap includes missing live sources, missing full-text checks, and missing domain-specific validation. These gaps are intentional in the safe simulated-run entrypoint and should remain visible to downstream final and advisory artifacts.",
            "",
            "## evidence_supported",
            "Evidence supported material is limited to deterministic local artifacts proving that required sections, claim rows, source anchors, and caveat fields exist. It supports contract validation only, not substantive domain certainty.",
            "",
            "## reasonable_inference",
            "Reasonable inference may connect the fixture claim table to process behavior: if the packet is accepted, the runner can reach PIPELINE_COMPLETE and optionally emit a report-only advisory sidecar. This inference remains about system behavior, not external facts.",
            "",
            "## foresight_hypothesis",
            "Foresight hypothesis is only a bounded placeholder: future or domain-transfer claims should remain tentative, require counter-signals, and should never be treated as verified from the simulated packet alone.",
            "",
            "scope: acceptance gate plus compact simulated evidence packet; no raw artifact dump, no user-facing final advice, no source acquisition, and no full-text verification claim.",
        ]
    )


def _write_simulated_run_advisory_aliases(
    mode: str,
    *,
    query: str,
    base_dir: Path,
    result: dict[str, Any],
) -> None:
    if result.get("pipeline_status") != PIPELINE_COMPLETE:
        return
    base = Path(base_dir)
    _write_text_if_missing(base / "original_user_question.txt", (query or "").strip() + "\n")
    _write_json_if_missing(
        base / "runner_result.json",
        {
            "status": result.get("status"),
            "pipeline_status": result.get("pipeline_status"),
            "mode": normalize_mode(mode),
            "execution_mode": "simulated-run",
            "contract": "stable",
        },
    )
    _copy_text_if_missing(
        base / "L5_deepseek_acceptance" / "research_evidence_packet.md",
        base / "research_evidence_packet.md",
    )
    _copy_text_if_missing(
        base / "L5_deepseek_acceptance" / "research_evidence_packet.md",
        base / "evidence_packet.md",
    )
    _copy_text_if_missing(
        base / "convergence_report" / "convergence_report.md",
        base / "convergence_report.md",
    )
    _copy_text_if_missing(
        base / "external_calibration" / "external_calibration.md",
        base / "calibration_report.md",
    )
    _copy_text_if_missing(
        base / "final_controller_report" / "final_decision_report.md",
        base / "final_controller_report.md",
    )
    run_payload = result.get("run") if isinstance(result.get("run"), dict) else {}
    if run_payload.get("execution_mode") == "simulated-run":
        _write_text_if_missing(
            base / "case_quality_review.md",
            (
                "case_quality_review\n"
                "final too generic and low specificity signals are retained for deterministic advisory validation.\n"
                "missing obligation and weak ranking may require explicit user-confirmed TOPIC_REFINEMENT, unless source boundaries dominate.\n"
                "No automatic execution, no candidate generation, and no final rewrite are allowed.\n"
            ),
        )


def _copy_text_if_missing(source: Path, target: Path) -> None:
    if target.exists() or not source.exists():
        return
    try:
        _write_text_if_missing(target, source.read_text(encoding="utf-8"))
    except OSError:
        return


def _write_text_if_missing(path: Path, text: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json_if_missing(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        return
    _write_text_if_missing(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

def _coerce_advisory_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n", ""}:
            return False
    return bool(value)


def _topic_refinement_advisory_topic_id(mode: str | None) -> str:
    normalized = normalize_mode(mode or "") or "task_engine"
    return f"{normalized.lower()}_post_final"


def _emit_topic_refinement_advisory_sidecar(
    *,
    result: dict[str, Any],
    query: str,
    mode: str | None,
    artifact_dir: str | Path | None,
    advisory_output_dir: str | None,
    strict: bool,
) -> None:
    if result.get("pipeline_status") != PIPELINE_COMPLETE or artifact_dir is None:
        return

    run_dir = Path(artifact_dir).expanduser().resolve(strict=False)
    output_dir = (
        Path(advisory_output_dir).expanduser().resolve(strict=False)
        if advisory_output_dir
        else run_dir / "topic_refinement_advisory"
    )
    topic_id = _topic_refinement_advisory_topic_id(mode)

    try:
        from tools import topic_refinement_post_final_advisory_report as advisory_report

        advisory_report.generate_post_final_topic_refinement_advisory_report(
            run_dir=run_dir,
            topic_id=topic_id,
            output_dir=output_dir,
            user_feedback=query,
            strict=strict,
        )
    except Exception as exc:  # pragma: no cover - defensive sidecar isolation
        _write_topic_refinement_advisory_failed_sidecar(
            output_dir=output_dir,
            run_dir=run_dir,
            topic_id=topic_id,
            reason=str(exc),
            query=query,
        )


def _write_topic_refinement_advisory_failed_sidecar(
    *,
    output_dir: Path,
    run_dir: Path,
    topic_id: str,
    reason: str,
    query: str,
) -> None:
    payload = {
        "status": "BLOCKED_TOPIC_REFINEMENT_ADVISORY_SIDECAR_FAILED",
        "quality_verdict": "REPORT_ONLY_NEEDS_REPAIR",
        "topic_id": topic_id,
        "run_dir": str(run_dir),
        "reason": reason,
        "query_preview": (query or "")[:240],
        "auto_execution": False,
        "auto_adoption": False,
        "no_adapter_called": True,
        "no_manual_task_called": True,
        "no_llm_called": True,
        "no_pipeline_rerun": True,
        "no_candidate_generated": True,
        "no_final_rewritten": True,
    }
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "post_final_topic_refinement_advisory_failed.json").write_text(
            json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        lines = ["# Post-Final Topic Refinement Advisory Sidecar Failed", ""]
        for key, value in payload.items():
            lines.append(f"- {key}: {value}")
        (output_dir / "post_final_topic_refinement_advisory_failed.md").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )
    except Exception:
        return


def _attach_passive_guard_debug(payload: dict[str, Any], *, query: str, enabled: bool) -> None:
    if not enabled:
        return
    payload["passive_intelligence_guard"] = {
        "skill_triggers": classify_skill_triggers(query),
        "debug_only": True,
        "production_behavior_change": False,
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
        emit_topic_refinement_advisory=_coerce_advisory_bool(args.get("emit_topic_refinement_advisory"), default=False),
        topic_refinement_advisory_output_dir=args.get("topic_refinement_advisory_output_dir"),
        topic_refinement_advisory_strict=_coerce_advisory_bool(args.get("topic_refinement_advisory_strict"), default=True),
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
