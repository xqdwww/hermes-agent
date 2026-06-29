from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = (
    ROOT
    / "optional-skills/research-decision/topic-refinement-loop-operator/SKILL.md"
)
REVIEW_PATH = (
    ROOT
    / "optional-skills/research-decision/topic-refinement-loop-operator/"
    "references/external_pattern_review.md"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalized(text: str) -> str:
    return " ".join(text.split())


def assert_contains_all(text: str, needles: list[str], label: str) -> None:
    flat = normalized(text)
    missing = [needle for needle in needles if needle not in flat]
    assert not missing, f"{label} missing required wording: {missing}"


def test_skill_file_exists() -> None:
    assert SKILL_PATH.exists()


def test_external_pattern_review_exists() -> None:
    assert REVIEW_PATH.exists()


def test_skill_frontmatter_exists_and_contains_name_description() -> None:
    text = read(SKILL_PATH)
    assert text.startswith("---\n")
    assert "name: research-decision-topic-refinement-loop" in text
    assert "description:" in text
    assert "targeted refinement rather than a full rerun" in text


def test_core_sections_exist() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "## Purpose",
            "## Trigger / When to use",
            "## When not to use",
            "## Required inputs",
        ],
        "core sections",
    )


def test_topic_refinement_state_exists() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "topic_refinement_state",
            "topic_id",
            "current_final_version",
            "artifact_paths",
            "quality_failures",
            "refinement_history",
            "preserved_caveats",
            "unresolved_evidence_gaps",
            "next_action",
            "stop_reason",
        ],
        "topic state model",
    )


def test_failure_taxonomy_exists() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "## Failure taxonomy",
            "final_template_fallback",
            "low_domain_specificity",
            "missing_user_obligation",
            "weak_priority_ranking",
            "generic_topn_items",
            "calibration_absorption_gap",
            "convergence_to_final_specificity_loss",
            "evidence_gap_needs_acquisition",
            "evidence_gap_needs_full_text_verification",
            "thin_evidence_must_remain_conditional",
            "raw_internal_metadata_leakage",
            "wrong_domain_or_stale_output",
            "executor_or_environment_blocker",
            "user_feedback_requests_deeper_specificity",
        ],
        "failure taxonomy",
    )


def test_failure_to_next_action_mapping_exists() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "## Failure-to-next-action mapping",
            "section_rewrite",
            "final_absorption_pass",
            "targeted source acquisition",
            "Preserve caveats and do not upgrade thin evidence",
            "Run environment triage",
        ],
        "failure mapping",
    )


def test_refinement_modes_exist() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "## Refinement modes",
            "section_rewrite",
            "final_absorption_pass",
            "targeted_convergence_refinement",
            "targeted_evidence_acquisition",
            "user_feedback_refinement",
            "environment_triage",
        ],
        "refinement modes",
    )


def test_workflow_output_stop_and_antipattern_sections_exist() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "## Refinement workflow checklist",
            "## Refinement output contract",
            "## Stop conditions",
            "## Anti-patterns",
            "dirty worktree",
            "branch-head mismatch",
            "what changed / what did not change",
        ],
        "workflow and guards",
    )


def test_examples_and_handoff_template_exist() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "## Example workflows",
            "case03 architecture final too generic",
            "case05 travel priority copied prompt order",
            "case06 education research support too generic",
            "case04 business convergence missing PMF signals",
            "继续这个话题，把第 2 部分做实",
            "## Handoff prompt template",
            "Current topic artifacts",
            "topic_refinement_state update",
        ],
        "examples and handoff",
    )


def test_external_pattern_review_required_terms() -> None:
    assert_contains_all(
        read(REVIEW_PATH),
        [
            "sources_reviewed",
            "extracted_patterns",
            "what_to_adopt",
            "what_not_to_adopt",
            "implications_for_hermes_research_decision",
            "open_questions",
            "skill authoring best practices",
            "iterative refinement",
            "feedback loop",
            "reflective memory",
            "evaluation / tests",
        ],
        "external pattern review",
    )


def test_patterns_have_required_fields() -> None:
    text = read(REVIEW_PATH)
    required = [
        "pattern_name:",
        "source_family:",
        "mature_practice:",
        "why_it_matters:",
        "how_to_adapt_to_research_decision:",
        "risks_if_overapplied:",
    ]
    for field in required:
        assert text.count(field) >= 5, f"missing repeated pattern field: {field}"


def test_no_travel_specific_route_or_place_hard_coding() -> None:
    combined = read(SKILL_PATH) + "\n" + read(REVIEW_PATH)
    forbidden = [
        "day-by-day itinerary",
        "JR Pass",
        "Kansai",
        "Tokyo",
        "Kyoto",
        "airport transfer",
        "hotel recommendation",
        "restaurant recommendation",
    ]
    for phrase in forbidden:
        assert phrase not in combined, f"Travel-specific hard-code leaked: {phrase}"


def test_no_full_rerun_default_instruction() -> None:
    text = normalized(read(SKILL_PATH))
    forbidden = [
        "default to full rerun",
        "full rerun by default",
        "full rerun as the default repair",
    ]
    for phrase in forbidden:
        assert phrase not in text
    assert "Do not treat full rerun as default" in text


def test_caveats_and_thin_evidence_are_preserved() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "Preserve artifacts and caveats",
            "Preserve caveats and do not upgrade thin evidence",
            "Deleting caveats to sound more certain",
            "Upgrading thin evidence into strong evidence",
        ],
        "caveat preservation",
    )


def test_dirty_worktree_and_branch_head_stops() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "dirty worktree",
            "branch-head mismatch",
            "wrong branch",
            "staged files",
        ],
        "dirty and branch-head stops",
    )


def test_runtime_integration_not_claimed_complete() -> None:
    text = read(SKILL_PATH)
    forbidden = [
        "runtime integration completed",
        "runtime integration is complete",
        "integrated into runtime",
        "wired into the main pipeline",
    ]
    for phrase in forbidden:
        assert phrase not in text
    assert "does not integrate with runtime" in text


def run_all() -> None:
    test_skill_file_exists()
    test_external_pattern_review_exists()
    test_skill_frontmatter_exists_and_contains_name_description()
    test_core_sections_exist()
    test_topic_refinement_state_exists()
    test_failure_taxonomy_exists()
    test_failure_to_next_action_mapping_exists()
    test_refinement_modes_exist()
    test_workflow_output_stop_and_antipattern_sections_exist()
    test_examples_and_handoff_template_exist()
    test_external_pattern_review_required_terms()
    test_patterns_have_required_fields()
    test_no_travel_specific_route_or_place_hard_coding()
    test_no_full_rerun_default_instruction()
    test_caveats_and_thin_evidence_are_preserved()
    test_dirty_worktree_and_branch_head_stops()
    test_runtime_integration_not_claimed_complete()


if __name__ == "__main__":
    run_all()
    print("PASS research decision topic refinement loop skill")
