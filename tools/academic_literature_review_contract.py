"""Deterministic validator for academic literature review output packages."""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_OUTPUT_FILES: tuple[str, ...] = (
    "literature_review.md",
    "claim_citation_table.md",
    "evidence_matrix.csv",
    "paper_index.md",
    "method_taxonomy.md",
    "debate_map.md",
    "gap_and_future_work.md",
    "provenance.json",
    "quality_gate_report.md",
)

RECOMMENDED_OUTPUT_FILES: tuple[str, ...] = ("bibliography.bib",)

EVIDENCE_TIERS: tuple[str, ...] = (
    "full_text_verified",
    "full_text_partial",
    "abstract_only",
    "metadata_only",
    "search_snippet_only",
    "secondary_summary",
)

STRONG_CLAIM_ALLOWED_TIERS: frozenset[str] = frozenset({"full_text_verified"})
NON_SUBSTANTIVE_TIERS: frozenset[str] = frozenset({"metadata_only", "search_snippet_only"})

PASS_ACADEMIC_LIT_REVIEW_PACKAGE = "PASS_ACADEMIC_LIT_REVIEW_PACKAGE"
FAIL_MISSING_REQUIRED_OUTPUTS = "FAIL_MISSING_REQUIRED_OUTPUTS"
FAIL_RUBRIC_SCORE_MISSING = "FAIL_RUBRIC_SCORE_MISSING"
FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD = "FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD"
FAIL_PATCHWORK_REVIEW = "FAIL_PATCHWORK_REVIEW"
FAIL_CLAIM_TRACEABILITY_MISSING = "FAIL_CLAIM_TRACEABILITY_MISSING"
FAIL_EVIDENCE_TIER_VIOLATION = "FAIL_EVIDENCE_TIER_VIOLATION"
FAIL_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS = "FAIL_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS"
FAIL_NO_FULL_TEXT_FOR_STRONG_CLAIMS = "FAIL_NO_FULL_TEXT_FOR_STRONG_CLAIMS"

FAILURE_PRIORITY: tuple[str, ...] = (
    FAIL_MISSING_REQUIRED_OUTPUTS,
    FAIL_RUBRIC_SCORE_MISSING,
    FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD,
    FAIL_PATCHWORK_REVIEW,
    FAIL_CLAIM_TRACEABILITY_MISSING,
    FAIL_EVIDENCE_TIER_VIOLATION,
    FAIL_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS,
    FAIL_NO_FULL_TEXT_FOR_STRONG_CLAIMS,
)

CLAIM_TRACEABILITY_FIELDS: tuple[str, ...] = (
    "claim",
    "citation_key",
    "paper_id",
    "source_anchor",
    "evidence_tier",
    "claim_strength",
)

EMPTY_ANCHOR_VALUES: frozenset[str] = frozenset({"", "-", "n/a", "na", "missing", "none", '""', "''"})

FIELD_LEVEL_REVIEW_TYPES: frozenset[str] = frozenset(
    {"field_level", "field-level", "state_of_the_field_review", "state-of-the-field-review"}
)


