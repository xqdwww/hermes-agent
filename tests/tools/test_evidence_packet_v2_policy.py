from tools.evidence_packet_v2 import build_minimal_sample_packet, validate_packet


def _packet() -> dict:
    return build_minimal_sample_packet("B06_sme_lending", "Should we use early-warning models for SME lending risk?")


def test_simulated_evidence_cannot_be_full_text_verified() -> None:
    packet = _packet()
    packet["claim_table_v2"][0]["full_text_verified"] = True

    result = validate_packet(packet)

    assert result.ok is False
    assert "claim_table_v2[0]:full_text_verified_forbidden_in_simulated_evidence_mode" in result.errors
    assert "claim_table_v2[0]:full_text_verified_forbidden_for_simulated_fixture_basis" in result.errors


def test_snippet_basis_cannot_be_full_text_verified() -> None:
    packet = _packet()
    packet["metadata"]["evidence_mode"] = "web_search"
    packet["metadata"]["full_text_acquisition_used"] = True
    packet["claim_table_v2"][0]["source_basis"] = "snippet"
    packet["claim_table_v2"][0]["retrieval_status"] = "source_accessible"
    packet["claim_table_v2"][0]["full_text_verified"] = True

    result = validate_packet(packet)

    assert result.ok is False
    assert "claim_table_v2[0]:full_text_verified_forbidden_for_snippet_basis" in result.errors


def test_full_text_verified_true_fails_when_metadata_full_text_acquisition_false() -> None:
    packet = _packet()
    packet["metadata"]["evidence_mode"] = "mixed"
    packet["claim_table_v2"][0]["source_basis"] = "primary_source"
    packet["claim_table_v2"][0]["retrieval_status"] = "full_text_accessed"
    packet["claim_table_v2"][0]["full_text_verified"] = True

    result = validate_packet(packet)

    assert result.ok is False
    assert "claim_table_v2[0]:full_text_verified_requires_metadata_full_text_acquisition_used" in result.errors


def test_upgrade_allowed_blocked_for_unverified_claim() -> None:
    packet = _packet()
    packet["claim_table_v2"][0]["claim_type"] = "market_claim"
    packet["claim_table_v2"][0]["confidence_effect"] = "upgrade_allowed"

    result = validate_packet(packet)

    assert result.ok is False
    assert "claim_table_v2[0]:upgrade_allowed_forbidden_for_support_level:unverified" in result.errors
    assert result.confidence_upgrade_blocked is True


def test_upgrade_allowed_blocked_for_high_risk_claim_without_full_text_verified() -> None:
    packet = _packet()
    packet["metadata"]["evidence_mode"] = "mixed"
    packet["claim_table_v2"][0]["support_level"] = "strongly_supported"
    packet["claim_table_v2"][0]["confidence_effect"] = "upgrade_allowed"

    result = validate_packet(packet)

    assert result.ok is False
    assert "claim_table_v2[0]:upgrade_allowed_forbidden_for_high_risk_without_full_text_verified" in result.errors
    assert result.high_risk_claims == ["C1"]


def test_unresolved_contradiction_forces_source_need_downgrade_remove_or_expert_review() -> None:
    packet = _packet()
    packet["claim_table_v2"][0]["contradiction_status"] = "unresolved"
    packet["claim_table_v2"][0]["confidence_effect"] = "keep"
    packet["claim_table_v2"][0]["final_allowed_wording"] = "Use as a verified fact."
    packet["verification_matrix"][0]["confidence_delta"] = "none"

    result = validate_packet(packet)

    assert result.ok is False
    assert result.source_need_required is True
    assert "claim_table_v2[0]:contradiction_requires_downgrade_source_need_remove_or_expert_review" in result.errors
    assert "claim_table_v2[0]:contradiction_final_allowed_wording_must_not_be_strong_assertion" in result.errors
    assert "verification_matrix[0]:unresolved_contradiction_requires_non_upgrade_confidence_delta" in result.errors


def test_unverified_claim_requires_uncertainty_or_removal_wording() -> None:
    packet = _packet()
    packet["claim_table_v2"][0]["final_allowed_wording"] = "Use as a verified fact."

    result = validate_packet(packet)

    assert result.ok is False
    assert "claim_table_v2[0]:unsupported_claim_requires_uncertainty_or_removal_wording" in result.errors


def test_simulated_evidence_mode_blocks_global_confidence_upgrade() -> None:
    packet = _packet()
    packet["claim_table_v2"][0]["support_level"] = "strongly_supported"
    packet["claim_table_v2"][0]["confidence_effect"] = "upgrade_allowed"

    result = validate_packet(packet)

    assert result.ok is False
    assert result.confidence_upgrade_blocked is True
    assert "claim_table_v2[0]:upgrade_allowed_forbidden_in_simulated_evidence_mode" in result.errors
    assert any("simulated_evidence_limitation" in warning for warning in result.warnings)
