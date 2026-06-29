import copy
import json
import subprocess
import sys
from pathlib import Path

from tools.source_registry_workflow import (
    HOLD_FOR_MORE_SOURCES,
    READY_FOR_EVIDENCE_PACKET_V2,
    READY_WITH_LIMITATIONS,
    load_registry_json,
    normalize_source_registry,
    render_source_registry_review,
    score_source_registry,
    validate_source_registry,
    write_registry_review,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "source_registry_workflow.py"
B01_STAGE1_REGISTRY = (
    REPO_ROOT
    / "outputs"
    / "b01_b06_evidence_backed_pilot_stage1_sources_20260629"
    / "cases"
    / "B01_pricing_packaging"
    / "source_registry.json"
)
B06_STAGE1_REGISTRY = (
    REPO_ROOT
    / "outputs"
    / "b01_b06_evidence_backed_pilot_stage1_sources_20260629"
    / "cases"
    / "B06_sme_lending"
    / "source_registry.json"
)


def _source(**overrides: object) -> dict:
    source = {
        "source_id": "S1",
        "case_id": "B06",
        "title": "Official credit risk guidance",
        "url_or_local_ref": "https://example.test/credit-risk-guidance",
        "source_type": "official_report",
        "publisher_or_author": "Example Regulator",
        "publication_date": "2026-01-01",
        "access_date": "2026-06-29",
        "as_of_relevance": "Current regulatory guidance for model governance context.",
        "authority_tier": "regulatory",
        "independence": "regulator",
        "potential_bias": "Supervisory perspective; not a product design recipe.",
        "retrieval_status": "full_text_accessed",
        "full_text_available": True,
        "full_text_accessed": True,
        "full_text_hash_or_excerpt_ref": "sha256:example",
        "captured_excerpt_or_span": "Section 2 states banks should monitor credit risk and maintain review controls.",
        "captured_excerpt_summary": "Supports governance and monitoring, not model performance.",
        "source_limitations": "Does not provide SME-specific coefficient design or model accuracy.",
        "usable_for_claim_categories": ["financial_risk_recommendation", "governance_claim"],
        "not_usable_for": ["model performance guarantee", "automatic credit decisioning"],
        "next_stage_verification_notes": "Use only for cautious governance claims.",
    }
    source.update(overrides)
    return source


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_valid_registry_passes() -> None:
    result = validate_source_registry([_source()])

    assert result.ok is True
    assert result.errors == []
    assert result.readiness == HOLD_FOR_MORE_SOURCES
    assert result.source_count == 1
    assert result.full_text_accessed_count == 1


def test_missing_required_field_fails() -> None:
    source = _source()
    source.pop("source_limitations")

    result = validate_source_registry([source])

    assert result.ok is False
    assert "source_registry[0]:missing_field:source_limitations" in result.errors


def test_empty_source_limitations_fails() -> None:
    result = validate_source_registry([_source(source_limitations="")])

    assert result.ok is False
    assert "source_registry[0]:empty_field:source_limitations" in result.errors


def test_empty_usable_for_claim_categories_fails() -> None:
    result = validate_source_registry([_source(usable_for_claim_categories=[])])

    assert result.ok is False
    assert "source_registry[0]:empty_field:usable_for_claim_categories" in result.errors


def test_duplicate_source_id_fails() -> None:
    result = validate_source_registry([_source(source_id="S1"), _source(source_id="S1", url_or_local_ref="https://example.test/other")])

    assert result.ok is False
    assert "source_registry[1]:duplicate_source_id:S1" in result.errors


def test_duplicate_url_warns() -> None:
    result = validate_source_registry([_source(source_id="S1"), _source(source_id="S2")])

    assert result.ok is True
    assert any("duplicate_url_or_local_ref" in warning for warning in result.warnings)


def test_normalize_preserves_facts_and_does_not_invent_fields() -> None:
    registry = [{"source_id": "S1", "full_text_accessed": False, "custom_note": "keep"}]

    normalized = normalize_source_registry(registry)

    entry = normalized["source_registry"][0]
    assert entry["source_id"] == "S1"
    assert entry["full_text_accessed"] is False
    assert entry["custom_note"] == "keep"
    assert "title" not in entry


def test_render_markdown_contains_required_sections_and_limitations() -> None:
    markdown = render_source_registry_review([_source()])

    expected = [
        "# Source Registry Workflow Review",
        "## Summary",
        "## Validation Result",
        "## Counts",
        "## Errors",
        "## Warnings",
        "## Source Quality Scores",
        "## Full-Text / Excerpt Capture Review",
        "## High-Risk Source Control",
        "## Next-Stage Readiness",
        "## Source-Level Notes",
        "Does not provide SME-specific coefficient design",
    ]
    for text in expected:
        assert text in markdown


def test_score_source_registry_is_deterministic_and_registry_only() -> None:
    scores_a = score_source_registry([_source()])
    scores_b = score_source_registry([_source()])

    assert scores_a == scores_b
    assert set(scores_a) == {
        "source_count_sufficiency",
        "authority_mix",
        "source_relevance_proxy",
        "recency_handling",
        "fulltext_capture_quality",
        "bias_handling",
        "claim_category_coverage",
        "high_risk_source_control",
        "next_stage_readiness",
        "overall_score",
    }


def test_validate_does_not_mutate_input_registry() -> None:
    registry = [_source()]
    before = copy.deepcopy(registry)

    validate_source_registry(registry)

    assert registry == before


def test_write_registry_review_writes_markdown_json_and_normalized(tmp_path: Path) -> None:
    result = write_registry_review([_source()], tmp_path / "review")

    assert Path(result["review_markdown"]).exists()
    assert Path(result["review_json"]).exists()
    assert Path(result["normalized_json"]).exists()
    assert result["validation"]["ok"] is True


def test_load_registry_json_accepts_list(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    _write_json(path, [_source()])

    assert isinstance(load_registry_json(path), list)


def test_validate_cli_invalid_exits_nonzero(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    _write_json(path, [_source(source_limitations="")])

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", "--input", str(path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "empty_field:source_limitations" in completed.stdout


def test_validate_cli_valid_exits_zero(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    _write_json(
        path,
        [
            _source(source_id="S1", url_or_local_ref="https://example.test/credit-risk-guidance-1"),
            _source(source_id="S2", url_or_local_ref="https://example.test/credit-risk-guidance-2"),
            _source(source_id="S3", url_or_local_ref="https://example.test/credit-risk-guidance-3"),
        ],
    )

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", "--input", str(path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert READY_FOR_EVIDENCE_PACKET_V2 in completed.stdout


def test_review_cli_writes_markdown_and_json_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    output = tmp_path / "review.md"
    _write_json(path, [_source()])

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "review", "--input", str(path), "--output", str(output)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert "# Source Registry Workflow Review" in output.read_text(encoding="utf-8")


def test_normalize_cli_writes_json(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    output = tmp_path / "normalized.json"
    _write_json(path, [_source()])

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "normalize", "--input", str(path), "--output", str(output)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["source_registry"][0]["source_id"] == "S1"


def test_b01_stage1_registry_validates_without_fulltext_false_errors() -> None:
    registry = load_registry_json(B01_STAGE1_REGISTRY)

    result = validate_source_registry(registry)

    assert result.ok is True
    assert result.readiness in {READY_FOR_EVIDENCE_PACKET_V2, READY_WITH_LIMITATIONS}
    assert result.full_text_accessed_count == 8
    assert result.excerpt_or_span_capture_count == 8
    assert result.fulltext_rule_violations == []


def test_b06_stage1_registry_validates_without_fulltext_false_errors() -> None:
    registry = load_registry_json(B06_STAGE1_REGISTRY)

    result = validate_source_registry(registry)

    assert result.ok is True
    assert result.readiness in {READY_FOR_EVIDENCE_PACKET_V2, READY_WITH_LIMITATIONS}
    assert result.full_text_accessed_count == 9
    assert result.excerpt_or_span_capture_count == 9
    assert result.fulltext_rule_violations == []


def test_module_has_no_network_llm_runner_or_evidence_packet_imports() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    forbidden = [
        "requests",
        "urllib",
        "socket",
        "http.client",
        "openai",
        "anthropic",
        "task_engine_runner",
        "task_engine_executors",
        "topic_refinement",
        "evidence_packet_v2",
        "git clone",
    ]
    for token in forbidden:
        assert token not in source
