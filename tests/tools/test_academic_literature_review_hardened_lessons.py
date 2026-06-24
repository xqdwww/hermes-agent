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


def test_hardened_execution_lessons_declared():
    text = _skill_text()

    assert "## hardened_execution_lessons" in text
    for lesson in [
        "passive_boundary",
        "intake_first",
        "git_scope_guard",
        "head_stability",
        "no_acceptance_shell",
        "source_discovery_not_evidence",
        "no_fake_repair",
        "strong_model_or_block",
        "calibration_separation",
        "deterministic_validator_authority",
        "failure_first",
        "route_pollution_guard",
        "provenance",
        "runtime_mutation_guard",
    ]:
        assert f"`{lesson}`" in text


def test_runtime_boundary_lessons_are_hard_rules():
    text = _skill_text()

    for phrase in [
        "Keep this as a passive optional skill",
        "Do not turn it into a Research runtime route",
        "Do not modify TaskMode",
        "Research / Decision routing",
        "task-engine core",
        "Do not mutate Research engine runtime behavior",
        "FAIL_RUNTIME_MUTATION_ATTEMPTED",
    ]:
        assert phrase in text


def test_evidence_and_repair_lessons_are_locked():
    text = _skill_text()

    for phrase in [
        "Discovery results, search snippets, rankings, and metadata are retrieval leads",
        "not scholarly evidence",
        "Do not invent missing DOI values, citations, anchors, papers, methods, or findings",
        "FAIL_SOURCE_DISCOVERY_USED_AS_EVIDENCE",
        "BLOCKED_NO_SOURCES",
    ]:
        assert phrase in text


def test_model_calibration_validator_lessons_are_locked():
    text = _skill_text()

    for phrase in [
        "Use the fixed high-capability model chain",
        "if only weak executors are available, block or downgrade",
        "Keep external calibration separate from the final writer",
        "Treat deterministic validator failure as authoritative",
        "Prefer explicit failure codes over fluent but unsupported output",
    ]:
        assert phrase in text


def test_provenance_lesson_records_model_and_validation_context():
    text = _skill_text()

    for phrase in [
        "Preserve source paths, URLs, DOIs",
        "evidence tiers",
        "anchors",
        "acquisition dates",
        "model roles",
        "validator results",
        "downgrade reasons",
    ]:
        assert phrase in text
