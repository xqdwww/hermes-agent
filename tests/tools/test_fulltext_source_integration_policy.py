import copy

from tools.fulltext_source_integration import BLOCKED, READY_WITH_LIMITATIONS, validate_fulltext_handoff_manifest


def _item(**overrides: object) -> dict:
    item = {
        "source_id": "S1",
        "case_id": "E05",
        "registry_path": "source_registry.json",
        "url_or_local_ref": "https://example.test/source",
        "retrieval_status": "full_text_accessed",
        "full_text_available": True,
        "full_text_accessed": True,
        "excerpt_ref_id": "S1:section",
        "excerpt_or_span": "Section states that governance and human review are required for safety-critical operations.",
        "excerpt_summary": "Supports governance and human review.",
        "section_locator": "Section 4",
        "access_date": "2026-06-30",
        "source_hash_or_locator": "S1:section",
        "allowed_claim_categories": ["medical_health", "human_review"],
        "prohibited_claim_categories": ["automated clinical decisioning"],
        "full_text_verified_allowed": True,
        "high_risk_allowed": True,
        "caveats": ["Official guidance; broad applicability and not a product performance claim."],
        "handoff_ready": True,
        "source_type": "official_health_guidance",
        "authority_tier": "official",
        "potential_bias": "Official guidance; broad applicability.",
    }
    item.update(overrides)
    return item


def _manifest(item: dict) -> dict:
    return {"registry_source_ids": ["S1"], "handoff_items": [item]}


def test_full_text_verified_allowed_true_without_full_text_accessed_fails() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_item(full_text_accessed=False)))

    assert result.ok is False
    assert "handoff_items[0]:full_text_verified_allowed_requires_full_text_accessed" in result.errors


def test_full_text_verified_allowed_true_without_excerpt_or_section_locator_fails() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_item(excerpt_or_span="", section_locator="")))

    assert result.ok is False
    assert "handoff_items[0]:full_text_verified_allowed_requires_excerpt_or_section_locator" in result.errors


def test_snippet_source_cannot_full_text_verified_allowed() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_item(retrieval_status="search_result_snippet")))

    assert result.ok is False
    assert "handoff_items[0]:snippet_or_metadata_cannot_full_text_verified_allowed" in result.errors
    assert result.snippet_block_count == 1


def test_missing_excerpt_ref_fails_when_full_text_verified_allowed_true() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_item(excerpt_ref_id="", source_hash_or_locator="")))

    assert result.ok is False
    assert "handoff_items[0]:full_text_verified_allowed_requires_source_hash_or_excerpt_ref" in result.errors
    assert "handoff_items[0]:full_text_verified_allowed_requires_excerpt_ref_id" in result.errors


def test_long_excerpt_warns() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_item(excerpt_or_span="x" * 1300)))

    assert result.ok is True
    assert any("excerpt_or_span_exceeds_1200_chars" in warning for warning in result.warnings)


def test_handoff_ready_true_requires_allowed_claim_categories_and_caveats() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_item(allowed_claim_categories=[], caveats=[])))

    assert result.ok is False
    assert "handoff_items[0]:handoff_ready_requires_allowed_claim_categories" in result.errors
    assert "handoff_items[0]:handoff_ready_requires_caveats" in result.errors


def test_empty_prohibited_claim_categories_warns() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_item(prohibited_claim_categories=[])))

    assert result.ok is True
    assert result.readiness == READY_WITH_LIMITATIONS
    assert any("prohibited_claim_categories_should_be_explicit" in warning for warning in result.warnings)


def test_handoff_ready_false_blocks_stageb_upgrade_but_not_error() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_item(handoff_ready=False)))

    assert result.ok is True
    assert result.readiness == READY_WITH_LIMITATIONS
    assert result.handoff_ready_count == 0


def test_high_risk_allowed_true_requires_authoritative_tier() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_item(authority_tier="reputable_secondary", source_type="industry_report")))

    assert result.ok is False
    assert "handoff_items[0]:high_risk_allowed_requires_authoritative_tier:reputable_secondary" in result.errors


def test_vendor_blog_consulting_cannot_high_risk_allowed_true() -> None:
    result = validate_fulltext_handoff_manifest(
        _manifest(
            _item(
                authority_tier="vendor",
                source_type="vendor_blog",
                caveats=["Vendor source; marketing bias."],
            )
        )
    )

    assert result.ok is False
    assert "handoff_items[0]:vendor_blog_consulting_cannot_high_risk_allowed" in result.errors


def test_high_risk_allowed_true_requires_full_text_or_authoritative_locator() -> None:
    result = validate_fulltext_handoff_manifest(_manifest(_item(full_text_verified_allowed=False, section_locator="")))

    assert result.ok is False
    assert "handoff_items[0]:high_risk_allowed_requires_full_text_or_authoritative_locator" in result.errors


def test_vendor_blog_consulting_requires_caveat() -> None:
    result = validate_fulltext_handoff_manifest(
        _manifest(
            _item(
                authority_tier="vendor",
                source_type="vendor_blog",
                high_risk_allowed=False,
                caveats=[],
            )
        )
    )

    assert result.ok is False
    assert "handoff_items[0]:vendor_blog_consulting_requires_bias_caveat" in result.errors


def test_validation_does_not_mutate_manifest() -> None:
    manifest = _manifest(_item(prohibited_claim_categories=[]))
    before = copy.deepcopy(manifest)

    validate_fulltext_handoff_manifest(manifest)

    assert manifest == before
