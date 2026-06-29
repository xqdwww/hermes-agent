from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools import topic_refinement_artifact_loader as loader


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools/topic_refinement_artifact_loader.py"


def _write_minimal_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "final_controller_report.md").write_text(
        "Final answer. Caveat: current conclusion remains bounded by available evidence.\n",
        encoding="utf-8",
    )
    (run_dir / "case_quality_review.md").write_text(
        "Quality review: final too generic with low specificity. Calibration not absorbed.\n",
        encoding="utf-8",
    )
    (run_dir / "original_user_question.txt").write_text("Original question?\n", encoding="utf-8")


def _run_loader(run_dir: Path, output_dir: Path, *, topic_id: str = "topic-1", feedback: str = "continue this topic"):
    return loader.load_artifacts(
        run_dir=run_dir,
        topic_id=topic_id,
        user_feedback=feedback,
        output_dir=output_dir,
    )


def _read_state(output_dir: Path) -> dict:
    return json.loads((output_dir / loader.STATE_FILENAME).read_text(encoding="utf-8"))


def test_success_with_minimal_artifacts_generates_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    result = _run_loader(run_dir, output_dir)

    assert result.exit_code == 0
    assert result.status == loader.PASS_STATUS
    assert (output_dir / loader.STATE_FILENAME).exists()


