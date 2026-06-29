from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

from tools import topic_refinement_manual_task as manual
from tools import topic_refinement_registry_adapter as adapter
from tools import topic_refinement_output_validator as validator


REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_SOURCE = REPO_ROOT / "tools/topic_refinement_registry_adapter.py"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_dir(
    tmp_path: Path,
    *,
    quality: str = "quality review\n",
    calibration: str = "",
    evidence: str = "",
    failure: str = "",
    include_final: bool = True,
    include_quality: bool = True,
) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    if include_final:
        (run_dir / "final_controller_report.md").write_text("final_v1 original\nCaveat: bounded evidence.\n", encoding="utf-8")
    if include_quality:
        (run_dir / "case_quality_review.md").write_text(quality, encoding="utf-8")
    if calibration:
        (run_dir / "calibration_report.md").write_text(calibration, encoding="utf-8")
    if evidence:
        (run_dir / "research_evidence_packet.md").write_text(evidence, encoding="utf-8")
    if failure:
        (run_dir / "failure_report.md").write_text(failure, encoding="utf-8")
    (run_dir / "original_user_question.txt").write_text("original question\n", encoding="utf-8")
    return run_dir


def _rewrite_run(tmp_path: Path) -> Path:
    return _run_dir(tmp_path, calibration="overclaim caveat plausible calibration boundary\n")


def _source_need_run(tmp_path: Path) -> Path:
    return _run_dir(
        tmp_path,
        quality="verification_required true snippet_limited true\n",
        evidence="snippet full-text verification unsupported evidence gap\n",
    )


def _environment_run(tmp_path: Path) -> Path:
    return _run_dir(tmp_path, failure="DDGS missing environment blocker\n")


def _payload(run_dir: Path, output_dir: Path, feedback: str, **extra) -> dict:
    payload = {
        "task_mode": adapter.TASK_MODE,
        "run_dir": str(run_dir),
        "topic_id": "topic-1",
        "user_feedback": feedback,
        "confirm_same_topic": True,
        "output_dir": str(output_dir),
    }
    payload.update(extra)
    return payload


def _candidate(tmp_path: Path, files: dict[str, str]) -> Path:
    cand = tmp_path / "candidate"
    cand.mkdir()
    for name, text in files.items():
        path = cand / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return cand


def test_boundary_evidence_gap_routes_to_source_need_without_confidence_upgrade(tmp_path: Path) -> None:
    run_dir = _source_need_run(tmp_path)
    result = adapter.run_topic_refinement_registry_adapter(
        _payload(run_dir, tmp_path / "out", "继续这个话题。请写得更确定一点。")
    )
    manual_result = result["manual_task_result"]
    validator_report = json.loads(
        (tmp_path / "out" / "manual_task_output" / "validator_output" / "refinement_output_validation_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert result["status"] == adapter.PASS_STATUS
    assert manual_result["status"] == manual.PASS_MANUAL_TASK_STOPPED_SOURCE_NEED
    assert manual_result["selected_refinement_mode"] == "targeted_evidence_acquisition"
    assert validator_report["confidence_boundary_check"]["pass"] is True
    assert not (tmp_path / "out" / "manual_task_output" / "candidate_output" / "revised_final_v2.md").exists()


def test_boundary_environment_blocker_stops_before_rewrite(tmp_path: Path) -> None:
    run_dir = _environment_run(tmp_path)
    result = adapter.run_topic_refinement_registry_adapter(_payload(run_dir, tmp_path / "out", "继续这个话题，把 blocker 说明清楚"))

    assert result["status"] == adapter.BLOCKED_MANUAL_TASK_FAILED
    assert result["manual_task_result"]["status"] == manual.BLOCKED_LOADER_FAILED
    assert result["manual_task_result"]["loader_result"] == "BLOCKED_ENVIRONMENT_OR_RUNTIME_ARTIFACT"
    assert not (tmp_path / "out" / "manual_task_output" / "candidate_output" / "revised_final_v2.md").exists()


def test_boundary_confidence_upgrade_request_without_evidence_stops(tmp_path: Path) -> None:
    run_dir = _source_need_run(tmp_path)
    result = adapter.run_topic_refinement_registry_adapter(
        _payload(run_dir, tmp_path / "out", "same topic refine, stronger conclusion please")
    )

    assert result["manual_task_result"]["status"] == manual.PASS_MANUAL_TASK_STOPPED_SOURCE_NEED
    assert result["manual_task_result"]["next_action"] == "source_need_or_full_text_verification"


def test_boundary_missing_final_v1_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, include_final=False)
    result = adapter.run_topic_refinement_registry_adapter(_payload(run_dir, tmp_path / "out", "same topic refine"))

    assert result["status"] == adapter.BLOCKED_MANUAL_TASK_FAILED
    assert result["manual_task_result"]["status"] == manual.BLOCKED_LOADER_FAILED
    assert result["manual_task_result"]["loader_result"] == "BLOCKED_MISSING_FINAL_V1"


def test_boundary_missing_quality_review_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, include_quality=False)
    result = adapter.run_topic_refinement_registry_adapter(_payload(run_dir, tmp_path / "out", "same topic refine"))

    assert result["status"] == adapter.BLOCKED_MANUAL_TASK_FAILED
    assert result["manual_task_result"]["status"] == manual.BLOCKED_LOADER_FAILED
    assert result["manual_task_result"]["loader_result"] == "BLOCKED_MISSING_QUALITY_REVIEW"


