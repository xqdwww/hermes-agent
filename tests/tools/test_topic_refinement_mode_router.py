from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools import topic_refinement_mode_router as router


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools/topic_refinement_mode_router.py"


def _write_initial_state(
    tmp_path: Path,
    *,
    quality: list[str] | None = None,
    evidence: list[str] | None = None,
    calibration: list[str] | None = None,
    environment: list[dict[str, str]] | None = None,
    feedback: str = "continue this topic",
    authorization: dict | None = None,
    next_action: str = "needs_mode_router",
    selected_failure_type=None,
    selected_refinement_mode=None,
    state_type: str = "topic_refinement_state_initial",
    flags: dict | None = None,
) -> Path:
    final_path = tmp_path / "final_controller_report.md"
    final_path.write_text("final_v1\n", encoding="utf-8")
    state = {
        "schema_version": "1.0",
        "state_type": state_type,
        "topic_id": "topic-1",
        "original_question": "question",
        "current_final_version": "final_v1",
        "current_final_version_path": str(final_path),
        "artifact_paths": {"final_v1": str(final_path)},
        "artifact_hashes": {},
        "user_feedback": feedback,
        "detected_quality_signals": quality or [],
        "detected_evidence_boundary_signals": evidence or [],
        "detected_calibration_boundary_signals": calibration or [],
        "detected_environment_signals": environment or [],
        "authorization": authorization or {"allow_source_acquisition": False, "allow_full_text_verification": False},
        "preserved_caveats": [],
        "unresolved_evidence_gaps": [],
        "selected_failure_type": selected_failure_type,
        "selected_refinement_mode": selected_refinement_mode,
        "selection_tie_breaker_reason": None,
        "confidence_boundary": "no confidence upgrade without evidence",
        "final_versions": [{"version": "final_v1", "path": str(final_path), "created_by": "existing_artifact"}],
        "refinement_history": [],
        "next_action": next_action,
        "no_runtime_integration": True,
        "no_llm_called": True,
        "no_pipeline_rerun": True,
    }
    if flags:
        state.update(flags)
    state_path = tmp_path / "topic_refinement_state.initial.json"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state_path


def _route(tmp_path: Path, state_path: Path) -> dict:
    output_dir = tmp_path / "router_out"
    result = router.route_file(state_path=state_path, output_dir=output_dir)
    assert result.exit_code == 0
    return json.loads((output_dir / router.ROUTED_STATE_FILENAME).read_text(encoding="utf-8"))


def _blocked_status(output_dir: Path) -> str:
    return json.loads((output_dir / "mode_router_blocked_report.json").read_text(encoding="utf-8"))["status"]


def test_success_with_minimal_valid_initial_state(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path)
    output_dir = tmp_path / "out"

    result = router.route_file(state_path=state_path, output_dir=output_dir)

    assert result.exit_code == 0
    assert result.status == router.PASS_STATUS
    assert (output_dir / router.ROUTED_STATE_FILENAME).exists()


