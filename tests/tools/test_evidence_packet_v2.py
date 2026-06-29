import copy
import json
import subprocess
import sys
from pathlib import Path

from tools.evidence_packet_v2 import (
    build_minimal_sample_packet,
    render_packet_markdown,
    validate_packet,
    write_packet_outputs,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "evidence_packet_v2.py"


def _packet() -> dict:
    return build_minimal_sample_packet("B01_pricing_packaging", "How should we package SaaS pricing?")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_valid_minimal_packet_passes() -> None:
    result = validate_packet(_packet())

    assert result.ok is True
    assert result.errors == []
    assert result.confidence_upgrade_blocked is True
    assert any("simulated_evidence_limitation" in item for item in result.warnings)


def test_missing_top_level_section_fails() -> None:
    packet = _packet()
    packet.pop("claim_table_v2")

    result = validate_packet(packet)

    assert result.ok is False
    assert "missing_section:claim_table_v2" in result.errors


def test_missing_claim_field_fails() -> None:
    packet = _packet()
    del packet["claim_table_v2"][0]["final_allowed_wording"]

    result = validate_packet(packet)

    assert result.ok is False
    assert "claim_table_v2[0]:missing_field:final_allowed_wording" in result.errors


def test_invalid_enum_fails() -> None:
    packet = _packet()
    packet["claim_table_v2"][0]["support_level"] = "certainly_true"

    result = validate_packet(packet)

    assert result.ok is False
    assert "invalid_enum:claim_table_v2[0].support_level:certainly_true" in result.errors


def test_render_output_contains_all_required_sections() -> None:
    markdown = render_packet_markdown(_packet())

    expected = [
        "# Evidence Packet v2",
        "## Metadata",
        "## User Question Obligations",
        "## Claim Table v2",
        "## Source Registry",
        "## Citation-Claim Pairs",
        "## Verification Matrix",
        "## Contradiction Table",
        "## Evidence Boundary",
        "## Confidence Policy",
        "## Final Answer Traceability",
        "## Validation Summary",
    ]
    for heading in expected:
        assert heading in markdown


def test_citation_pair_with_unknown_claim_id_fails() -> None:
    packet = _packet()
    packet["citation_claim_pairs"][0]["claim_id"] = "C999"

    result = validate_packet(packet)

    assert result.ok is False
    assert "citation_claim_pairs[0]:unknown_claim_id:C999" in result.errors


def test_citation_pair_with_unknown_source_id_fails() -> None:
    packet = _packet()
    packet["citation_claim_pairs"][0]["source_id"] = "S999"

    result = validate_packet(packet)

    assert result.ok is False
    assert "citation_claim_pairs[0]:unknown_source_id:S999" in result.errors


def test_verification_matrix_with_unknown_claim_id_fails() -> None:
    packet = _packet()
    packet["verification_matrix"][0]["claim_id"] = "C999"

    result = validate_packet(packet)

    assert result.ok is False
    assert "verification_matrix[0]:unknown_claim_id:C999" in result.errors


def test_claim_source_ids_unknown_source_fails_unless_simulated_fixture_only() -> None:
    packet = _packet()
    packet["claim_table_v2"][0]["source_ids"] = ["UNKNOWN-SOURCE"]

    assert validate_packet(packet).ok is True

    packet["claim_table_v2"][0]["source_basis"] = "web_source"
    result = validate_packet(packet)

    assert result.ok is False
    assert "claim_table_v2[0].source_ids:unknown_source_id:UNKNOWN-SOURCE" in result.errors


def test_final_answer_traceability_unknown_claim_id_fails() -> None:
    packet = _packet()
    packet["final_answer_traceability"][0]["claim_ids_used"] = ["C999"]

    result = validate_packet(packet)

    assert result.ok is False
    assert "final_answer_traceability[0].claim_ids_used:unknown_claim_id:C999" in result.errors


def test_unsupported_claims_removed_required() -> None:
    packet = _packet()
    del packet["final_answer_traceability"][0]["unsupported_claims_removed"]

    result = validate_packet(packet)

    assert result.ok is False
    assert "final_answer_traceability[0]:missing_field:unsupported_claims_removed" in result.errors


def test_caveats_required_required() -> None:
    packet = _packet()
    del packet["final_answer_traceability"][0]["caveats_required"]

    result = validate_packet(packet)

    assert result.ok is False
    assert "final_answer_traceability[0]:missing_field:caveats_required" in result.errors


def test_sample_command_writes_packet_and_markdown(tmp_path: Path) -> None:
    question = tmp_path / "question.txt"
    question.write_text("Should we change packaging?", encoding="utf-8")
    out = tmp_path / "sample"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "sample", "--case-id", "B01", "--user-question-file", str(question), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (out / "packet.json").exists()
    assert (out / "packet.md").exists()
    report = json.loads((out / "validation_report.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["confidence_upgrade_blocked"] is True


def test_validate_command_returns_nonzero_on_invalid_packet(tmp_path: Path) -> None:
    packet = _packet()
    packet.pop("metadata")
    path = tmp_path / "packet.json"
    _write_json(path, packet)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", "--input", str(path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "missing_section:metadata" in completed.stdout


def test_render_command_writes_deterministic_markdown(tmp_path: Path) -> None:
    packet_path = tmp_path / "packet.json"
    output_a = tmp_path / "packet_a.md"
    output_b = tmp_path / "packet_b.md"
    _write_json(packet_path, _packet())

    for output in (output_a, output_b):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "render", "--input", str(packet_path), "--output", str(output)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    assert output_a.read_text(encoding="utf-8") == output_b.read_text(encoding="utf-8")


def test_write_packet_outputs_writes_json_markdown_and_report(tmp_path: Path) -> None:
    result = write_packet_outputs(_packet(), tmp_path / "out")

    assert Path(result["packet_json"]).exists()
    assert Path(result["packet_markdown"]).exists()
    assert Path(result["validation_report"]).exists()
    assert result["validation"]["ok"] is True


def test_validation_does_not_mutate_input_packet() -> None:
    packet = _packet()
    before = copy.deepcopy(packet)

    validate_packet(packet)

    assert packet == before


def test_module_has_no_network_llm_external_repo_or_runner_imports() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    forbidden = [
        "requests",
        "urllib",
        "socket",
        "http.client",
        "openai",
        "anthropic",
        "subprocess",
        "task_engine_runner",
        "task_engine_executors",
        "topic_refinement",
        "git clone",
    ]
    for token in forbidden:
        assert token not in source
