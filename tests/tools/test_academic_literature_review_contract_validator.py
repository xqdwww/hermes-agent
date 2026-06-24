from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.academic_literature_review_contract import (
    FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD,
    FAIL_CLAIM_TRACEABILITY_MISSING,
    FAIL_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS,
    FAIL_EVIDENCE_TIER_VIOLATION,
    FAIL_MISSING_REQUIRED_OUTPUTS,
    FAIL_NO_FULL_TEXT_FOR_STRONG_CLAIMS,
    FAIL_PATCHWORK_REVIEW,
    FAIL_RUBRIC_SCORE_MISSING,
    PASS_ACADEMIC_LIT_REVIEW_PACKAGE,
    REQUIRED_OUTPUT_FILES,
    validate_review_package,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_valid_package(package_dir: Path, *, score: str = "rubric_score: 85") -> Path:
    package_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "literature_review.md": "\n".join(
            [
                "# Literature Review",
                "",
                "The focused mini_review synthesizes multiple full text sources without claiming field coverage.",
            ]
        ),
        "claim_citation_table.md": "\n".join(
            [
                "| claim | citation_key | paper_id | source_anchor | evidence_tier | claim_strength |",
                "| --- | --- | --- | --- | --- | --- |",
                "| Full-text studies support the focused theme. | Smith2024 | P1 | p. 4 | full_text_verified | strong |",
            ]
        ),
        "evidence_matrix.csv": "\n".join(
            [
                "paper_id,citation_key,theme,method,sample,finding,limitation,evidence_tier,source_anchor,claim_strength",
                "P1,Smith2024,theme,qualitative,n=20,finding,small sample,full_text_verified,p. 4,strong",
            ]
        ),
        "paper_index.md": "| paper_id | citation_key | evidence_tier |\n| --- | --- | --- |\n| P1 | Smith2024 | full_text_verified |\n",
        "method_taxonomy.md": "# Method Taxonomy\n\nQualitative and quantitative methods are compared.\n",
        "debate_map.md": "# Debate Map\n\nCounter-evidence and disagreement are represented.\n",
        "gap_and_future_work.md": "# Gaps\n\nFuture work is scoped to the corpus limitations.\n",
        "provenance.json": json.dumps(
            {
                "review_type": "mini_review",
                "corpus_size": 6,
                "full_text_verified_count": 2,
                "coverage_limitation": "focused corpus only",
            },
            indent=2,
        ),
        "quality_gate_report.md": "\n".join(
            [
                score,
                "patchwork_risk: low",
                "review_type: mini_review",
                "corpus_size: 6",
                "full_text_verified_count: 2",
                "coverage_limitation: focused corpus only",
            ]
        ),
    }
    for filename in REQUIRED_OUTPUT_FILES:
        (package_dir / filename).write_text(files[filename], encoding="utf-8")
    return package_dir


def test_valid_package_passes(tmp_path: Path):
    package_dir = _write_valid_package(tmp_path / "review_package")

    result = validate_review_package(package_dir)

    assert result.passed is True
    assert result.status == PASS_ACADEMIC_LIT_REVIEW_PACKAGE
    assert result.failure_codes == []
    assert result.rubric_score == 85


def test_missing_required_outputs_fails(tmp_path: Path):
    package_dir = _write_valid_package(tmp_path / "review_package")
    (package_dir / "debate_map.md").unlink()

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert result.status == FAIL_MISSING_REQUIRED_OUTPUTS
    assert FAIL_MISSING_REQUIRED_OUTPUTS in result.failure_codes
    assert result.missing_files == ["debate_map.md"]


def test_rubric_score_below_80_fails(tmp_path: Path):
    package_dir = _write_valid_package(tmp_path / "review_package", score="academic quality score: 79/100")

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert result.status == FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD
    assert FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD in result.failure_codes
    assert result.rubric_score == 79


def test_missing_rubric_score_fails(tmp_path: Path):
    package_dir = _write_valid_package(tmp_path / "review_package", score="rubric details withheld")

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert result.status == FAIL_RUBRIC_SCORE_MISSING
    assert FAIL_RUBRIC_SCORE_MISSING in result.failure_codes