def test_invalid_json_blocks(tmp_path: Path) -> None:
    state_path = tmp_path / "bad.json"
    state_path.write_text("{bad", encoding="utf-8")
    output_dir = tmp_path / "out"

    result = router.route_file(state_path=state_path, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == router.BLOCKED_INVALID_JSON


def test_missing_state_file_blocks(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    result = router.route_file(state_path=tmp_path / "missing.json", output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == router.BLOCKED_STATE_FILE_MISSING


def test_wrong_state_type_blocks(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, state_type="topic_refinement_state_final")
    output_dir = tmp_path / "out"

    result = router.route_file(state_path=state_path, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == router.BLOCKED_INVALID_STATE_TYPE


def test_wrong_next_action_blocks(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, next_action="ready_for_refinement")
    output_dir = tmp_path / "out"

    result = router.route_file(state_path=state_path, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == router.BLOCKED_INVALID_NEXT_ACTION


def test_already_routed_state_blocks(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, selected_failure_type="low_domain_specificity")
    output_dir = tmp_path / "out"

    result = router.route_file(state_path=state_path, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == router.BLOCKED_ALREADY_ROUTED


def test_missing_final_v1_path_blocks(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_final_version_path"] = str(tmp_path / "missing_final.md")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    output_dir = tmp_path / "out"

    result = router.route_file(state_path=state_path, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == router.BLOCKED_FINAL_V1_MISSING


def test_runtime_flags_mismatch_blocks(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, flags={"no_llm_called": False})
    output_dir = tmp_path / "out"

    result = router.route_file(state_path=state_path, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == router.BLOCKED_RUNTIME_FLAG_MISMATCH


def test_output_already_exists_blocks(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / router.ROUTED_STATE_FILENAME).write_text("{}\n", encoding="utf-8")

    result = router.route_file(state_path=state_path, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == router.BLOCKED_OUTPUT_ALREADY_EXISTS


def test_environment_signal_routes_to_environment_triage(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, environment=[{"signal": "DDGS missing"}])
    routed = _route(tmp_path, state_path)

    assert routed["selected_failure_type"] == "executor_or_environment_blocker"
    assert routed["selected_refinement_mode"] == "environment_triage"
    assert routed["next_action"] == "environment_triage_required"


def test_evidence_gap_routes_to_targeted_evidence_acquisition(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, evidence=["full-text verification", "snippet"], feedback="请写得更确定一点")
    routed = _route(tmp_path, state_path)

    assert routed["selected_failure_type"] == "evidence_gap_needs_full_text_verification"
    assert routed["selected_refinement_mode"] == "targeted_evidence_acquisition"


def test_targeted_evidence_acquisition_without_authorization_stops_source_need(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, evidence=["unsupported", "weak evidence"], feedback="stronger conclusion please")
    routed = _route(tmp_path, state_path)

    assert routed["stop_reason"] == "source_or_full_text_verification_required"
    assert routed["next_action"] == "source_need_or_full_text_verification"


def test_targeted_evidence_acquisition_with_authorization_still_performs_no_acquisition(tmp_path: Path) -> None:
    state_path = _write_initial_state(
        tmp_path,
        evidence=["full-text verification"],
        feedback="more certain",
        authorization={"allow_source_acquisition": True, "allow_full_text_verification": False},
    )
    routed = _route(tmp_path, state_path)

    assert routed["next_action"] == "ready_for_authorized_source_acquisition_dry_run"
    assert routed["no_evidence_acquisition_performed"] is True


def test_calibration_overclaim_routes_to_final_absorption(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, calibration=["overclaim", "confidence down"])
    routed = _route(tmp_path, state_path)

    assert routed["selected_failure_type"] == "calibration_absorption_gap"
    assert routed["selected_refinement_mode"] == "final_absorption_pass"


def test_convergence_not_absorbed_routes_to_final_absorption(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, quality=["convergence not absorbed"])
    routed = _route(tmp_path, state_path)

    assert routed["selected_failure_type"] == "convergence_to_final_specificity_loss"
    assert routed["selected_refinement_mode"] == "final_absorption_pass"


def test_template_signal_routes_to_final_template_fallback(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, quality=["template"])
    routed = _route(tmp_path, state_path)

    assert routed["selected_failure_type"] == "final_template_fallback"


def test_low_specificity_routes_to_low_domain_specificity(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, quality=["low specificity"])
    routed = _route(tmp_path, state_path)

    assert routed["selected_failure_type"] == "low_domain_specificity"


def test_user_deeper_feedback_routes_to_user_feedback_refinement(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, feedback="继续这个话题，把第 2 部分做实")
    routed = _route(tmp_path, state_path)

    assert routed["selected_failure_type"] == "user_feedback_requests_deeper_specificity"
    assert routed["selected_refinement_mode"] == "user_feedback_refinement"


def test_no_signals_routes_to_stop_no_actionable_refinement(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, feedback="thanks")
    routed = _route(tmp_path, state_path)

    assert routed["selected_failure_type"] is None
    assert routed["selected_refinement_mode"] is None
    assert routed["next_action"] == "stop_no_actionable_refinement"


def test_tie_breaker_environment_beats_evidence(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, environment=[{"signal": "OMLX"}], evidence=["unsupported"], feedback="more certain")
    routed = _route(tmp_path, state_path)

    assert routed["routing_priority"] == 0
    assert routed["selected_refinement_mode"] == "environment_triage"


def test_tie_breaker_evidence_beats_calibration(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, evidence=["unsupported"], calibration=["overclaim"], feedback="more certain")
    routed = _route(tmp_path, state_path)

    assert routed["routing_priority"] == 1
    assert routed["selected_refinement_mode"] == "targeted_evidence_acquisition"


def test_tie_breaker_calibration_beats_generic_final(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, quality=["final too generic"], calibration=["caveat"])
    routed = _route(tmp_path, state_path)

    assert routed["routing_priority"] == 2
    assert routed["selected_refinement_mode"] == "final_absorption_pass"


def test_confidence_upgrade_request_cannot_create_confidence_upgrade_mode(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, evidence=["weak evidence"], feedback="please make confidence upgraded")
    routed = _route(tmp_path, state_path)

    assert routed["selected_refinement_mode"] != "confidence_upgrade"
    assert "confidence_upgrade_not_allowed_without_new_evidence" in routed["routing_warnings"]


def test_output_state_is_append_only_and_preserves_initial_final_versions(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, quality=["low specificity"])
    initial = json.loads(state_path.read_text(encoding="utf-8"))
    routed = _route(tmp_path, state_path)

    assert routed["state_type"] == "topic_refinement_state_routed"
    assert routed["final_versions"] == initial["final_versions"]


def test_no_llm_pipeline_or_final_rewrite_flags_true(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, quality=["low specificity"])
    routed = _route(tmp_path, state_path)

    assert routed["no_llm_called"] is True
    assert routed["no_pipeline_rerun"] is True
    assert routed["no_final_rewritten"] is True


def test_no_revised_final_file_is_generated(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, quality=["low specificity"])
    output_dir = tmp_path / "out"
    router.route_file(state_path=state_path, output_dir=output_dir)

    assert not (output_dir / "revised_final_v2.md").exists()
    assert not (output_dir / "refined_sections_v2.md").exists()


def test_no_evidence_acquisition_output_is_generated(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, evidence=["unsupported"], feedback="more certain")
    output_dir = tmp_path / "out"
    router.route_file(state_path=state_path, output_dir=output_dir)

    assert not (output_dir / "evidence_acquisition_result.md").exists()


def test_selected_refinement_mode_is_allowed(tmp_path: Path) -> None:
    state_path = _write_initial_state(tmp_path, quality=["low specificity"])
    routed = _route(tmp_path, state_path)

    assert routed["selected_refinement_mode"] in router.ALLOWED_MODES


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
    state_path = _write_initial_state(tmp_path, quality=["low specificity"])
    output_dir = tmp_path / "cli_out"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--state", str(state_path), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert router.PASS_STATUS in result.stdout


def test_cli_blocked_exit_code_nonzero(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli_out"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--state", str(tmp_path / "missing.json"), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert router.BLOCKED_STATE_FILE_MISSING in result.stdout
