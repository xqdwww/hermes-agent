from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tools.skills_tool import skill_view, skills_list


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = (
    REPO_ROOT
    / "optional-skills"
    / "research-decision"
    / "academic-literature-review-writer"
)
SKILL_PATH = SKILL_DIR / "SKILL.md"
RESEARCH_DECISION_SKILLS_ROOT = REPO_ROOT / "optional-skills" / "research-decision"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _normalized_skill_text() -> str:
    return _skill_text().lower().replace("_", "-")


def test_skill_file_exists():
    assert SKILL_PATH.exists()
    assert SKILL_PATH.is_file()


def test_required_contract_sections_present():
    text = _skill_text()
    required_sections = [
        "purpose",
        "when_to_use",
        "when_not_to_use",
        "input_contract",
        "evidence_tiers",
        "extraction_schema",
        "synthesis_schema",
        "output_contract",
        "academic_quality_standard",
        "anti_patchwork_rule",
        "synthesis_requirement",
        "paragraph_quality_rule",
        "academic_review_rubric",
        "structure_requirement",
        "literature_review_vs_annotated_bibliography",
        "quality_gates",
        "failure_modes",
        "review_types",
        "writing_rules",
        "integration_with_research_decision",
        "corpus_size_policy",
        "acceptance_tests",
        "final_response_policy",
    ]

    for section in required_sections:
        assert f"## {section}" in text


def test_evidence_tier_rules_are_strict():
    text = _skill_text()
    lowered = text.lower()

    for tier in [
        "full_text_verified",
        "full_text_partial",
        "abstract_only",
        "metadata_only",
        "search_snippet_only",
        "secondary_summary",
    ]:
        assert f"`{tier}`" in text

    assert "only `full_text_verified` sources may support strong scholarly claims" in lowered
    assert "abstract_only` sources may only support preliminary characterization" in lowered
    assert "metadata_only` must not support substantive scholarly claims" in lowered
    assert "search_snippet_only` must not support scholarly claims" in lowered


def test_output_contract_declares_required_artifacts():
    text = _skill_text()

    for output_file in [
        "literature_review.md",
        "claim_citation_table.md",
        "evidence_matrix.csv",
        "paper_index.md",
        "method_taxonomy.md",
        "debate_map.md",
        "gap_and_future_work.md",
        "bibliography.bib",
        "provenance.json",
        "quality_gate_report.md",
    ]:
        assert f"`{output_file}`" in text


def test_academic_rubric_threshold_locked():
    text = _skill_text()
    lowered = text.lower()

    assert "100-point scale" in lowered
    assert "a score below 80 cannot pass" in lowered
    assert "fail_academic_quality_below_threshold" in lowered
    assert "90-100" in text
    assert "80-89" in text
    assert "70-79" in text
    assert "If `rubric_score < 80`, set final status" in text

    for rubric_category in [
        "Research question and scope clarity",
        "Corpus relevance and coverage",
        "Conceptual/theoretical framing",
        "Cross-literature synthesis quality",
        "Methodological comparison and evidence appraisal",
        "Debate, contradiction, and counter-evidence handling",
        "Gap analysis and future research directions",
        "Citation rigor and claim-source traceability",
    ]:
        assert rubric_category in text


def test_anti_patchwork_failure_locked():
    normalized = _normalized_skill_text()

    assert "patchwork literature reviews are forbidden" in normalized
    assert "citation dumping" in normalized
    assert "annotated bibliography" in normalized
    assert "paper-by-paper summary" in normalized
    assert "use synonym rewriting to disguise summary as synthesis" in normalized
    assert "fail-patchwork-review" in normalized
    assert "fail-annotated-bibliography-only" in normalized
    assert "fail-no-cross-source-synthesis" in normalized


def test_claim_traceability_locked():
    text = _skill_text()

    for trace_field in [
        "citation_key",
        "paper_id",
        "source_anchor",
        "evidence_tier",
        "claim_strength",
    ]:
        assert f"`{trace_field}`" in text

    for gate in [
        "no_uncited_key_claims",
        "no_fake_citations",
        "no_fake_doi",
        "claim_source_traceability_required",
    ]:
        assert f"`{gate}`" in text


def test_corpus_size_policy_locked():
    lowered = _skill_text().lower()

    assert "3-5 full-text papers can support at most a `mini_review`" in lowered
    assert "abstract-only or partial-text corpora can support only a `preliminary_review`" in lowered
    assert "must not be described as a completed field-level literature review" in lowered
    assert "without `full_text_verified` evidence, do not make strong consensus claims" in lowered


def test_acceptance_tests_declared():
    text = _skill_text()

    for acceptance_test in [
        "small_full_text_corpus_mini_review",
        "contradictory_findings_debate_map",
        "abstract_only_corpus_blocks_strong_claims",
        "search_snippet_downgrade",
        "cross_disciplinary_method_taxonomy",
        "patchwork_negative_test",
        "academic_rubric_threshold_test",
    ]:
        assert acceptance_test in text


def test_skill_is_discoverable_when_research_decision_optional_root_is_skill_root():
    with (
        patch("tools.skills_tool.SKILLS_DIR", RESEARCH_DECISION_SKILLS_ROOT),
        patch("tools.skills_tool._get_disabled_skill_names", return_value=set()),
        patch("tools.skills_tool._is_skill_disabled", return_value=False),
        patch("agent.skill_utils.get_external_skills_dirs", return_value=[]),
    ):
        listed = json.loads(skills_list())
        viewed = json.loads(skill_view("academic-literature-review-writer"))

    matching = [
        skill
        for skill in listed["skills"]
        if skill["name"] == "research-decision-academic-literature-review-writer"
    ]
    assert matching
    assert "academic literature reviews" in matching[0]["description"]
    assert viewed["success"] is True
    assert viewed["name"] == "research-decision-academic-literature-review-writer"
    assert "## evidence_tiers" in viewed["content"]
    assert "FAIL_PATCHWORK_REVIEW" in viewed["content"]
