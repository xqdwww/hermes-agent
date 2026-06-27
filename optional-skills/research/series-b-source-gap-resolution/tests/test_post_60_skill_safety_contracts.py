#!/usr/bin/env python3
"""Post-60 safety contract checks for Series B skill documentation."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SOURCE_GAP = REPO_ROOT / "optional-skills/research/source-gap-acquisition/SKILL.md"
PIPELINE = REPO_ROOT / "optional-skills/research/series-b-score-improvement-pipeline/SKILL.md"
RESOLUTION = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/SKILL.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def _assert_terms(path: Path, terms: list[str]) -> None:
    text = _text(path)
    missing = [term for term in terms if term.lower() not in text]
    assert not missing, f"{path} missing terms: {missing}"


def test_source_gap_alias_and_policy_caveat_contracts() -> None:
    _assert_terms(
        SOURCE_GAP,
        [
            "alias_confirmed_with_caveat",
            "do not convert a caveated alias into unconstrained certainty",
            "malformed/trap tokens must not be promoted into fake entities",
            "locator-only evidence must not become conceptual evidence",
        ],
    )


def test_pipeline_post_60_and_review_scope_contracts() -> None:
    _assert_terms(
        PIPELINE,
        [
            "post-60 closure rule",
            "stop case chasing by default",
            "human-reviewed with caveats",
            "do not promote candidate-only deltas that were outside the review scope",
            "release planning is not release execution",
        ],
    )


def test_source_gap_resolution_post_60_boundary_contracts() -> None:
    _assert_terms(
        RESOLUTION,
        [
            "historical score as current state",
            "post-60 safety boundary",
            "do not chase more cases",
            "candidate-only vs official-baseline separation",
            "official movement requires separate candidate rerun",
        ],
    )


def run_tests() -> None:
    test_source_gap_alias_and_policy_caveat_contracts()
    test_pipeline_post_60_and_review_scope_contracts()
    test_source_gap_resolution_post_60_boundary_contracts()


if __name__ == "__main__":
    run_tests()
    print("post-60 skill safety contract tests PASS")
