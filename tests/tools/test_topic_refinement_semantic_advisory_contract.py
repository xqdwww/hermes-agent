from __future__ import annotations

from tools import topic_refinement_semantic_advisory_contract as contract


def _payload() -> dict:
    return {
        "original_user_question": "Pick an execution architecture.",
        "final_v1": "The final picks a stack but remains shallow.",
        "quality_review": "No explicit keyword signal.",
        "convergence_report": "Convergence noted operational constraints.",
        "calibration_report": "Caveats must be preserved.",
        "research_evidence_packet": "Evidence is bounded.",
        "deterministic_advisory": {"advisory_status": contract.STATUS_NO_REFINEMENT},
        "user_feedback": "same topic, make the decision useful",
    }


def _valid(**overrides) -> dict:
    output = {
        "semantic_issue_detected": True,
        "issue_types": ["missing_user_obligation"],
        "suggested_advisory_status": contract.STATUS_TOPIC_REFINEMENT,
        "suggested_advisory_verdict": contract.VERDICT_CONFIRM_REFINEMENT,
        "suggested_refinement_mode": "section_rewrite",
        "reasons": ["The final does not satisfy a required decision obligation."],
        "missing_obligations": ["explicit architecture ranking rationale"],
        "specificity_issues": [],
        "convergence_absorption_issues": [],
        "calibration_absorption_issues": [],
        "evidence_boundary_respected": True,
        "confidence_upgrade_requested": False,
        "source_need_detected": False,
        "environment_issue_detected": False,
        "topic_drift_or_new_topic_detected": False,
        "should_ask_user": True,
        "should_auto_execute": False,
        "should_auto_adopt": False,
        "evaluator_confidence": "medium",
        "false_positive_risk": "medium",
        "false_negative_risk": "medium",
    }
    output.update(overrides)
    return output


def _det(status: str, **extra) -> dict:
    verdict = contract.REFINEMENT_VERDICT_BY_STATUS[status]
    payload = {
        "advisory_status": status,
        "advisory_verdict": verdict,
        "suggested_refinement_mode": None,
        "requires_user_confirmation": status == contract.STATUS_TOPIC_REFINEMENT,
        "auto_execution": False,
        "auto_adoption": False,
    }
    payload.update(extra)
    return payload


def test_prompt_contains_required_input_sections() -> None:
    prompt = contract.build_semantic_advisory_prompt(_payload())

    for section in [
        "original_user_question",
        "final_v1",
        "quality_review",
        "convergence_report",
        "calibration_report",
        "research_evidence_packet_or_boundary_summary",
        "deterministic_advisory",
        "user_feedback",
    ]:
        assert section in prompt


def test_prompt_forbids_revised_final_generation() -> None:
    prompt = contract.build_semantic_advisory_prompt(_payload())

    assert "Do not generate revised_final_v2" in prompt
    assert "Do not directly edit final_v1" in prompt


def test_prompt_forbids_confidence_upgrade() -> None:
    prompt = contract.build_semantic_advisory_prompt(_payload())

    assert "Do not increase confidence" in prompt


def test_prompt_forbids_full_text_verification_claim() -> None:
    prompt = contract.build_semantic_advisory_prompt(_payload())

    assert "Do not claim full-text verification" in prompt


def test_prompt_requires_strict_json() -> None:
    prompt = contract.build_semantic_advisory_prompt(_payload())

    assert "Return strict JSON only" in prompt
    assert "suggested_advisory_status" in prompt


def test_prompt_states_advisory_only_no_auto_execute_or_adopt() -> None:
    prompt = contract.build_semantic_advisory_prompt(_payload())

    assert "advisory JSON only" in prompt
    assert "Do not execute TOPIC_REFINEMENT" in prompt
    assert "Do not adopt any candidate" in prompt


def test_schema_contains_required_fields_and_enums() -> None:
    schema = contract.semantic_advisory_schema()

    assert set(contract.REQUIRED_FIELDS) == set(schema["required"])
    assert contract.STATUS_TOPIC_REFINEMENT in schema["properties"]["suggested_advisory_status"]["enum"]
    assert contract.VERDICT_CONFIRM_REFINEMENT in schema["properties"]["suggested_advisory_verdict"]["enum"]
    assert "section_rewrite" in schema["properties"]["suggested_refinement_mode"]["enum"]


def test_valid_semantic_advisory_passes() -> None:
    result = contract.validate_semantic_advisory_output(_valid())

    assert result["valid"] is True
    assert result["status"] == "PASS_SEMANTIC_ADVISORY_OUTPUT_VALIDATION"
    assert result["no_model_called"] is True


def test_missing_required_field_fails() -> None:
    output = _valid()
    output.pop("semantic_issue_detected")

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is False
    assert any(error["code"] == "missing_required_field" for error in result["errors"])


def test_invalid_status_fails() -> None:
    result = contract.validate_semantic_advisory_output(_valid(suggested_advisory_status="REWRITE_NOW"))

    assert result["valid"] is False
    assert any(error["code"] == "invalid_advisory_status" for error in result["errors"])


def test_invalid_verdict_fails() -> None:
    result = contract.validate_semantic_advisory_output(_valid(suggested_advisory_verdict="AUTO_RUN"))

    assert result["valid"] is False
    assert any(error["code"] == "invalid_advisory_verdict" for error in result["errors"])


