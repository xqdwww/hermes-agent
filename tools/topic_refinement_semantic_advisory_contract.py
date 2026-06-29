#!/usr/bin/env python3
"""Prompt contract and safety checks for semantic Topic Refinement advisory.

R3B is contract-only. It does not call GPT, Claude, any other LLM, network
services, API clients, the explicit TOPIC_REFINEMENT adapter, or the
Research/Decision pipeline.
"""

from __future__ import annotations

import json
from typing import Any

CONTRACT_VERSION = "r3b.0"

STATUS_TOPIC_REFINEMENT = "TOPIC_REFINEMENT_SUGGESTED"
STATUS_SOURCE_NEED = "SOURCE_NEED_SUGGESTED"
STATUS_ENVIRONMENT = "ENVIRONMENT_TRIAGE_SUGGESTED"
STATUS_NO_REFINEMENT = "NO_REFINEMENT_SUGGESTED"
STATUS_NEW_TOPIC = "NEW_TOPIC_OR_FULL_RERUN_RECOMMENDED"
STATUS_INSUFFICIENT = "INSUFFICIENT_ARTIFACTS_TO_ADVISE"

VERDICT_CONFIRM_REFINEMENT = "ASK_USER_TO_CONFIRM_TOPIC_REFINEMENT"
VERDICT_AUTHORIZE_SOURCE = "ASK_USER_TO_AUTHORIZE_SOURCE_OR_FULL_TEXT_VERIFICATION"
VERDICT_FIX_ENVIRONMENT = "ASK_USER_TO_FIX_ENVIRONMENT"
VERDICT_DO_NOT_REFINE = "DO_NOT_REFINE"
VERDICT_START_NEW_TASK = "START_NEW_TASK_INSTEAD"
VERDICT_BLOCKED_CONTEXT = "BLOCKED_INSUFFICIENT_CONTEXT"

ALLOWED_ADVISORY_STATUSES = {
    STATUS_TOPIC_REFINEMENT,
    STATUS_SOURCE_NEED,
    STATUS_ENVIRONMENT,
    STATUS_NO_REFINEMENT,
    STATUS_NEW_TOPIC,
    STATUS_INSUFFICIENT,
}

ALLOWED_ADVISORY_VERDICTS = {
    VERDICT_CONFIRM_REFINEMENT,
    VERDICT_AUTHORIZE_SOURCE,
    VERDICT_FIX_ENVIRONMENT,
    VERDICT_DO_NOT_REFINE,
    VERDICT_START_NEW_TASK,
    VERDICT_BLOCKED_CONTEXT,
}

ALLOWED_REFINEMENT_MODES = {
    "final_absorption_pass",
    "section_rewrite",
    "user_feedback_refinement",
    "targeted_evidence_acquisition",
    "environment_triage",
    None,
}

REQUIRED_FIELDS = (
    "semantic_issue_detected",
    "issue_types",
    "suggested_advisory_status",
    "suggested_advisory_verdict",
    "suggested_refinement_mode",
    "reasons",
    "missing_obligations",
    "specificity_issues",
    "convergence_absorption_issues",
    "calibration_absorption_issues",
    "evidence_boundary_respected",
    "confidence_upgrade_requested",
    "source_need_detected",
    "environment_issue_detected",
    "topic_drift_or_new_topic_detected",
    "should_ask_user",
    "should_auto_execute",
    "should_auto_adopt",
    "evaluator_confidence",
    "false_positive_risk",
    "false_negative_risk",
)

LIST_FIELDS = {
    "issue_types",
    "reasons",
    "missing_obligations",
    "specificity_issues",
    "convergence_absorption_issues",
    "calibration_absorption_issues",
}

BOOL_FIELDS = {
    "semantic_issue_detected",
    "evidence_boundary_respected",
    "confidence_upgrade_requested",
    "source_need_detected",
    "environment_issue_detected",
    "topic_drift_or_new_topic_detected",
    "should_ask_user",
    "should_auto_execute",
    "should_auto_adopt",
}