def test_required_state_fields_exist(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    _run_loader(run_dir, output_dir)
    state = _read_state(output_dir)

    required = {
        "schema_version",
        "state_type",
        "loader_version",
        "generated_at_utc",
        "topic_id",
        "original_question",
        "current_final_version",
        "current_final_version_path",
        "artifact_paths",
        "artifact_hashes",
        "user_feedback",
        "user_feedback_history",
        "detected_quality_signals",
        "detected_evidence_boundary_signals",
        "detected_calibration_boundary_signals",
        "detected_environment_signals",
        "selected_failure_type",
        "selected_refinement_mode",
        "selection_tie_breaker_reason",
        "allowed_scope",
        "authorization",
        "preserved_caveats",
        "unresolved_evidence_gaps",
        "confidence_boundary",
        "final_versions",
        "refinement_history",
        "stop_reason",
        "next_action",
        "append_only_warning",
        "no_runtime_integration",
        "no_llm_called",
        "no_pipeline_rerun",
    }
    assert required <= set(state)
    assert state["state_type"] == "topic_refinement_state_initial"


def test_no_failure_type_or_mode_selected(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    _run_loader(run_dir, output_dir)
    state = _read_state(output_dir)

    assert state["selected_failure_type"] is None
    assert state["selected_refinement_mode"] is None
    assert state["selection_tie_breaker_reason"] is None


def test_next_action_is_needs_mode_router(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    _run_loader(run_dir, output_dir)

    assert _read_state(output_dir)["next_action"] == "needs_mode_router"


def test_no_runtime_llm_or_pipeline_flags_are_true(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    _run_loader(run_dir, output_dir)
    state = _read_state(output_dir)

    assert state["no_runtime_integration"] is True
    assert state["no_llm_called"] is True
    assert state["no_pipeline_rerun"] is True


def test_final_versions_contains_final_v1_without_overwrite(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    _run_loader(run_dir, output_dir)
    state = _read_state(output_dir)

    assert state["current_final_version"] == "final_v1"
    assert state["final_versions"] == [
        {
            "version": "final_v1",
            "path": str(run_dir / "final_controller_report.md"),
            "sha256": state["artifact_hashes"]["final_v1"],
            "created_by": "existing_artifact",
            "overwritten": False,
        }
    ]


def test_artifact_hashes_generated(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    _run_loader(run_dir, output_dir)
    hashes = _read_state(output_dir)["artifact_hashes"]

    assert len(hashes["final_v1"]) == 64
    assert len(hashes["quality_review"]) == 64
    assert len(hashes["original_user_question"]) == 64


def test_missing_final_v1_blocks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    run_dir.mkdir()
    (run_dir / "case_quality_review.md").write_text("review", encoding="utf-8")

    result = _run_loader(run_dir, output_dir)

    assert result.exit_code != 0
    blocked = json.loads((output_dir / "artifact_loader_blocked_report.json").read_text(encoding="utf-8"))
    assert blocked["status"] == loader.BLOCKED_MISSING_FINAL_V1


def test_missing_quality_review_blocks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    run_dir.mkdir()
    (run_dir / "final_controller_report.md").write_text("final", encoding="utf-8")

    result = _run_loader(run_dir, output_dir)

    assert result.exit_code != 0
    blocked = json.loads((output_dir / "artifact_loader_blocked_report.json").read_text(encoding="utf-8"))
    assert blocked["status"] == loader.BLOCKED_MISSING_QUALITY_REVIEW


def test_empty_user_feedback_blocks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    result = _run_loader(run_dir, output_dir, feedback="  ")

    assert result.exit_code != 0
    blocked = json.loads((output_dir / "artifact_loader_blocked_report.json").read_text(encoding="utf-8"))
    assert blocked["status"] == loader.BLOCKED_INVALID_USER_FEEDBACK


def test_empty_topic_id_blocks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    result = _run_loader(run_dir, output_dir, topic_id=" ")

    assert result.exit_code != 0
    blocked = json.loads((output_dir / "artifact_loader_blocked_report.json").read_text(encoding="utf-8"))
    assert blocked["status"] == loader.BLOCKED_INVALID_TOPIC_ID


def test_output_already_exists_blocks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)
    output_dir.mkdir()
    (output_dir / loader.STATE_FILENAME).write_text("{}\n", encoding="utf-8")

    result = _run_loader(run_dir, output_dir)

    assert result.exit_code != 0
    blocked = json.loads((output_dir / "artifact_loader_blocked_report.json").read_text(encoding="utf-8"))
    assert blocked["status"] == loader.BLOCKED_OUTPUT_ALREADY_EXISTS


def test_environment_blocker_detection_blocks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)
    (run_dir / "runner_result.json").write_text('{"error":"evidence_judge resource exhausted"}', encoding="utf-8")

    result = _run_loader(run_dir, output_dir)

    assert result.exit_code != 0
    blocked = json.loads((output_dir / "artifact_loader_blocked_report.json").read_text(encoding="utf-8"))
    assert blocked["status"] == loader.BLOCKED_ENVIRONMENT_OR_RUNTIME_ARTIFACT
    assert blocked["selected_refinement_mode"] is None


def test_path_escape_protection_blocks_symlink_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    output_dir = tmp_path / "out"
    run_dir.mkdir()
    outside.mkdir()
    (outside / "final_controller_report.md").write_text("outside final", encoding="utf-8")
    (run_dir / "case_quality_review.md").write_text("review", encoding="utf-8")
    try:
        os.symlink(outside / "final_controller_report.md", run_dir / "final_controller_report.md")
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")

    result = _run_loader(run_dir, output_dir)

    assert result.exit_code != 0
    blocked = json.loads((output_dir / "artifact_loader_blocked_report.json").read_text(encoding="utf-8"))
    assert blocked["status"] == loader.BLOCKED_ARTIFACT_PATH_ESCAPE


def test_detects_evidence_boundary_signals(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)
    (run_dir / "research_evidence_packet.md").write_text(
        "Evidence gap: snippet-backed support needs full-text verification; thin evidence remains speculative.",
        encoding="utf-8",
    )

    _run_loader(run_dir, output_dir)
    signals = _read_state(output_dir)["detected_evidence_boundary_signals"]

    assert "snippet" in signals
    assert "full-text verification" in signals
    assert "thin evidence" in signals
    assert "speculative" in signals
    assert "evidence gap" in signals


def test_detects_calibration_boundary_signals(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)
    (run_dir / "calibration_report.md").write_text(
        "Calibration: overclaim risk; confidence down; caveat required; plausible but speculative and unsupported.",
        encoding="utf-8",
    )

    _run_loader(run_dir, output_dir)
    signals = _read_state(output_dir)["detected_calibration_boundary_signals"]

    assert "overclaim" in signals
    assert "confidence down" in signals
    assert "caveat" in signals
    assert "plausible" in signals
    assert "speculative" in signals
    assert "unsupported" in signals


def test_extracts_preserved_caveats_with_max_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)
    lines = [f"Caveat {i}: limitation remains plausible and unsupported." for i in range(30)]
    (run_dir / "calibration_report.md").write_text("\n".join(lines), encoding="utf-8")

    _run_loader(run_dir, output_dir)
    caveats = _read_state(output_dir)["preserved_caveats"]

    assert len(caveats) == 20
    assert caveats[0].startswith("Caveat 0")


def test_extracts_unresolved_evidence_gaps_with_max_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)
    lines = [f"Evidence gap {i}: snippet-backed weak evidence needs full-text verification." for i in range(30)]
    (run_dir / "research_evidence_packet.md").write_text("\n".join(lines), encoding="utf-8")

    _run_loader(run_dir, output_dir)
    gaps = _read_state(output_dir)["unresolved_evidence_gaps"]

    assert len(gaps) == 20
    assert gaps[0].startswith("Evidence gap 0")


def test_does_not_import_runtime_modules() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    forbidden = [
        "tools.task_engine_runner",
        "tools.task_engine_executors",
        "tools.task_mode_runtime",
        "tools.task_engine_contracts",
        "research_pipeline_runner",
    ]
    assert not any(token in source for token in forbidden)


def test_cli_success_exit_code_zero(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-dir",
            str(run_dir),
            "--topic-id",
            "topic-cli",
            "--user-feedback",
            "continue this topic",
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert loader.PASS_STATUS in result.stdout


def test_cli_blocked_exit_code_nonzero(tmp_path: Path) -> None:
    run_dir = tmp_path / "missing"
    output_dir = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-dir",
            str(run_dir),
            "--topic-id",
            "topic-cli",
            "--user-feedback",
            "continue this topic",
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert loader.BLOCKED_RUN_DIR_MISSING in result.stdout


def test_generated_report_contains_pass_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    _run_loader(run_dir, output_dir)

    assert loader.PASS_STATUS in (output_dir / "artifact_loader_report.md").read_text(encoding="utf-8")
    assert json.loads((output_dir / "artifact_loader_report.json").read_text(encoding="utf-8"))["status"] == loader.PASS_STATUS


def test_blocked_report_contains_correct_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    run_dir.mkdir()
    (run_dir / "case_quality_review.md").write_text("review", encoding="utf-8")

    _run_loader(run_dir, output_dir)

    assert loader.BLOCKED_MISSING_FINAL_V1 in (output_dir / "artifact_loader_blocked_report.md").read_text(encoding="utf-8")
    assert json.loads((output_dir / "artifact_loader_blocked_report.json").read_text(encoding="utf-8"))["status"] == loader.BLOCKED_MISSING_FINAL_V1


def test_no_mode_routing_behavior_is_implemented(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    _run_loader(run_dir, output_dir)
    state = _read_state(output_dir)
    report = json.loads((output_dir / "artifact_loader_report.json").read_text(encoding="utf-8"))

    assert state["allowed_scope"]["may_select_refinement_mode"] is False
    assert state["selected_refinement_mode"] is None
    assert report["no_mode_selected"] is True


def test_no_revised_final_file_is_generated(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "out"
    _write_minimal_run(run_dir)

    _run_loader(run_dir, output_dir)

    forbidden_outputs = [
        "revised_final_v2.md",
        "refined_sections_v2.md",
        "refinement_stop_or_source_need.md",
        "topic_refinement_state.final.json",
    ]
    assert not any((output_dir / name).exists() for name in forbidden_outputs)