def test_patchwork_risk_high_fails(tmp_path: Path):
    package_dir = _write_valid_package(tmp_path / "review_package")
    (package_dir / "quality_gate_report.md").write_text(
        "rubric_score: 88\npatchwork_risk: high\n",
        encoding="utf-8",
    )

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert result.status == FAIL_PATCHWORK_REVIEW
    assert FAIL_PATCHWORK_REVIEW in result.failure_codes
    assert result.patchwork_risk == "high"


def test_claim_traceability_missing_fails(tmp_path: Path):
    package_dir = _write_valid_package(tmp_path / "review_package")
    (package_dir / "claim_citation_table.md").write_text(
        "\n".join(
            [
                "| claim | citation_key | paper_id | source_anchor | evidence_tier | claim_strength |",
                "| --- | --- | --- | --- | --- | --- |",
                "| Full-text studies support the focused theme. | Smith2024 | P1 | - | full_text_verified | strong |",
            ]
        ),
        encoding="utf-8",
    )

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert result.status == FAIL_CLAIM_TRACEABILITY_MISSING
    assert FAIL_CLAIM_TRACEABILITY_MISSING in result.failure_codes
    assert result.claim_traceability_errors


def test_strong_claim_requires_full_text_verified(tmp_path: Path):
    package_dir = _write_valid_package(tmp_path / "review_package")
    (package_dir / "claim_citation_table.md").write_text(
        "\n".join(
            [
                "| claim | citation_key | paper_id | source_anchor | evidence_tier | claim_strength |",
                "| --- | --- | --- | --- | --- | --- |",
                "| Abstract evidence proves a strong claim. | Smith2024 | P1 | abstract | abstract_only | strong |",
                "| Snippet evidence proves a strong claim. | Jones2025 | P2 | snippet | search_snippet_only | strong |",
            ]
        ),
        encoding="utf-8",
    )

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert result.status == FAIL_EVIDENCE_TIER_VIOLATION
    assert FAIL_EVIDENCE_TIER_VIOLATION in result.failure_codes
    assert any("abstract_only" in error for error in result.evidence_tier_errors)
    assert any("search_snippet_only" in error for error in result.evidence_tier_errors)


def test_small_corpus_cannot_claim_field_level_review(tmp_path: Path):
    package_dir = _write_valid_package(tmp_path / "review_package")
    (package_dir / "provenance.json").write_text(
        json.dumps(
            {
                "review_type": "state_of_the_field_review",
                "corpus_size": 5,
                "full_text_verified_count": 5,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (package_dir / "quality_gate_report.md").write_text(
        "rubric_score: 86\nreview_type: state_of_the_field_review\ncorpus_size: 5\nfull_text_verified_count: 5\n",
        encoding="utf-8",
    )
    (package_dir / "literature_review.md").write_text(
        "# Literature Review\n\nThis state of the field review claims broad field coverage.\n",
        encoding="utf-8",
    )

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert result.status == FAIL_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS
    assert FAIL_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS in result.failure_codes


def test_no_full_text_blocks_strong_consensus(tmp_path: Path):
    package_dir = _write_valid_package(tmp_path / "review_package")
    (package_dir / "provenance.json").write_text(
        json.dumps(
            {
                "review_type": "preliminary_review",
                "corpus_size": 8,
                "full_text_verified_count": 0,
                "coverage_limitation": "abstract-only corpus",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (package_dir / "literature_review.md").write_text(
        "# Literature Review\n\nThe review finds strong consensus across the field.\n",
        encoding="utf-8",
    )

    result = validate_review_package(package_dir)

    assert result.passed is False
    assert result.status == FAIL_NO_FULL_TEXT_FOR_STRONG_CLAIMS
    assert FAIL_NO_FULL_TEXT_FOR_STRONG_CLAIMS in result.failure_codes


def test_cli_outputs_json(tmp_path: Path):
    package_dir = _write_valid_package(tmp_path / "review_package")

    completed = subprocess.run(
        [sys.executable, "-m", "tools.academic_literature_review_contract", str(package_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["passed"] is True
    assert payload["status"] == PASS_ACADEMIC_LIT_REVIEW_PACKAGE
    assert payload["rubric_score"] == 85
