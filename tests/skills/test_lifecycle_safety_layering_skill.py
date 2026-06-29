from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains_all(text: str, needles: list[str], label: str) -> None:
    normalized = " ".join(text.split())
    missing = [needle for needle in needles if needle not in normalized]
    assert not missing, f"{label} missing required wording: {missing}"


def test_codex_lifecycle_execution_safety_contract() -> None:
    text = read_text("skills/autonomous-ai-agents/codex/SKILL.md")

    assert_contains_all(
        text,
        [
            "Lifecycle Execution Safety",
            "branch, HEAD, tracked",
            "outputs/**",
            "Candidate-only, dry-run, smoke, controlled, guarded, and provisional outputs",
            "must not write a final result",
            "Baseline or final result writes must be their own reviewed phase",
            "Runtime metadata updates follow accepted state",
            "Rejected, deferred, weak, or wrong-context evidence must not be promoted",
            "approval is blocked",
            "exact authorization for the remote, branch or tag refs",
        ],
        "codex lifecycle safety",
    )


def test_github_exact_ref_release_safety_contract() -> None:
    text = read_text("skills/github/github-repo-management/SKILL.md")

    assert_contains_all(
        text,
        [
            "Exact-Ref Push and Release Safety",
            "explicit user authorization naming the remote",
            "branch refspec",
            "tag refspec",
            "remote visibility",
            "public",
            "WRITE",
            "MAINTAIN",
            "ADMIN",
            "dry-run",
            "fast-forward",
            "Never use `--force`",
            "`--tags`",
            "`--all`",
            "`--mirror`",
            "Push only the enumerated `src:dst` refs",
            "Do not upload bundle assets",
        ],
        "github exact-ref release safety",
    )


def test_rd_guarded_validation_layering_contract() -> None:
    text = read_text(
        "optional-skills/research-decision/guarded-validation-operator/SKILL.md"
    )

    assert_contains_all(
        text,
        [
            "Lifecycle Safety Layering",
            "Guarded validation is not a shortcut to accepted state",
            "observed branch",
            "accepted scope",
            "`RESEARCH`, `DECISION`, and `RESEARCH_DECISION` artifacts isolated",
            "StageRecord, ledger, validation JSON, closeout report, and final answer",
            "Runtime metadata, public release notes, and final status summaries may follow accepted state",
            "Rejected or weak evidence cannot be promoted",
            "`passive_guard_mode` remains default off",
            "Debug, warn, and",
            "block-destructive passive-guard modes are opt-in",
        ],
        "R/D guarded validation lifecycle layering",
    )


def test_final_controller_layered_evidence_boundaries_contract() -> None:
    text = read_text(
        "optional-skills/research-decision/"
        "final-controller-quality-adversarial-audit-operator/SKILL.md"
    )

    assert_contains_all(
        text,
        [
            "Layered Evidence Boundaries",
            "Evidence packets, convergence reports, external calibration, and final",
            "not themselves final accepted",
            "Candidate, provisional, smoke, dry-run, and guarded-validation outputs",
            "accepted-scope review",
            "must not promote unaccepted material",
            "Caveats, uncertainty, disagreement, weak evidence, and rejected-evidence",
            "must not strengthen",
            "current-run provenance",
            "other repositories or product lines",
            "must not change the normal",
        ],
        "final-controller layered evidence boundaries",
    )


def test_travel_case_specific_rules_are_not_globalized() -> None:
    combined = "\n".join(
        read_text(path)
        for path in [
            "skills/autonomous-ai-agents/codex/SKILL.md",
            "skills/github/github-repo-management/SKILL.md",
            "optional-skills/research-decision/guarded-validation-operator/SKILL.md",
            (
                "optional-skills/research-decision/"
                "final-controller-quality-adversarial-audit-operator/SKILL.md"
            ),
        ]
    )
    forbidden = [
        "obj_art_008",
        "adv_trap_059",
        "Travel 60/60 caveat registry",
        "travel locator/listicle",
    ]

    for phrase in forbidden:
        assert phrase not in combined, f"Travel-specific rule leaked: {phrase}"


def run_all() -> None:
    test_codex_lifecycle_execution_safety_contract()
    test_github_exact_ref_release_safety_contract()
    test_rd_guarded_validation_layering_contract()
    test_final_controller_layered_evidence_boundaries_contract()
    test_travel_case_specific_rules_are_not_globalized()


if __name__ == "__main__":
    run_all()
    print("PASS lifecycle safety layering skill contracts")
