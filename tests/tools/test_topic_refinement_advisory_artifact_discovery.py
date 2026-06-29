from __future__ import annotations

import json
from pathlib import Path

from tools import topic_refinement_post_final_advisory_detector as detector
from tools import topic_refinement_post_final_advisory_report as report


def _write_actual_runner_named_artifacts(run_dir: Path) -> None:
    final_dir = run_dir / "final_controller_report"
    final_dir.mkdir(parents=True)
    (final_dir / "final_decision_report.md").write_text("FINAL CONTROLLER BODY with bounded recommendation.\n", encoding="utf-8")
    (run_dir / "case_quality_review.md").write_text("final too generic and low specificity\n", encoding="utf-8")
    (run_dir / "evidence_packet.md").write_text("Evidence packet alias with bounded evidence and no source acquisition claim.\n", encoding="utf-8")
    (run_dir / "runner_result.json").write_text('{"pipeline_status":"PIPELINE_COMPLETE"}\n', encoding="utf-8")
    (run_dir / "original_user_question.txt").write_text("Original decision question\n", encoding="utf-8")


def test_detector_discovers_actual_runner_final_decision_report_alias(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_actual_runner_named_artifacts(run_dir)

    artifacts, escaped = detector.discover_artifacts(run_dir)

    assert escaped is None
    assert artifacts["final_v1"] == run_dir / "final_controller_report" / "final_decision_report.md"
    assert artifacts["quality_review"] == run_dir / "case_quality_review.md"
    assert artifacts["research_evidence_packet"] == run_dir / "evidence_packet.md"


def test_report_wrapper_uses_actual_runner_aliases_without_adapter_or_llm(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "advisory"
    _write_actual_runner_named_artifacts(run_dir)

    result = report.generate_post_final_topic_refinement_advisory_report(
        run_dir=run_dir,
        topic_id="alias_discovery",
        output_dir=output_dir,
        user_feedback="same topic refine",
    )
    payload = json.loads((output_dir / report.REPORT_JSON).read_text(encoding="utf-8"))

    assert result.exit_code == 0
    assert payload["status"] == report.PASS_REPORT_ONLY_ADVISORY_GENERATED
    assert payload["user_confirmation_required"] is True
    assert payload["no_adapter_called"] is True
    assert payload["no_manual_task_called"] is True
    assert payload["no_llm_called"] is True
    assert payload["no_pipeline_rerun"] is True
    assert payload["no_candidate_generated"] is True
    assert payload["no_final_rewritten"] is True