def test_boundary_output_collision_blocks(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "existing.txt").write_text("existing\n", encoding="utf-8")

    result = adapter.run_topic_refinement_registry_adapter(_payload(run_dir, out, "same topic refine"))

    assert result["status"] == adapter.BLOCKED_OUTPUT_ALREADY_EXISTS
    assert not (out / "manual_task_output").exists()


def test_boundary_bad_candidate_false_full_text_claim_blocks(tmp_path: Path) -> None:
    run_dir = _source_need_run(tmp_path)
    cand = _candidate(tmp_path, {"refinement_stop_or_source_need.md": "source_need: required\nfull_text_verified: true\n"})
    result = adapter.run_topic_refinement_registry_adapter(
        _payload(run_dir, tmp_path / "out", "验证这个 candidate refinement", candidate_refinement_dir=str(cand))
    )

    assert result["status"] == adapter.BLOCKED_MANUAL_TASK_FAILED
    assert result["manual_task_result"]["validator_result"] == validator.BLOCKED_FALSE_FULL_TEXT_VERIFICATION_CLAIM


def test_boundary_bad_candidate_full_rerun_claim_blocks(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    cand = _candidate(
        tmp_path,
        {
            "revised_final_v2.md": "Caveat preserved. full rerun completed.\n",
            "changed_unchanged_traceability.md": "changed_sections: final\nwhat_was_not_changed: final_v1\n",
        },
    )
    result = adapter.run_topic_refinement_registry_adapter(
        _payload(run_dir, tmp_path / "out", "验证这个 candidate refinement", candidate_refinement_dir=str(cand))
    )

    assert result["status"] == adapter.BLOCKED_MANUAL_TASK_FAILED
    assert result["manual_task_result"]["validator_result"] == validator.BLOCKED_FULL_RERUN_CLAIM


def test_boundary_candidate_validator_failure_prevents_usable_revised_final(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    cand = _candidate(
        tmp_path,
        {
            "revised_final_v2.md": "Caveat preserved. confidence upgraded.\n",
            "changed_unchanged_traceability.md": "changed_sections: final\nwhat_was_not_changed: final_v1\n",
        },
    )
    result = adapter.run_topic_refinement_registry_adapter(
        _payload(run_dir, tmp_path / "out", "验证这个 candidate refinement", candidate_refinement_dir=str(cand))
    )

    assert result["status"] == adapter.BLOCKED_MANUAL_TASK_FAILED
    assert result["manual_task_result"].get("usable_candidate") is not True
    assert result["manual_task_result"]["validator_result"] == validator.BLOCKED_CONFIDENCE_UPGRADE_WITHOUT_NEW_EVIDENCE


def test_boundary_final_v1_hash_unchanged(tmp_path: Path) -> None:
    run_dir = _source_need_run(tmp_path)
    final_v1 = run_dir / "final_controller_report.md"
    before = _sha(final_v1)

    result = adapter.run_topic_refinement_registry_adapter(_payload(run_dir, tmp_path / "out", "继续这个话题。请写得更确定一点。"))

    assert _sha(final_v1) == before
    assert result["final_v1_append_only_preserved"] is True
    assert result["manual_task_result"]["final_v1_overwrite_check"]["pass"] is True


def test_process_loader_router_validator_reports_are_preserved(tmp_path: Path) -> None:
    run_dir = _source_need_run(tmp_path)
    result = adapter.run_topic_refinement_registry_adapter(_payload(run_dir, tmp_path / "out", "继续这个话题。请写得更确定一点。"))
    manual_out = tmp_path / "out" / "manual_task_output"

    assert result["manual_task_report_preserved"] is True
    assert (manual_out / "loader_output" / "artifact_loader_report.json").exists()
    assert (manual_out / "router_output" / "mode_router_report.json").exists()
    assert (manual_out / "validator_output" / "refinement_output_validation_report.json").exists()
    assert (manual_out / "manual_task_report.json").exists()


def test_process_flags_prevent_llm_pipeline_hooks_and_auto_execution(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    result = adapter.run_topic_refinement_registry_adapter(_payload(run_dir, tmp_path / "out", "same topic refine"))

    assert result["no_llm_called"] is True
    assert result["no_pipeline_rerun"] is True
    assert result["no_final_controller_hook"] is True
    assert result["no_auto_invocation"] is True
    assert result["no_automatic_post_final_execution"] is True
    assert result["manual_task_result"]["append_only_state"] is True


def test_process_candidate_validator_called_when_candidate_exists(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    cand = _candidate(
        tmp_path,
        {
            "revised_final_v2.md": "new_evidence: none\nCaveat preserved; conditional.\n",
            "changed_unchanged_traceability.md": "changed_sections: final\nwhat_was_not_changed: final_v1\n",
        },
    )
    result = adapter.run_topic_refinement_registry_adapter(
        _payload(run_dir, tmp_path / "out", "验证这个 candidate refinement", candidate_refinement_dir=str(cand))
    )

    assert result["manual_task_result"]["validator_result"] == validator.PASS_STATUS
    assert (tmp_path / "out" / "manual_task_output" / "validator_output" / "refinement_output_validation_report.json").exists()


def test_runtime_safety_default_route_is_not_changed() -> None:
    assert not hasattr(adapter, "DEFAULT_TASK_MODE")
    assert not hasattr(adapter, "AUTO_TRIGGER")
    assert adapter.TASK_MODE == "TOPIC_REFINEMENT"


def test_runtime_safety_registry_description_is_narrow() -> None:
    description = adapter.REGISTRY_DESCRIPTION

    assert "explicitly asks" in description
    assert "existing Research/Decision topic" in description
    assert "Do not use for new topics" in description
    assert "automatic post-final retries" in description
    assert "any task" not in description.lower()
    assert "general refinement" not in description.lower()


def test_runtime_safety_import_has_no_circular_runtime_side_effects() -> None:
    module = importlib.reload(adapter)

    assert module.TASK_MODE == "TOPIC_REFINEMENT"
    assert module.REGISTRY_DESCRIPTION == adapter.REGISTRY_DESCRIPTION


def test_runtime_safety_no_forbidden_runtime_imports_or_registration() -> None:
    source = ADAPTER_SOURCE.read_text(encoding="utf-8")
    forbidden = [
        "tools.task_engine_runner",
        "tools.task_engine_executors",
        "tools.task_mode_runtime",
        "research_pipeline_runner",
        "register(",
        "register_task_mode",
        "from tools import final_controller",
    ]

    assert not any(token in source for token in forbidden)
