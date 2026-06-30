from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = (
    ROOT / "optional-skills/engineering/new-skill-external-pattern-review/SKILL.md"
)
TEMPLATE_PATH = (
    ROOT
    / "optional-skills/engineering/new-skill-external-pattern-review/"
    "references/pattern_review_template.md"
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


def test_reference_template_exists() -> None:
    assert TEMPLATE_PATH.exists()


def test_requires_external_pattern_review_before_implementation() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "This skill is mandatory before creating a new substantial skill or major domain skill.",
            "Before implementation, review external patterns read-only.",
            "No pattern review means no implementation.",
            "IMPLEMENTATION_BLOCKED_PATTERN_REVIEW_MISSING",
        ],
        "external pattern review gate",
    )


def test_requires_mature_sources_official_docs_repos_and_papers() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "mature skills or public skill repositories",
            "official docs or specifications",
            "high-quality repos, examples, templates, or reference implementations",
            "papers, standards, or best-practice guides when relevant",
            "Search at least three source classes",
        ],
        "source class requirements",
    )


def test_forbids_clone_install_run_unknown_external_repo_by_default() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "External repositories are read-only by default.",
            "Do not clone, install, or run unknown external code unless separately authorized and sandboxed.",
            "Not allowed by default",
            "`git clone` of an unfamiliar repo",
            "install commands from an unfamiliar repo",
            "running setup scripts, examples, notebooks, CLIs, or package code from an unfamiliar repo",
        ],
        "external code execution boundary",
    )


def test_requires_anti_pattern_review() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "### Phase 2: Anti-Pattern Review",
            "Do not blindly copy external skill text",
            "Do not treat GitHub stars, download counts, or popularity as quality proof.",
            "Do not apply an external pattern unchanged to local Hermes workflows.",
            "Do not implement before tests, contract, artifacts, and validation plan exist.",
        ],
        "anti-pattern review",
    )


def test_requires_local_contract_before_implementation() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "### Phase 3: Local Contract Design",
            "Design the local contract before writing implementation",
            "skill purpose",
            "trigger conditions",
            "input contract",
            "output contract",
            "failure modes",
            "stop rules",
            "user confirmation boundaries",
            "security constraints",
        ],
        "local contract",
    )


def test_requires_output_artifacts() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "## Output Artifacts",
            "external_pattern_review.md",
            "external_pattern_review.json",
            "local_contract.md",
            "implementation_gate.md",
            "test_plan.md",
            "dry_run_review.md",
            "precommit_audit.md",
        ],
        "output artifacts",
    )


def test_requires_implementation_gate() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "### Phase 4: Implementation Gate",
            "Implementation is blocked unless all gate checks pass",
            "IMPLEMENTATION_ALLOWED",
            "IMPLEMENTATION_BLOCKED_LOCAL_CONTRACT_MISSING",
            "IMPLEMENTATION_BLOCKED_TEST_PLAN_MISSING",
            "IMPLEMENTATION_BLOCKED_SECURITY_REVIEW_MISSING",
        ],
        "implementation gate",
    )


def test_includes_blocked_status_when_network_required_but_unavailable() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "If web/network is unavailable and external review is required",
            "BLOCKED_EXTERNAL_PATTERN_REVIEW_REQUIRES_NETWORK",
            "unless the user explicitly chooses local-only design",
        ],
        "network blocked status",
    )


def test_includes_cross_domain_applicability_examples() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "Travel evidence dossier skill",
            "Academic Literature Review skill enhancement",
            "Research-Decision operator skill",
            "Finance Assistant skill",
            "Small typo fix in an existing skill",
        ],
        "cross-domain examples",
    )


def test_does_not_instruct_default_external_repo_execution() -> None:
    text = normalized(read(SKILL_PATH))
    forbidden_positive_instructions = [
        "run external repository code by default",
        "clone unknown external code by default",
        "install unknown external code by default",
        "execute unfamiliar repo setup",
    ]
    for phrase in forbidden_positive_instructions:
        assert phrase not in text

    assert "Allowed by default" in read(SKILL_PATH)
    assert "read official documentation" in read(SKILL_PATH)
    assert "Not allowed by default" in read(SKILL_PATH)


def test_does_not_allow_implementation_without_tests_or_validation_plan() -> None:
    assert_contains_all(
        read(SKILL_PATH),
        [
            "tests/validation plan exists",
            "Do not implement before tests, contract, artifacts, and validation plan exist.",
            "IMPLEMENTATION_BLOCKED_TEST_PLAN_MISSING",
            "Run a dry run against realistic target scenarios.",
            "Include adversarial or negative tests.",
        ],
        "tests and validation gate",
    )


def test_template_has_required_sections() -> None:
    assert_contains_all(
        read(TEMPLATE_PATH),
        [
            "## Scope",
            "## Target Skill",
            "## Trigger Reason",
            "## Sources Reviewed",
            "## Pattern Extraction",
            "## Anti-Pattern Review",
            "## Security Review",
            "## Local Adaptation Plan",
            "## Implementation Gate Decision",
            "## Tests Plan",
            "## Final Recommendation",
        ],
        "template sections",
    )


def test_template_captures_source_pattern_antipattern_security_and_gate() -> None:
    assert_contains_all(
        read(TEMPLATE_PATH),
        [
            "why relevant",
            "pattern extracted",
            "local adaptation",
            "clone/install/run unknown code",
            "external repositories read-only",
            "implementation_gate_status",
            "implementation_allowed",
        ],
        "template review fields",
    )