def test_invalid_refinement_mode_fails() -> None:
    result = contract.validate_semantic_advisory_output(_valid(suggested_refinement_mode="rewrite_everything"))

    assert result["valid"] is False
    assert any(error["code"] == "invalid_refinement_mode" for error in result["errors"])


def test_should_auto_execute_true_fails() -> None:
    result = contract.validate_semantic_advisory_output(_valid(should_auto_execute=True))

    assert result["valid"] is False
    assert any(error["code"] == "auto_execute_not_allowed" for error in result["errors"])


def test_should_auto_adopt_true_fails() -> None:
    result = contract.validate_semantic_advisory_output(_valid(should_auto_adopt=True))

    assert result["valid"] is False
    assert any(error["code"] == "auto_adopt_not_allowed" for error in result["errors"])


def test_confidence_upgrade_requested_true_fails() -> None:
    result = contract.validate_semantic_advisory_output(_valid(confidence_upgrade_requested=True))

    assert result["valid"] is False
    assert any(error["code"] == "confidence_upgrade_not_allowed" for error in result["errors"])


def test_source_need_plus_topic_refinement_fails() -> None:
    result = contract.validate_semantic_advisory_output(_valid(source_need_detected=True))

    assert result["valid"] is False
    assert any(error["code"] == "source_need_outranks_refinement" for error in result["errors"])


def test_environment_issue_plus_topic_refinement_fails() -> None:
    result = contract.validate_semantic_advisory_output(_valid(environment_issue_detected=True))

    assert result["valid"] is False
    assert any(error["code"] == "environment_outranks_refinement" for error in result["errors"])


def test_evidence_boundary_not_respected_fails() -> None:
    result = contract.validate_semantic_advisory_output(_valid(evidence_boundary_respected=False))

    assert result["valid"] is False
    assert any(error["code"] == "evidence_boundary_not_respected" for error in result["errors"])


def test_revised_final_body_in_output_fails() -> None:
    output = _valid()
    output["revised_final_v2"] = "Replace final_v1 with this answer."

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is False
    assert any(error["code"] == "revised_final_body_not_allowed" for error in result["errors"])


def test_full_text_verification_completed_claim_fails() -> None:
    output = _valid(reasons=["full-text verification completed"])

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is False
    assert any(error["code"] == "full_text_verification_claim_not_allowed" for error in result["errors"])


def test_evidence_acquisition_completed_claim_fails() -> None:
    output = _valid(reasons=["evidence acquisition completed"])

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is False
    assert any(error["code"] == "evidence_acquisition_claim_not_allowed" for error in result["errors"])


def test_full_rerun_as_topic_refinement_fails() -> None:
    output = _valid(reasons=["full rerun as TOPIC_REFINEMENT"])

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is False
    assert any(error["code"] == "full_rerun_as_refinement_not_allowed" for error in result["errors"])


def test_environment_deterministic_wins_over_semantic_refinement() -> None:
    merged = contract.merge_deterministic_and_semantic_advisory(_det(contract.STATUS_ENVIRONMENT), _valid())

    assert merged["advisory_status"] == contract.STATUS_ENVIRONMENT
    assert merged["source"] == "deterministic"


def test_source_need_deterministic_wins_over_semantic_refinement() -> None:
    merged = contract.merge_deterministic_and_semantic_advisory(_det(contract.STATUS_SOURCE_NEED), _valid())

    assert merged["advisory_status"] == contract.STATUS_SOURCE_NEED
    assert merged["source"] == "deterministic"


def test_new_topic_deterministic_wins_over_semantic_refinement() -> None:
    merged = contract.merge_deterministic_and_semantic_advisory(_det(contract.STATUS_NEW_TOPIC), _valid())

    assert merged["advisory_status"] == contract.STATUS_NEW_TOPIC
    assert merged["source"] == "deterministic"


def test_insufficient_artifacts_deterministic_wins() -> None:
    merged = contract.merge_deterministic_and_semantic_advisory(_det(contract.STATUS_INSUFFICIENT), _valid())

    assert merged["advisory_status"] == contract.STATUS_INSUFFICIENT
    assert merged["source"] == "deterministic"


def test_semantic_can_suggest_refinement_when_deterministic_no_refinement() -> None:
    merged = contract.merge_deterministic_and_semantic_advisory(_det(contract.STATUS_NO_REFINEMENT), _valid())

    assert merged["advisory_status"] == contract.STATUS_TOPIC_REFINEMENT
    assert merged["source"] == "semantic_advisory"


def test_merged_topic_refinement_requires_user_confirmation() -> None:
    merged = contract.merge_deterministic_and_semantic_advisory(_det(contract.STATUS_NO_REFINEMENT), _valid())

    assert merged["requires_user_confirmation"] is True


def test_merged_advisory_never_auto_executes_or_adopts() -> None:
    merged = contract.merge_deterministic_and_semantic_advisory(_det(contract.STATUS_NO_REFINEMENT), _valid())

    assert merged["auto_execution"] is False
    assert merged["auto_adoption"] is False
    assert merged["confidence_upgrade_allowed"] is False