REFINEMENT_VERDICT_BY_STATUS = {
    STATUS_TOPIC_REFINEMENT: VERDICT_CONFIRM_REFINEMENT,
    STATUS_SOURCE_NEED: VERDICT_AUTHORIZE_SOURCE,
    STATUS_ENVIRONMENT: VERDICT_FIX_ENVIRONMENT,
    STATUS_NO_REFINEMENT: VERDICT_DO_NOT_REFINE,
    STATUS_NEW_TOPIC: VERDICT_START_NEW_TASK,
    STATUS_INSUFFICIENT: VERDICT_BLOCKED_CONTEXT,
}

HARD_BOUNDARY_STATUSES = {
    STATUS_ENVIRONMENT,
    STATUS_SOURCE_NEED,
    STATUS_NEW_TOPIC,
    STATUS_INSUFFICIENT,
}

DANGEROUS_CLAIM_PATTERNS = (
    "full_text_verified",
    "full-text verified",
    "full_text_verified: true",
    "\"full_text_verified\": true",
    "full-text verification completed",
    "full text verification completed",
    "full-text verified",
    "evidence_acquisition_completed",
    "evidence acquisition completed",
    "source acquisition completed",
    "new evidence acquired",
    "full text retrieved",
)

REVISED_FINAL_PATTERNS = (
    "revised_final_v2",
    "revised final",
    "final_v2",
    "# revised",
    "## revised",
    "candidate_v2",
    "candidate final",
)

FULL_RERUN_PATTERNS = (
    "full rerun as topic_refinement",
    "full rerun as TOPIC_REFINEMENT".lower(),
    "full pipeline rerun as topic_refinement",
    "rerun the pipeline as topic_refinement",
)


def semantic_advisory_schema() -> dict[str, Any]:
    """Return the strict advisory JSON contract for a future evaluator."""

    return {
        "contract_version": CONTRACT_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": list(REQUIRED_FIELDS),
        "properties": {
            "semantic_issue_detected": {"type": "boolean"},
            "issue_types": {"type": "array", "items": {"type": "string"}},
            "suggested_advisory_status": {"type": "string", "enum": sorted(ALLOWED_ADVISORY_STATUSES)},
            "suggested_advisory_verdict": {"type": "string", "enum": sorted(ALLOWED_ADVISORY_VERDICTS)},
            "suggested_refinement_mode": {
                "type": ["string", "null"],
                "enum": sorted([mode for mode in ALLOWED_REFINEMENT_MODES if mode is not None]) + [None],
            },
            "reasons": {"type": "array", "items": {"type": "string"}},
            "missing_obligations": {"type": "array", "items": {"type": "string"}},
            "specificity_issues": {"type": "array", "items": {"type": "string"}},
            "convergence_absorption_issues": {"type": "array", "items": {"type": "string"}},
            "calibration_absorption_issues": {"type": "array", "items": {"type": "string"}},
            "evidence_boundary_respected": {"type": "boolean"},
            "confidence_upgrade_requested": {"type": "boolean"},
            "source_need_detected": {"type": "boolean"},
            "environment_issue_detected": {"type": "boolean"},
            "topic_drift_or_new_topic_detected": {"type": "boolean"},
            "should_ask_user": {"type": "boolean"},
            "should_auto_execute": {"type": "boolean", "const": False},
            "should_auto_adopt": {"type": "boolean", "const": False},
            "evaluator_confidence": {"type": "string"},
            "false_positive_risk": {"type": "string"},
            "false_negative_risk": {"type": "string"},
        },
    }