@dataclass
class ReviewPackageValidationResult:
    status: str
    passed: bool
    failure_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    rubric_score: int | None = None
    patchwork_risk: str = "unknown"
    claim_traceability_errors: list[str] = field(default_factory=list)
    evidence_tier_errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_review_package(package_dir: str | Path) -> ReviewPackageValidationResult:
    package_path = Path(package_dir)
    failure_codes: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    claim_traceability_errors: list[str] = []
    evidence_tier_errors: list[str] = []

    missing_files = [filename for filename in REQUIRED_OUTPUT_FILES if not (package_path / filename).is_file()]
    if missing_files:
        _add_failure(failure_codes, FAIL_MISSING_REQUIRED_OUTPUTS)

    quality_report = _read_text(package_path / "quality_gate_report.md")
    literature_review = _read_text(package_path / "literature_review.md")
    claim_table = _read_text(package_path / "claim_citation_table.md")
    evidence_matrix = _read_text(package_path / "evidence_matrix.csv")
    provenance_text = _read_text(package_path / "provenance.json")
    provenance = _read_json(package_path / "provenance.json", warnings)

    rubric_score = _parse_rubric_score(quality_report)
    if rubric_score is None:
        _add_failure(failure_codes, FAIL_RUBRIC_SCORE_MISSING)
    elif rubric_score < 80:
        _add_failure(failure_codes, FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD)

    patchwork_risk = _detect_patchwork_risk(quality_report, literature_review)
    if patchwork_risk == "high":
        _add_failure(failure_codes, FAIL_PATCHWORK_REVIEW)

    claim_rows, claim_errors = _parse_claim_table(claim_table)
    claim_traceability_errors.extend(claim_errors)
    if claim_errors:
        _add_failure(failure_codes, FAIL_CLAIM_TRACEABILITY_MISSING)

    matrix_rows = _parse_evidence_matrix(evidence_matrix, warnings)
    evidence_tier_errors.extend(_evidence_tier_errors(claim_rows, source="claim_citation_table.md"))
    evidence_tier_errors.extend(_evidence_tier_errors(matrix_rows, source="evidence_matrix.csv"))
    if evidence_tier_errors:
        _add_failure(failure_codes, FAIL_EVIDENCE_TIER_VIOLATION)

    combined_text = "\n".join([quality_report, literature_review, provenance_text])
    review_type = _extract_string_value("review_type", quality_report, provenance)
    corpus_size = _extract_int_value("corpus_size", quality_report, provenance)
    full_text_verified_count = _extract_int_value("full_text_verified_count", quality_report, provenance)

    if _is_small_field_level_overclaim(review_type, corpus_size, combined_text):
        _add_failure(failure_codes, FAIL_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS)

    if full_text_verified_count == 0 and _has_strong_consensus_claim(combined_text):
        _add_failure(failure_codes, FAIL_NO_FULL_TEXT_FOR_STRONG_CLAIMS)

    if "bibliography.bib" not in missing_files and not (package_path / "bibliography.bib").is_file():
        warnings.append("bibliography.bib_not_present")

    status = _status_from_failures(failure_codes)
    return ReviewPackageValidationResult(
        status=status,
        passed=not failure_codes,
        failure_codes=failure_codes,
        warnings=warnings,
        missing_files=missing_files,
        rubric_score=rubric_score,
        patchwork_risk=patchwork_risk,
        claim_traceability_errors=claim_traceability_errors,
        evidence_tier_errors=evidence_tier_errors,
        notes=notes,
    )


def _add_failure(failure_codes: list[str], code: str) -> None:
    if code not in failure_codes:
        failure_codes.append(code)


def _status_from_failures(failure_codes: list[str]) -> str:
    for code in FAILURE_PRIORITY:
        if code in failure_codes:
            return code
    return PASS_ACADEMIC_LIT_REVIEW_PACKAGE


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path, warnings: list[str]) -> dict[str, Any]:
    text = _read_text(path)
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        warnings.append("provenance_json_invalid")
        return {}
    return value if isinstance(value, dict) else {}


