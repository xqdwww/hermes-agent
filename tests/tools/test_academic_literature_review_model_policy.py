from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = (
    REPO_ROOT
    / "optional-skills"
    / "research-decision"
    / "academic-literature-review-writer"
    / "SKILL.md"
)


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_online_acquisition_default_locked():
    text = _skill_text()

    assert "## online_literature_acquisition_default" in text
    assert "`auto_online_acquisition_default: true`" in text
    assert "`source_corpus_required_by_default: false`" in text
    assert "User-provided papers, PDFs, BibTeX files" in text
    assert "not required by default" in text
    assert "`source_discovery_not_evidence: true`" in text
    assert "discovery leads only" in text


def test_quality_first_fixed_model_chain_locked():
    text = _skill_text()

    for marker in [
        "## model_execution_policy",
        "`quality_first_default: true`",
        "`stability_over_speed: true`",
        "`fixed_model_chain_required: true`",
        "`executor_model_choice: forbidden`",
        "`source_discovery_model: GPT Bridge primary`",
        "`final_writer_primary: GPT Bridge primary`",
        "`final_writer_fallback: Gemini 3.1 Pro High`",
    ]:
        assert marker in text

    assert "executor does not choose models ad hoc" in text


def test_no_9b_and_local_executor_limits_locked():
    text = _skill_text()

    assert "`no_9b_executor: true`" in text
    assert "9B models must not enter this skill execution chain" in text
    assert "FAIL_FORBIDDEN_9B_EXECUTOR" in text
    assert "`minimum_local_executor: 27B+`" in text
    assert "formatting, normalization, metadata cleanup" in text
    assert "non-claim support" in text
    assert "must not create, rewrite, evaluate, calibrate, or repair scholarly claims" in text
    assert "FAIL_LOCAL_EXECUTOR_BELOW_27B" in text
    assert "FAIL_LOCAL_EXECUTOR_USED_FOR_CLAIMS" in text


def test_calibration_and_validator_authority_locked():
    text = _skill_text()

    assert "`external_calibrator_must_differ_from_writer: true`" in text
    assert "External calibration must use a model different from the final writer" in text
    assert "BLOCKED_EXTERNAL_CALIBRATOR_NOT_SEPARATE" in text
    assert "`deterministic_validator_final_gate: true`" in text
    assert "deterministic `academic_literature_review_contract` validator is the final gate" in text
    assert "No model output can override validator failures" in text
    assert "FAIL_VALIDATOR_NOT_FINAL_GATE" in text


def test_forbidden_final_writers_locked():
    text = _skill_text()

    assert "`forbidden_final_writers`" in text
    for forbidden in [
        "9B models",
        "local lightweight executors",
        "27B local executors",
        "metadata cleanup executors",
        "source discovery executors",
        "external calibrators",
        "any unlisted model",
    ]:
        assert forbidden in text
