from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.academic_literature_review_contract import (
    FAIL_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS,
    FAIL_EVIDENCE_TIER_VIOLATION,
    FAIL_NO_FULL_TEXT_FOR_STRONG_CLAIMS,
    FAIL_PATCHWORK_REVIEW,
    PASS_ACADEMIC_LIT_REVIEW_PACKAGE,
    REQUIRED_OUTPUT_FILES,
    validate_review_package,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def write_required_files(
    package_dir: Path,
    *,
    quality_gate_report: str,
    literature_review: str,
    claim_table: str,
    evidence_matrix: str,
    provenance: dict,
) -> Path:
    package_dir.mkdir(parents=True, exist_ok=True)
    contents = {
        "literature_review.md": literature_review,
        "claim_citation_table.md": claim_table,
        "evidence_matrix.csv": evidence_matrix,
        "paper_index.md": "# Paper Index\n\nAll included sources are indexed with evidence tiers.\n",
        "method_taxonomy.md": "# Method Taxonomy\n\nMethods are compared across the included corpus.\n",
        "debate_map.md": "# Debate Map\n\nContradictions and boundary conditions are mapped.\n",
        "gap_and_future_work.md": "# Gaps And Future Work\n\nGaps are translated into future research directions.\n",
        "provenance.json": json.dumps(provenance, indent=2),
        "quality_gate_report.md": quality_gate_report,
    }
    for filename in REQUIRED_OUTPUT_FILES:
        (package_dir / filename).write_text(contents[filename], encoding="utf-8")
    return package_dir


def write_valid_base_package(
    tmp_path: Path,
    *,
    quality_gate_report: str | None = None,
    literature_review: str | None = None,
    claim_table: str | None = None,
    evidence_matrix: str | None = None,
    provenance: dict | None = None,
) -> Path:
    base_quality_gate_report = "\n".join(
        [
            "rubric_score: 86/100",
            "patchwork_risk: low",
            "review_type: mini_review",
            "corpus_size: 5",
            "full_text_verified_count: 5",
            "coverage_limitation: focused mini-review corpus; no field-level coverage claimed",
        ]
    )
    base_literature_review = "\n".join(
        [
            "# Academic Literature Review",
            "",
            "This mini_review synthesizes a focused five-paper full-text corpus.",
            "The review compares theory, method, evidence strength, debate, and gaps without claiming field consensus.",
        ]
    )
    base_claim_table = "\n".join(
        [
            "| claim | citation_key | paper_id | source_anchor | evidence_tier | claim_strength |",
            "| --- | --- | --- | --- | --- | --- |",
            "| Full-text studies support the first focused synthesis claim. | Smith2024 | P1 | p. 4 | full_text_verified | strong |",
            "| Method differences explain a bounded divergence in findings. | Jones2025 | P2 | sec. 3.2 | full_text_verified | supported |",
        ]
    )
    base_evidence_matrix = "\n".join(
        [
            "paper_id,citation_key,theme,method,sample,finding,limitation,evidence_tier,source_anchor,claim_strength",
            "P1,Smith2024,theory,qualitative,n=28,bounded finding,small sample,full_text_verified,p. 4,strong",
            "P2,Jones2025,methods,mixed,n=64,method contrast,limited setting,full_text_verified,sec. 3.2,supported",
        ]
    )
    base_provenance = {
        "review_type": "mini_review",
        "corpus_size": 5,
        "full_text_verified_count": 5,
        "coverage_limitation": "focused mini-review corpus",
    }
    return write_required_files(
        tmp_path / "golden_package",
        quality_gate_report=quality_gate_report or base_quality_gate_report,
        literature_review=literature_review or base_literature_review,
        claim_table=claim_table or base_claim_table,
        evidence_matrix=evidence_matrix or base_evidence_matrix,
        provenance=provenance or base_provenance,
    )


def test_golden_strong_mini_review_package_passes(tmp_path: Path):
    package_dir = write_valid_base_package(tmp_path)

    result = validate_review_package(package_dir)

    assert result.passed is True
    assert result.status == PASS_ACADEMIC_LIT_REVIEW_PACKAGE
    assert result.failure_codes == []


def test_golden_patchwork_package_fails(tmp_path: Path):
    package_dir = write_valid_base_package(
        tmp_path,
        quality_gate_report="\n".join(
            [
                "rubric_score: 82",
                "patchwork_risk: high",
                "review_type: mini_review",
                "corpus_size: 5",
                "full_text_verified_count: 5",
            ]
        ),
        literature_review="\n".join(
            [
                "# Literature Review",
                "",
                "This paper-by-paper summary creates citation dumping rather than synthesis.",
            ]
        ),
    )

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert FAIL_PATCHWORK_REVIEW in result.failure_codes


def test_golden_abstract_only_strong_claim_fails(tmp_path: Path):
    package_dir = write_valid_base_package(
        tmp_path,
        quality_gate_report="\n".join(
            [
                "rubric_score: 85",
                "patchwork_risk: low",
                "review_type: preliminary_review",
                "corpus_size: 5",
                "full_text_verified_count: 3",
                "coverage_limitation: one abstract-only source remains preliminary",
            ]
        ),
        claim_table="\n".join(
            [
                "| claim | citation_key | paper_id | source_anchor | evidence_tier | claim_strength |",
                "| --- | --- | --- | --- | --- | --- |",
                "| Abstract-only evidence is incorrectly used for a strong claim. | Lee2025 | P3 | abstract | abstract_only | strong |",
            ]
        ),
    )

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert FAIL_EVIDENCE_TIER_VIOLATION in result.failure_codes


def test_golden_state_of_field_small_corpus_fails(tmp_path: Path):
    package_dir = write_valid_base_package(
        tmp_path,
        quality_gate_report="\n".join(
            [
                "rubric_score: 88",
                "patchwork_risk: low",
                "review_type: state_of_the_field_review",
                "corpus_size: 5",
                "full_text_verified_count: 5",
            ]
        ),
        literature_review="\n".join(
            [
                "# State Of The Field Review",
                "",
                "The field has established a field consensus from this five-paper corpus.",
            ]
        ),
        provenance={
            "review_type": "state_of_the_field_review",
            "corpus_size": 5,
            "full_text_verified_count": 5,
        },
    )

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert FAIL_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS in result.failure_codes


def test_golden_no_full_text_strong_consensus_fails(tmp_path: Path):
    package_dir = write_valid_base_package(
        tmp_path,
        quality_gate_report="\n".join(
            [
                "rubric_score: 84",
                "patchwork_risk: low",
                "review_type: preliminary_review",
                "corpus_size: 8",
                "full_text_verified_count: 0",
                "coverage_limitation: abstract-only corpus",
            ]
        ),
        literature_review="\n".join(
            [
                "# Preliminary Review",
                "",
                "Despite no full text, the review wrongly claims definitive consensus.",
            ]
        ),
        provenance={
            "review_type": "preliminary_review",
            "corpus_size": 8,
            "full_text_verified_count": 0,
            "coverage_limitation": "abstract-only corpus",
        },
    )

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert FAIL_NO_FULL_TEXT_FOR_STRONG_CLAIMS in result.failure_codes


def test_golden_cli_matches_python_api(tmp_path: Path):
    package_dir = write_valid_base_package(tmp_path)

    api_result = validate_review_package(package_dir)
    completed = subprocess.run(
        [sys.executable, "-m", "tools.academic_literature_review_contract", str(package_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    cli_result = json.loads(completed.stdout)

    assert cli_result["status"] == api_result.status
    assert cli_result["passed"] == api_result.passed
    assert cli_result["failure_codes"] == api_result.failure_codes
