from __future__ import annotations

import json
from pathlib import Path

from tools import topic_refinement_post_final_advisory_report as report
from tools.task_engine_contracts import ENGINE_DECISION, ENGINE_RESEARCH_DECISION, PIPELINE_COMPLETE
from tools.task_engine_executors import _research_evidence_packet_quality_error
from tools.task_engine_runner import task_engine_runner


def _run_simulated(tmp_path: Path, *, emit: bool | str | None = None, mode: str = ENGINE_RESEARCH_DECISION) -> tuple[dict, Path]:
    run_dir = tmp_path / "simulated"
    kwargs = {
        "query": "Should this decision use the safe simulated runner for validation?",
        "mode": mode,
        "action": "simulated-run",
        "base_dir": str(run_dir),
    }
    if emit is not None:
        kwargs["emit_topic_refinement_advisory"] = emit
    result = json.loads(task_engine_runner(**kwargs))
    return result, run_dir


def test_simulated_run_emits_contract_compliant_research_packet(tmp_path: Path) -> None:
    result, run_dir = _run_simulated(tmp_path)
    packet = run_dir / "L5_deepseek_acceptance" / "research_evidence_packet.md"
    text = packet.read_text(encoding="utf-8")

    assert result["status"] == "ok"
    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert result["validation"]["valid"] is True
    assert packet.exists()
    assert "## claim_table" in text
    assert "claim_id: SIM-C1" in text
    assert "source_anchors:" in text
    assert "evidence_strength:" in text
    assert "epistemic_tier:" in text
    assert _research_evidence_packet_quality_error(text) == ""


def test_simulated_run_packet_preserves_fixture_evidence_boundaries(tmp_path: Path) -> None:
    _, run_dir = _run_simulated(tmp_path)
    text = (run_dir / "L5_deepseek_acceptance" / "research_evidence_packet.md").read_text(encoding="utf-8")
    lowered = text.lower()

    assert "full_text_verified: false" in lowered
    assert "full_text_verified: true" not in lowered
    assert "full-text verification completed" not in lowered
    assert "evidence_boundary:" in lowered
    assert "source_limitations:" in lowered
    assert "simulated_fixture" in lowered


def test_simulated_run_reaches_pipeline_complete_for_decision_and_research_decision(tmp_path: Path) -> None:
    for mode in (ENGINE_DECISION, ENGINE_RESEARCH_DECISION):
        result, run_dir = _run_simulated(tmp_path / mode, mode=mode)

        assert result["pipeline_status"] == PIPELINE_COMPLETE
        assert result["validation"]["errors"] == []
        assert (run_dir / "runner_result.json").exists()
        assert (run_dir / "final_controller_report.md").exists()
        assert (run_dir / "case_quality_review.md").exists()
        assert (run_dir / "research_evidence_packet.md").exists() == (mode == ENGINE_RESEARCH_DECISION)


def test_simulated_run_flag_true_after_complete_emits_advisory_sidecar(tmp_path: Path) -> None:
    result, run_dir = _run_simulated(tmp_path, emit=True)
    sidecar = run_dir / "topic_refinement_advisory"
    payload = json.loads((sidecar / report.REPORT_JSON).read_text(encoding="utf-8"))

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert (sidecar / report.REPORT_MD).exists()
    assert (sidecar / report.DETECTOR_OUTPUT_DIR / "post_final_advisory_report.json").exists()
    assert payload["status"] == report.PASS_REPORT_ONLY_SOURCE_NEED_ADVISED
    assert payload["no_adapter_called"] is True
    assert payload["no_manual_task_called"] is True
    assert payload["no_llm_called"] is True
    assert payload["no_pipeline_rerun"] is True
    assert payload["no_candidate_generated"] is True
    assert payload["no_final_rewritten"] is True


def test_simulated_run_flag_absent_or_false_emits_no_advisory_sidecar(tmp_path: Path) -> None:
    _, absent_dir = _run_simulated(tmp_path / "absent")
    _, false_dir = _run_simulated(tmp_path / "false", emit=False)

    assert not (absent_dir / "topic_refinement_advisory").exists()
    assert not (false_dir / "topic_refinement_advisory").exists()
