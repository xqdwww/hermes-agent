from __future__ import annotations

import importlib
from pathlib import Path

from tools import topic_refinement_semantic_advisory_contract as contract


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SOURCE = REPO_ROOT / "tools/topic_refinement_semantic_advisory_contract.py"


def _semantic(status: str, **overrides) -> dict:
    output = {
        "semantic_issue_detected": status == contract.STATUS_TOPIC_REFINEMENT,
        "issue_types": [],
        "suggested_advisory_status": status,
        "suggested_advisory_verdict": contract.REFINEMENT_VERDICT_BY_STATUS[status],
        "suggested_refinement_mode": None,
        "reasons": [],
        "missing_obligations": [],
        "specificity_issues": [],
        "convergence_absorption_issues": [],
        "calibration_absorption_issues": [],
        "evidence_boundary_respected": True,
        "confidence_upgrade_requested": False,
        "source_need_detected": status == contract.STATUS_SOURCE_NEED,
        "environment_issue_detected": status == contract.STATUS_ENVIRONMENT,
        "topic_drift_or_new_topic_detected": status == contract.STATUS_NEW_TOPIC,
        "should_ask_user": status in {contract.STATUS_TOPIC_REFINEMENT, contract.STATUS_SOURCE_NEED, contract.STATUS_ENVIRONMENT},
        "should_auto_execute": False,
        "should_auto_adopt": False,
        "evaluator_confidence": "medium",
        "false_positive_risk": "medium",
        "false_negative_risk": "medium",
    }
    if status == contract.STATUS_TOPIC_REFINEMENT:
        output["suggested_refinement_mode"] = "section_rewrite"
    if status == contract.STATUS_SOURCE_NEED:
        output["suggested_refinement_mode"] = "targeted_evidence_acquisition"
    if status == contract.STATUS_ENVIRONMENT:
        output["suggested_refinement_mode"] = "environment_triage"
    output.update(overrides)
    return output


def test_missing_obligation_semantic_issue_suggests_topic_refinement() -> None:
    output = _semantic(
        contract.STATUS_TOPIC_REFINEMENT,
        issue_types=["missing_user_obligation"],
        missing_obligations=["answer the ranking question with a concrete choice"],
        reasons=["A required user obligation is not answered."],
    )

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is True
    assert output["suggested_advisory_status"] == contract.STATUS_TOPIC_REFINEMENT


def test_shallow_final_semantic_issue_suggests_topic_refinement() -> None:
    output = _semantic(
        contract.STATUS_TOPIC_REFINEMENT,
        issue_types=["too_generic", "weak_tradeoff"],
        specificity_issues=["tradeoff language is generic and not decision-useful"],
        reasons=["Refinement would add practical user value."],
    )

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is True
    assert output["suggested_refinement_mode"] == "section_rewrite"


def test_source_need_semantic_case_suggests_source_need_not_refinement() -> None:
    output = _semantic(
        contract.STATUS_SOURCE_NEED,
        issue_types=["source_need_should_stop"],
        reasons=["Evidence is insufficient for a stronger answer."],
    )

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is True
    assert output["suggested_advisory_status"] == contract.STATUS_SOURCE_NEED
    assert output["suggested_advisory_status"] != contract.STATUS_TOPIC_REFINEMENT


def test_environment_semantic_case_suggests_environment_triage() -> None:
    output = _semantic(
        contract.STATUS_ENVIRONMENT,
        issue_types=["environment_blocker"],
        reasons=["Execution artifacts show service unhealthy."],
    )

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is True
    assert output["suggested_advisory_verdict"] == contract.VERDICT_FIX_ENVIRONMENT


def test_new_topic_semantic_case_suggests_start_new_task() -> None:
    output = _semantic(
        contract.STATUS_NEW_TOPIC,
        issue_types=["topic_drift"],
        reasons=["User feedback asks for a different topic."],
    )

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is True
    assert output["suggested_advisory_verdict"] == contract.VERDICT_START_NEW_TASK


def test_high_quality_final_suggests_no_refinement() -> None:
    output = _semantic(
        contract.STATUS_NO_REFINEMENT,
        semantic_issue_detected=False,
        issue_types=["no_actionable_semantic_issue"],
        reasons=["Final appears obligation-complete and specific."],
        should_ask_user=False,
    )

    result = contract.validate_semantic_advisory_output(output)

    assert result["valid"] is True
    assert output["suggested_advisory_status"] == contract.STATUS_NO_REFINEMENT


def test_prompt_builder_performs_no_model_call() -> None:
    prompt = contract.build_semantic_advisory_prompt(
        {
            "original_user_question": "Question",
            "final_v1": "Final",
            "quality_review": "Review",
            "deterministic_advisory": {"advisory_status": contract.STATUS_NO_REFINEMENT},
        }
    )

    assert isinstance(prompt, str)
    assert "strict JSON" in prompt
    assert not hasattr(contract, "call_model")
    assert not hasattr(contract, "MODEL_CLIENT")


def test_module_has_no_network_api_or_runtime_imports() -> None:
    source = CONTRACT_SOURCE.read_text(encoding="utf-8")
    forbidden = [
        "openai",
        "anthropic",
        "requests",
        "urllib",
        "httpx",
        "aiohttp",
        "api_key",
        "os.environ",
        "topic_refinement_registry_adapter",
        "topic_refinement_manual_task",
        "topic_refinement_post_final_advisory_detector",
        "final_controller",
        "task_engine",
    ]

    for token in forbidden:
        assert token not in source


def test_import_has_no_side_effects() -> None:
    module = importlib.reload(contract)

    assert module.CONTRACT_VERSION == contract.CONTRACT_VERSION
    assert module.semantic_advisory_schema()["contract_version"] == contract.CONTRACT_VERSION
