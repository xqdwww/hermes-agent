"""Hermes task-engine entrypoint for research and decision pipelines."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from tools.registry import registry
from tools.task_engine_contracts import (
    ENGINE_DECISION,
    ENGINE_RESEARCH,
    ENGINE_RESEARCH_DECISION,
    build_dry_run_plan,
    build_engine_contract,
    canonical_schema,
    detect_task_engine_mode,
    render_final_markdown,
    normalize_mode,
    validate_pipeline,
)
from tools.task_engine_executors import (
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
                        "smoke-research-decision-final: complete real RESEARCH_DECISION 16-stage smoke."
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
) -> str:
    resolved_mode = _resolve_mode(mode, query)
    action = (action or "contract").strip().lower().replace("_", "-")

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

    if action == "contract":
        return json.dumps(
            {
                "status": "ok",
                "mode": resolved_mode,
                "contract": build_engine_contract(resolved_mode, query),
                "schema": canonical_schema(resolved_mode),
            },
            ensure_ascii=False,
            indent=2,
        )

    if action == "agy-preflight":
        return json.dumps(run_agy_preflight(), ensure_ascii=False, indent=2)

    if action == "omlx-preflight":
        return json.dumps(run_omlx_preflight(), ensure_ascii=False, indent=2)

    if action == "dry-run":
        return json.dumps(
            {
                "status": "ok",
                "mode": resolved_mode,
                "plan": build_dry_run_plan(resolved_mode, base_dir=base_dir),
            },
            ensure_ascii=False,
            indent=2,
        )

    if action == "simulated-run":
        target_dir = _resolve_artifact_dir(base_dir, resolved_mode, "simulated")
        result = run_simulated_pipeline(resolved_mode, base_dir=target_dir)
        result["artifact_dir"] = str(target_dir)
        return json.dumps(result, ensure_ascii=False, indent=2)

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
        result = run_decision_final_smoke(query, base_dir=target_dir)
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


def _resolve_mode(mode: str, query: str) -> str | None:
    normalized = (mode or "AUTO").strip().upper().replace("-", "_")
    if normalized == "AUTO":
        return detect_task_engine_mode(query)
    return normalized


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


def _task_engine_handler(args: dict[str, Any], **kw) -> str:
    return task_engine_runner(
        query=str(args.get("query", "")),
        mode=str(args.get("mode", "AUTO")),
        action=str(args.get("action", "contract")),
        run=args.get("run"),
        base_dir=args.get("base_dir"),
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


__all__ = ["TASK_ENGINE_RUNNER_SCHEMA", "task_engine_runner"]
