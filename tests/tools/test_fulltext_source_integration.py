import copy
import json
import subprocess
import sys
from pathlib import Path

from tools.fulltext_source_integration import (
    BLOCKED,
    READY_FOR_STAGEB_PACKET_INPUT,
    build_source_handoff_manifest,
    link_source_registry_to_evidence_packet_inputs,
    load_json,
    render_fulltext_handoff_review,
    validate_fulltext_handoff_manifest,
    verify_excerpt_refs_exist,
    write_handoff_outputs,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "fulltext_source_integration.py"
STAGEA_ROOT = REPO_ROOT / "outputs" / "one_pass_8case_evidence_backed_blind_set_20260630" / "stageA_sources" / "cases"


def _handoff(**overrides: object) -> dict:
    item = {
        "source_id": "S1",
        "case_id": "E07",
        "registry_path": "source_registry.json",
        "url_or_local_ref": "https://example.test/source",
        "retrieval_status": "full_text_accessed",
        "full_text_available": True,
        "full_text_accessed": True,
        "excerpt_ref_id": "S1:section-2",
        "excerpt_or_span": "Section 2 says human approval is needed before risky automated actions.",
        "excerpt_summary": "Supports human approval and operating limits.",
        "section_locator": "Section 2",
        "access_date": "2026-06-30",
        "source_hash_or_locator": "S1:section-2",
        "allowed_claim_categories": ["soc_automation", "human_review"],
        "prohibited_claim_categories": ["vendor performance guarantee"],
        "full_text_verified_allowed": True,
        "high_risk_allowed": True,
        "caveats": ["Official source; applies to governance, not product performance."],
        "handoff_ready": True,
        "source_type": "official_security_guidance",
        "authority_tier": "official",
        "potential_bias": "Official guidance; broad applicability.",
    }
    item.update(overrides)
    return item


def _manifest(*items: dict, registry_source_ids: list[str] | None = None) -> dict:
    return {
        "metadata": {"stage": "fulltext_source_handoff"},
        "registry_source_ids": registry_source_ids if registry_source_ids is not None else [item["source_id"] for item in items],
        "handoff_items": list(items),
    }


def _registry() -> list[dict]:
    return [
        {
            "source_id": "S1",
            "case_id": "E07",
            "url_or_local_ref": "https://example.test/source",
            "captured_excerpt_or_span": "Section 2 says human approval is needed before risky automated actions.",
            "full_text_hash_or_excerpt_ref": "S1:section-2",
        }
    ]


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_valid_handoff_manifest_passes() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_handoff()))

    assert result.ok is True
    assert result.errors == []
    assert result.readiness == READY_FOR_STAGEB_PACKET_INPUT
    assert result.full_text_verified_allowed_count == 1
    assert result.high_risk_allowed_count == 1


def test_missing_required_field_fails() -> None:
    item = _handoff()
    item.pop("caveats")

    result = validate_fulltext_handoff_manifest(_manifest(item))

    assert result.ok is False
    assert "handoff_items[0]:missing_field:caveats" in result.errors


def test_duplicate_source_id_fails() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_handoff(source_id="S1"), _handoff(source_id="S1")))

    assert result.ok is False
    assert "handoff_items[1]:duplicate_source_id:S1" in result.errors


def test_manifest_cannot_include_source_absent_from_registry_ids() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_handoff(source_id="S2"), registry_source_ids=["S1"]))

    assert result.ok is False
    assert "handoff_items[0]:source_absent_from_registry:S2" in result.errors


def test_verify_excerpt_refs_exist_fails_for_manifest_source_absent_from_registry() -> None:
    result = verify_excerpt_refs_exist(_registry(), _manifest(_handoff(source_id="S2")))

    assert result.ok is False
    assert "handoff_items[0]:source_absent_from_registry:S2" in result.errors


def test_link_output_preserves_source_ids_and_does_not_set_support_levels() -> None:
    manifest = _manifest(_handoff())
    linked = link_source_registry_to_evidence_packet_inputs(_registry(), manifest)

    entry = linked["source_handoff_for_packet_v2"][0]
    assert entry["source_id"] == "S1"
    assert entry["allowed_claim_categories"] == ["soc_automation", "human_review"]
    assert entry["prohibited_claim_categories"] == ["vendor performance guarantee"]
    assert entry["caveats"] == ["Official source; applies to governance, not product performance."]
    assert linked["claim_support_levels_set"] is False
    assert linked["claim_verification_results_set"] is False


