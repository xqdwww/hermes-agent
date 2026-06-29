import copy

from tools.source_registry_workflow import validate_source_registry


def _source(**overrides: object) -> dict:
    source = {
        "source_id": "S1",
        "case_id": "B01",
        "title": "SaaS benchmark report",
        "url_or_local_ref": "https://example.test/saas-benchmark",
        "source_type": "saas_benchmark_report",
        "publisher_or_author": "Example Benchmark Publisher",
        "publication_date": "2023-01-01",
        "access_date": "2026-06-29",
        "as_of_relevance": "Dated benchmark for market context only.",
        "authority_tier": "industry_benchmark",
        "independence": "industry_report",
        "potential_bias": "Survey publisher may overrepresent its ecosystem.",
        "retrieval_status": "full_text_accessed",
        "full_text_available": True,
        "full_text_accessed": True,
        "full_text_hash_or_excerpt_ref": "sha256:benchmark",
        "captured_excerpt_or_span": "Report section states pricing and packaging are common SaaS growth levers.",
        "captured_excerpt_summary": "Supports market context, not a causal claim.",
        "source_limitations": "Cannot prove this startup should tier pricing.",
        "usable_for_claim_categories": ["pricing_signal_claim"],
        "not_usable_for": ["causal conversion impact"],
        "next_stage_verification_notes": "Use only for context and cautious pricing signal claims.",
    }
    source.update(overrides)
    return source


def test_full_text_accessed_true_without_excerpt_span_or_ref_fails() -> None:
    result = validate_source_registry(
        [
            _source(
                captured_excerpt_or_span="",
                full_text_hash_or_excerpt_ref="",
            )
        ]
    )

    assert result.ok is False
    assert "source_registry[0]:full_text_accessed_requires_excerpt_span_or_ref" in result.errors
    assert "source_registry[0]:full_text_accessed_requires_excerpt_span_or_ref" in result.fulltext_rule_violations


def test_full_text_accessed_true_with_search_snippet_retrieval_fails() -> None:
    result = validate_source_registry([_source(retrieval_status="search_result_snippet")])

    assert result.ok is False
    assert "source_registry[0]:full_text_accessed_invalid_retrieval_status:search_result_snippet" in result.errors
    assert "source_registry[0]:snippet_or_metadata_source_cannot_be_full_text_accessed" in result.errors


def test_full_text_accessed_true_with_full_text_available_false_fails() -> None:
    result = validate_source_registry([_source(full_text_available=False)])

    assert result.ok is False
    assert "source_registry[0]:full_text_accessed_requires_full_text_available" in result.errors


def test_full_text_accessed_false_but_available_without_excerpt_warns() -> None:
    result = validate_source_registry(
        [
            _source(
                full_text_accessed=False,
                full_text_hash_or_excerpt_ref="",
                captured_excerpt_or_span="",
                retrieval_status="source_accessible",
            )
        ]
    )

    assert result.ok is True
    assert any("full_text_available_without_accessed_excerpt_or_ref" in warning for warning in result.warnings)


def test_long_excerpt_warns() -> None:
    result = validate_source_registry([_source(captured_excerpt_or_span="x" * 1300)])

    assert result.ok is True
    assert any("captured_excerpt_or_span_exceeds_1200_chars" in warning for warning in result.warnings)


def test_vendor_blog_consulting_with_no_bias_label_fails() -> None:
    result = validate_source_registry(
        [
            _source(
                source_type="primary_vendor_pricing_page",
                authority_tier="vendor",
                potential_bias="none",
            )
        ]
    )

    assert result.ok is False
    assert "source_registry[0]:bias_required_for_source_type:primary_vendor_pricing_page" in result.errors


def test_statistic_or_report_source_with_empty_as_of_relevance_fails() -> None:
    result = validate_source_registry([_source(as_of_relevance="")])

    assert result.ok is False
    assert "source_registry[0]:as_of_relevance_required_for_dated_source" in result.errors


def test_high_risk_category_without_authoritative_source_fails() -> None:
    result = validate_source_registry(
        [
            _source(
                authority_tier="vendor",
                source_type="primary_vendor_blog",
                potential_bias="Vendor marketing source; limited support scope.",
                usable_for_claim_categories=["financial_risk_recommendation"],
            )
        ]
    )

    assert result.ok is False
    assert "high_risk_category_without_authoritative_source:financial_risk" in result.high_risk_rule_violations


def test_accepted_high_risk_category_with_regulatory_source_passes() -> None:
    result = validate_source_registry(
        [
            _source(
                case_id="B06",
                source_type="regulatory_model_risk_guidance",
                authority_tier="tier_1_regulatory",
                usable_for_claim_categories=["financial_risk_recommendation", "model_risk_claim"],
                potential_bias="Supervisory source; not a bank-specific implementation guide.",
            )
        ]
    )

    assert result.ok is True
    assert result.high_risk_rule_violations == []
    assert result.high_authority_count == 1


def test_empty_not_usable_for_warns() -> None:
    result = validate_source_registry([_source(not_usable_for=[])])

    assert result.ok is True
    assert any("not_usable_for_should_be_explicit" in warning for warning in result.warnings)


def test_validation_does_not_mutate_policy_input() -> None:
    registry = [_source(not_usable_for=[])]
    before = copy.deepcopy(registry)

    validate_source_registry(registry)

    assert registry == before
