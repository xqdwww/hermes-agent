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


def test_selection_tie_breaker_exists() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "## Selection tie-breaker",
            "Use this order when failures overlap",
            "Environment, dependency, branch/head",
            "Evidence gap or full-text verification gap",
            "Calibration/convergence is present but not absorbed",
            "Only one section is weak or missing",
            "choose `section_rewrite` for local defects",
            "choose `final_absorption_pass` for whole-final failures",
        ],
        "selection tie-breaker",
    )


def test_confidence_cannot_increase_without_evidence() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "## Confidence and evidence rules",
            "Confidence cannot increase without new evidence or stronger artifact support",
            "Thin evidence must remain conditional",
            "Calibration can decrease or qualify confidence without new evidence",
            "Full-text verification is required before upgrading snippet-only support",
        ],
        "confidence and evidence rules",
    )


def test_previous_final_must_not_be_overwritten_and_versioning_exists() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "final_versions",
            "final_v1",
            "refinement_v1",
            "revised_final_v2",
            "Never overwrite a previous final",
            "Append each refinement as a new version",
            "previous_final_version",
            "new_final_version",
            "do not overwrite previous final text",
        ],
        "topic versioning",
    )


def test_max_iteration_and_repeated_failure_stop_condition_exists() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "iteration_count",
            "the same failure repeats after two refinement attempts",
            "quality review shows no material improvement after two attempts",
            "the same failure did not repeat without improvement",
        ],
        "max iteration stop",
    )


def test_user_feedback_cannot_override_evidence_boundary() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "User preference can change emphasis, ordering, and specificity",
            "cannot override evidence boundaries",
            "User feedback cannot remove caveats",
            "user feedback conflicts with evidence boundaries",
            "Letting user feedback override evidence boundaries",
        ],
        "user feedback evidence boundary",
    )


def test_environment_blocker_maps_to_triage_not_answer_rewrite() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "`executor_or_environment_blocker` | Run environment triage",
            "do not repair prompts or rewrite answers",
            "Do not rewrite the answer while the environment blocker is unresolved",
            "Do not treat environment blockers as prompt repair",
            "Treating environment failure as prompt repair",
        ],
        "environment blocker routing",
    )


def test_output_quality_gate_exists() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "## Output quality gate",
            "changed sections are traceable to the selected failure type",
            "unchanged sections are named and intentionally preserved",
            "`new_or_reused_evidence` states whether evidence was reused",
            "`confidence_changes` states no increase unless new evidence or stronger artifact support exists",
            "caveats and thin-evidence boundaries are preserved",
            "output_quality_gate",
        ],
        "output quality gate",
    )


def test_external_patterns_are_operationalized_in_skill() -> None:
    text = read(SKILL_PATH)

    assert_contains_all(
        text,
        [
            "first_pass_final -> feedback -> refinement -> quality review -> revised_final",
            "refinement_history",
            "Read `refinement_history` and prior failure types",
            "Run the output quality gate",
            "Failure-to-next-action mapping",
            "Selection tie-breaker",
            "Stop conditions",
            "environment_triage",
        ],
        "external pattern operationalization",
    )


def test_skill_does_not_dump_long_external_reference_prose() -> None:
    text = read(SKILL_PATH)
    lines = text.splitlines()
    forbidden = [
        "https://",
        "Anthropic / Claude Skills authoring best practices",
        "OpenAI evaluation best practices",
        "Self-Refine:",
        "Reflexion:",
        "LangGraph workflow guidance",
    ]
    assert len(lines) < 340
    for phrase in forbidden:
        assert phrase not in text


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
    test_selection_tie_breaker_exists()
    test_confidence_cannot_increase_without_evidence()
    test_previous_final_must_not_be_overwritten_and_versioning_exists()
    test_max_iteration_and_repeated_failure_stop_condition_exists()
    test_user_feedback_cannot_override_evidence_boundary()
    test_environment_blocker_maps_to_triage_not_answer_rewrite()
    test_output_quality_gate_exists()
    test_external_patterns_are_operationalized_in_skill()
    test_skill_does_not_dump_long_external_reference_prose()


if __name__ == "__main__":
    run_all()
    print("PASS research decision topic refinement loop skill")