def test_link_output_does_not_mutate_inputs() -> None:
    registry = _registry()
    manifest = _manifest(_handoff())
    registry_before = copy.deepcopy(registry)
    manifest_before = copy.deepcopy(manifest)

    link_source_registry_to_evidence_packet_inputs(registry, manifest)

    assert registry == registry_before
    assert manifest == manifest_before


def test_render_markdown_contains_required_sections() -> None:
    markdown = render_fulltext_handoff_review(_manifest(_handoff()))

    expected = [
        "# Full-Text Source Handoff Review",
        "## Summary",
        "## Validation Result",
        "## Counts",
        "## Errors",
        "## Warnings",
        "## Full-Text Verification Allowance",
        "## High-Risk Allowance",
        "## Snippet / Metadata Blocks",
        "## Bias Caveat Carry-Forward",
        "## Source-Level Handoff Notes",
        "## Next-Stage Readiness",
    ]
    for text in expected:
        assert text in markdown


def test_write_handoff_outputs_writes_manifest_validation_and_review(tmp_path: Path) -> None:
    result = write_handoff_outputs(_manifest(_handoff()), tmp_path / "handoff")

    assert Path(result["manifest_json"]).exists()
    assert Path(result["validation_json"]).exists()
    assert Path(result["review_markdown"]).exists()
    assert result["validation"]["ok"] is True


def test_load_json_accepts_object(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    _write_json(path, _manifest(_handoff()))

    assert isinstance(load_json(path), dict)


def test_validate_cli_valid_exits_zero(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    _write_json(path, _manifest(_handoff()))

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", "--input", str(path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert READY_FOR_STAGEB_PACKET_INPUT in completed.stdout


def test_validate_cli_invalid_exits_nonzero(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    _write_json(path, _manifest(_handoff(full_text_accessed=False)))

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", "--input", str(path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "full_text_verified_allowed_requires_full_text_accessed" in completed.stdout


def test_review_cli_writes_markdown_and_json_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    output = tmp_path / "review.md"
    _write_json(path, _manifest(_handoff()))

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
    assert "# Full-Text Source Handoff Review" in output.read_text(encoding="utf-8")


def test_build_manifest_from_fixture_writes_json(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    registry = [
        {
            "source_id": "S1",
            "case_id": "E01",
            "url_or_local_ref": "https://example.test/source",
            "retrieval_status": "full_text_accessed",
            "full_text_available": True,
            "full_text_accessed": True,
            "full_text_hash_or_excerpt_ref": "S1:section",
            "captured_excerpt_or_span": "Section says governance controls are needed.",
            "captured_excerpt_summary": "Governance controls.",
            "access_date": "2026-06-30",
            "usable_for_claim_categories": ["governance"],
            "not_usable_for": ["performance guarantee"],
            "potential_bias": "Official source; broad applicability.",
            "source_limitations": "Not product-specific.",
            "next_stage_verification_notes": "Use cautiously.",
            "source_type": "official_guidance",
            "authority_tier": "official",
        }
    ]
    _write_json(case_dir / "source_registry.json", registry)
    output = tmp_path / "manifest.json"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "build-manifest", "--stageA-case-dir", str(case_dir), "--output", str(output)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.exists()
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["handoff_items"][0]["source_id"] == "S1"


def test_real_stageA_limitation_and_pass_cases_build_and_validate() -> None:
    case_ids = [
        "E03_predictive_maintenance_manufacturing",
        "E05_clinic_scheduling_ai",
        "E08_customer_success_churn_health_score",
        "E01_enterprise_rag_governance",
    ]
    for case_id in case_ids:
        manifest = build_source_handoff_manifest(STAGEA_ROOT / case_id)
        result = validate_fulltext_handoff_manifest(manifest)
        assert result.ok is True, (case_id, result.errors)
        assert result.source_count >= 5
        assert result.readiness in {READY_FOR_STAGEB_PACKET_INPUT, "READY_WITH_LIMITATIONS"}


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