def _parse_rubric_score(text: str) -> int | None:
    patterns = (
        r"(?im)^\s*rubric_score\s*[:=]\s*(\d{1,3})(?:\s*/\s*100)?\b",
        r"(?im)^\s*academic_quality_score\s*[:=]\s*(\d{1,3})(?:\s*/\s*100)?\b",
        r"(?im)^\s*academic\s+quality\s+score\s*[:=]\s*(\d{1,3})(?:\s*/\s*100)?\b",
        r"(?im)^\s*score\s*[:=]\s*(\d{1,3})\s*/\s*100\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            score = int(match.group(1))
            if 0 <= score <= 100:
                return score
    return None


def _detect_patchwork_risk(quality_report: str, literature_review: str) -> str:
    combined = f"{quality_report}\n{literature_review}".lower()
    if "fail_patchwork_review" in combined:
        return "high"
    if re.search(r"patchwork[_\s-]*risk\s*[:=]\s*high\b", combined):
        return "high"
    for marker in (
        "citation dumping",
        "paper-by-paper summary",
        "annotated bibliography only",
    ):
        if marker in combined:
            return "high"
    if re.search(r"patchwork[_\s-]*risk\s*[:=]\s*low\b", combined):
        return "low"
    return "unknown"


def _parse_claim_table(text: str) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    rows = _parse_markdown_table(text)
    if not rows:
        return [], ["claim_citation_table_missing_markdown_table"]

    fields = set(rows[0].keys()) if rows else set()
    missing = [field for field in CLAIM_TRACEABILITY_FIELDS if field not in fields]
    if missing:
        errors.append("claim_citation_table_missing_fields:" + ",".join(missing))
        return rows, errors

    for index, row in enumerate(rows, start=1):
        anchor = _clean_cell(row.get("source_anchor", ""))
        if anchor.lower() in EMPTY_ANCHOR_VALUES:
            errors.append(f"claim_citation_table_empty_source_anchor:row_{index}")
    return rows, errors


def _parse_markdown_table(text: str) -> list[dict[str, str]]:
    table_lines = [line.strip() for line in (text or "").splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return []
    header = [_normalize_field(cell) for cell in _split_markdown_row(table_lines[0])]
    if not header:
        return []

    rows: list[dict[str, str]] = []
    for raw_line in table_lines[1:]:
        cells = _split_markdown_row(raw_line)
        if _is_markdown_separator_row(cells):
            continue
        values = [_clean_cell(cell) for cell in cells]
        if len(values) < len(header):
            values.extend([""] * (len(header) - len(values)))
        rows.append(dict(zip(header, values)))
    return rows


def _split_markdown_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")]


def _is_markdown_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _normalize_field(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower().strip("`")).strip("_")


def _clean_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def _parse_evidence_matrix(text: str, warnings: list[str]) -> list[dict[str, str]]:
    if not (text or "").strip():
        return []
    try:
        reader = csv.DictReader(text.splitlines())
        return [
            {_normalize_field(key or ""): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    except csv.Error:
        warnings.append("evidence_matrix_csv_invalid")
        return []


def _evidence_tier_errors(rows: list[dict[str, str]], *, source: str) -> list[str]:
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        tier = _clean_cell(row.get("evidence_tier", "")).lower()
        strength = _clean_cell(row.get("claim_strength", "")).lower()
        if not tier or not strength:
            continue
        if tier not in EVIDENCE_TIERS:
            continue
        strong = "strong" in strength
        substantive = "substantive" in strength
        if strong and tier not in STRONG_CLAIM_ALLOWED_TIERS:
            errors.append(f"{source}:row_{index}:strong_claim_uses_{tier}")
            continue
        if tier in NON_SUBSTANTIVE_TIERS and (strong or substantive):
            errors.append(f"{source}:row_{index}:substantive_claim_uses_{tier}")
    return errors


def _extract_string_value(key: str, text: str, provenance: dict[str, Any]) -> str:
    value = provenance.get(key)
    if value is not None:
        return str(value).strip()
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*[:=]\s*([A-Za-z0-9_-]+)\b", text or "")
    return match.group(1).strip() if match else ""


def _extract_int_value(key: str, text: str, provenance: dict[str, Any]) -> int | None:
    value = provenance.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*[:=]\s*(\d+)\b", text or "")
    return int(match.group(1)) if match else None


def _is_small_field_level_overclaim(review_type: str, corpus_size: int | None, combined_text: str) -> bool:
    if corpus_size is None or corpus_size > 5:
        return False
    normalized_review_type = review_type.strip().lower().replace("_", "-")
    if normalized_review_type not in FIELD_LEVEL_REVIEW_TYPES:
        return False
    lowered = (combined_text or "").lower()
    has_downgrade = any(
        marker in lowered
        for marker in (
            "mini_review",
            "mini-review",
            "coverage limitation",
            "coverage_limitation",
            "corpus-size limitation",
            "corpus size limitation",
        )
    )
    return not has_downgrade


def _has_strong_consensus_claim(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "strong consensus",
            "definitive consensus",
            "settled consensus",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an academic literature review output package.")
    parser.add_argument("package_dir", help="Directory containing the review output package.")
    args = parser.parse_args(argv)

    result = validate_review_package(args.package_dir)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