def _clip(value: Any, max_chars: int = 6000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text[:max_chars]


def build_semantic_advisory_prompt(payload: dict[str, Any]) -> str:
    """Build a prompt contract for a future semantic evaluator.

    The returned prompt is inert text. This function does not call a model.
    """

    schema = semantic_advisory_schema()
    sections = {
        "original_user_question": payload.get("original_user_question"),
        "final_v1": payload.get("final_v1"),
        "quality_review": payload.get("quality_review"),
        "convergence_report": payload.get("convergence_report"),
        "calibration_report": payload.get("calibration_report"),
        "research_evidence_packet_or_boundary_summary": payload.get("research_evidence_packet")
        or payload.get("evidence_boundary_summary"),
        "deterministic_advisory": payload.get("deterministic_advisory"),
        "user_feedback": payload.get("user_feedback"),
    }
    rendered_sections = "\n\n".join(f"## {key}\n{_clip(value)}" for key, value in sections.items())
    return f"""# Semantic Topic Refinement Advisory Evaluator Contract

You are an optional semantic advisory evaluator for a completed Research/Decision topic.
You must output advisory JSON only. You are not an executor, source verifier, validator, or adoption authority.

Evaluate only:
- whether final_v1 answers original_user_question;
- whether user obligations are missing;
- whether final_v1 is overly templated or generic;
- whether convergence_report or calibration_report was not absorbed;
- whether tradeoffs are shallow or generic;
- whether priority/ranking merely restates the prompt rather than making a decision;
- whether same-topic refinement would create actual user value;
- whether the safe next step is stop/source_need rather than rewrite;
- whether user_feedback is same-topic continuation or new-topic/topic drift;
- whether candidate generation is worth asking the user to authorize.

Hard prohibitions:
- Do not directly edit final_v1.
- Do not generate revised_final_v2, a revised final, candidate_v2, or replacement final text.
- Do not delete caveats.
- Do not increase confidence.
- Do not suggest a full rerun as TOPIC_REFINEMENT.
- Do not claim full-text verification.
- Do not claim evidence acquisition.
- Do not execute TOPIC_REFINEMENT.
- Do not invoke or suggest automatic adapter execution.
- Do not adopt any candidate.
- Do not treat evaluator self-score as validator pass.
- Do not override deterministic hard-boundary advisory. If deterministic says SOURCE_NEED, ENVIRONMENT_TRIAGE,
  NEW_TOPIC_OR_FULL_RERUN, or INSUFFICIENT_ARTIFACTS, respect that boundary.

Output requirements:
- Return strict JSON only, with no markdown wrapper and no prose outside JSON.
- The JSON must conform exactly to this schema:
{json.dumps(schema, indent=2, ensure_ascii=False)}

Input bundle:
{rendered_sections}
"""


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _contains_any(text: str, patterns: tuple[str, ...]) -> str | None:
    lower = text.lower()
    for pattern in patterns:
        if pattern.lower() in lower:
            return pattern
    return None


def validate_semantic_advisory_output(output: dict[str, Any]) -> dict[str, Any]:
    """Validate future semantic evaluator JSON without executing anything."""

    errors: list[dict[str, str]] = []
    if not isinstance(output, dict):
        return {"valid": False, "status": "INVALID_SEMANTIC_ADVISORY_OUTPUT", "errors": [{"code": "invalid_type", "message": "output must be a dict"}]}

    for field in REQUIRED_FIELDS:
        if field not in output:
            errors.append({"code": "missing_required_field", "field": field, "message": f"missing required field: {field}"})

    for field in output:
        if field not in REQUIRED_FIELDS:
            errors.append({"code": "unexpected_field", "field": field, "message": f"unexpected field: {field}"})

    for field in LIST_FIELDS:
        if field in output and not isinstance(output[field], list):
            errors.append({"code": "invalid_field_type", "field": field, "message": f"{field} must be a list"})

    for field in BOOL_FIELDS:
        if field in output and not isinstance(output[field], bool):
            errors.append({"code": "invalid_field_type", "field": field, "message": f"{field} must be a bool"})

    status = output.get("suggested_advisory_status")
    verdict = output.get("suggested_advisory_verdict")
    mode = output.get("suggested_refinement_mode")

    if "suggested_advisory_status" in output and status not in ALLOWED_ADVISORY_STATUSES:
        errors.append({"code": "invalid_advisory_status", "field": "suggested_advisory_status", "message": f"invalid status: {status}"})
    if "suggested_advisory_verdict" in output and verdict not in ALLOWED_ADVISORY_VERDICTS:
        errors.append({"code": "invalid_advisory_verdict", "field": "suggested_advisory_verdict", "message": f"invalid verdict: {verdict}"})
    if mode not in ALLOWED_REFINEMENT_MODES:
        errors.append({"code": "invalid_refinement_mode", "field": "suggested_refinement_mode", "message": f"invalid mode: {mode}"})
    if status in REFINEMENT_VERDICT_BY_STATUS and verdict != REFINEMENT_VERDICT_BY_STATUS[status]:
        errors.append({"code": "status_verdict_mismatch", "message": f"{status} requires {REFINEMENT_VERDICT_BY_STATUS[status]}"})

    if output.get("should_auto_execute") is True:
        errors.append({"code": "auto_execute_not_allowed", "field": "should_auto_execute", "message": "semantic advisory must not auto execute"})
    if output.get("should_auto_adopt") is True:
        errors.append({"code": "auto_adopt_not_allowed", "field": "should_auto_adopt", "message": "semantic advisory must not auto adopt"})
    if output.get("confidence_upgrade_requested") is True:
        errors.append({"code": "confidence_upgrade_not_allowed", "field": "confidence_upgrade_requested", "message": "semantic advisory cannot request confidence upgrade"})
    if status == STATUS_TOPIC_REFINEMENT and output.get("evidence_boundary_respected") is False:
        errors.append({"code": "evidence_boundary_not_respected", "message": "TOPIC_REFINEMENT requires evidence_boundary_respected=true"})
    if status == STATUS_TOPIC_REFINEMENT and output.get("source_need_detected") is True:
        errors.append({"code": "source_need_outranks_refinement", "message": "source_need must not be converted to TOPIC_REFINEMENT"})
    if status == STATUS_TOPIC_REFINEMENT and output.get("environment_issue_detected") is True:
        errors.append({"code": "environment_outranks_refinement", "message": "environment issue must not be converted to TOPIC_REFINEMENT"})
    if status == STATUS_TOPIC_REFINEMENT and output.get("topic_drift_or_new_topic_detected") is True:
        errors.append({"code": "new_topic_outranks_refinement", "message": "new topic must not be converted to TOPIC_REFINEMENT"})

    flattened = _flatten(output)
    if status == STATUS_TOPIC_REFINEMENT and _contains_any(flattened, FULL_RERUN_PATTERNS):
        errors.append({"code": "full_rerun_as_refinement_not_allowed", "message": "full rerun must not be suggested as TOPIC_REFINEMENT"})
    if _contains_any(flattened, REVISED_FINAL_PATTERNS):
        errors.append({"code": "revised_final_body_not_allowed", "message": "semantic advisory must not include revised final or candidate body"})
    dangerous = _contains_any(flattened, DANGEROUS_CLAIM_PATTERNS)
    if dangerous:
        code = "full_text_verification_claim_not_allowed" if "verification" in dangerous.lower() or "full" in dangerous.lower() else "evidence_acquisition_claim_not_allowed"
        errors.append({"code": code, "message": f"dangerous claim not allowed: {dangerous}"})

    return {
        "valid": not errors,
        "status": "PASS_SEMANTIC_ADVISORY_OUTPUT_VALIDATION" if not errors else "INVALID_SEMANTIC_ADVISORY_OUTPUT",
        "errors": errors,
        "no_model_called": True,
        "no_adapter_called": True,
        "no_pipeline_rerun": True,
        "no_candidate_generated": True,
    }


def _det_status(deterministic: dict[str, Any]) -> str | None:
    return deterministic.get("advisory_status") or deterministic.get("suggested_advisory_status")


def _det_verdict(deterministic: dict[str, Any]) -> str | None:
    return deterministic.get("advisory_verdict") or deterministic.get("suggested_advisory_verdict")


def _merged_base(deterministic: dict[str, Any], semantic: dict[str, Any], semantic_validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "deterministic_advisory": deterministic,
        "semantic_advisory": semantic,
        "semantic_validation": semantic_validation,
        "auto_execution": False,
        "auto_adoption": False,
        "confidence_upgrade_allowed": False,
        "no_model_called": True,
        "no_adapter_called": True,
        "no_pipeline_rerun": True,
        "no_candidate_generated": True,
    }


def _copy_deterministic_result(base: dict[str, Any], deterministic: dict[str, Any], reason: str) -> dict[str, Any]:
    status = _det_status(deterministic)
    verdict = _det_verdict(deterministic) or REFINEMENT_VERDICT_BY_STATUS.get(status)
    base.update(
        {
            "advisory_status": status,
            "advisory_verdict": verdict,
            "suggested_refinement_mode": deterministic.get("suggested_refinement_mode"),
            "source": "deterministic",
            "merge_reason": reason,
            "requires_user_confirmation": status == STATUS_TOPIC_REFINEMENT,
        }
    )
    return base


def _copy_semantic_result(base: dict[str, Any], semantic: dict[str, Any], reason: str) -> dict[str, Any]:
    status = semantic.get("suggested_advisory_status")
    base.update(
        {
            "advisory_status": status,
            "advisory_verdict": semantic.get("suggested_advisory_verdict"),
            "suggested_refinement_mode": semantic.get("suggested_refinement_mode"),
            "source": "semantic_advisory",
            "merge_reason": reason,
            "requires_user_confirmation": status == STATUS_TOPIC_REFINEMENT,
        }
    )
    return base


def merge_deterministic_and_semantic_advisory(deterministic: dict[str, Any], semantic: dict[str, Any]) -> dict[str, Any]:
    """Merge R3A and future semantic advisory while preserving hard gates."""

    validation = validate_semantic_advisory_output(semantic)
    base = _merged_base(deterministic, semantic, validation)
    det_status = _det_status(deterministic)
    sem_status = semantic.get("suggested_advisory_status") if validation["valid"] else None

    if not validation["valid"]:
        return _copy_deterministic_result(base, deterministic, "semantic advisory invalid; deterministic result retained")
    if det_status == STATUS_ENVIRONMENT:
        return _copy_deterministic_result(base, deterministic, "deterministic environment triage outranks semantic advisory")
    if det_status == STATUS_SOURCE_NEED:
        return _copy_deterministic_result(base, deterministic, "deterministic source_need outranks semantic advisory")
    if det_status == STATUS_NEW_TOPIC:
        return _copy_deterministic_result(base, deterministic, "deterministic new-topic/full-rerun boundary outranks semantic advisory")
    if det_status == STATUS_INSUFFICIENT and sem_status != STATUS_NO_REFINEMENT:
        return _copy_deterministic_result(base, deterministic, "deterministic insufficient-artifacts boundary retained")
    if det_status == STATUS_NO_REFINEMENT and sem_status == STATUS_TOPIC_REFINEMENT:
        return _copy_semantic_result(base, semantic, "semantic advisory may suggest same-topic refinement, advisory only")
    if det_status == STATUS_NO_REFINEMENT and sem_status == STATUS_NO_REFINEMENT:
        return _copy_deterministic_result(base, deterministic, "both detectors do not suggest refinement")
    if det_status == STATUS_TOPIC_REFINEMENT:
        return _copy_deterministic_result(base, deterministic, "deterministic refinement suggestion retained; semantic advisory remains advisory context")
    return _copy_deterministic_result(base, deterministic, "deterministic advisory retained by default")
