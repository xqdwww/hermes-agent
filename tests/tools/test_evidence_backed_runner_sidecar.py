from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from tools import evidence_backed_runner_sidecar as sidecar


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_disabled_sidecar_writes_nothing(tmp_path: Path) -> None:
    result = sidecar.maybe_emit_sidecar(tmp_path, enabled=False)

    assert result["status"] == "SKIPPED_EVIDENCE_BACKED_SIDECAR_DISABLED"
    assert not (tmp_path / sidecar.SIDECAR_DIRNAME).exists()


def test_status_only_empty_run_warns_and_requests_source_registry(tmp_path: Path) -> None:
    result = sidecar.maybe_emit_sidecar(tmp_path, enabled=True)
    output_dir = Path(result["output_dir"])
    validation = _load(output_dir / sidecar.VALIDATION_JSON)

    assert result["status"] == "PASS_EVIDENCE_BACKED_SIDECAR_EMITTED"
    assert validation["ok"] is True
    assert validation["next_action"] == "needs_source_registry"
    assert validation["source_registry_present"] is False
    assert "status_only sidecar found no source registry" in validation["warnings"][0]
    assert (output_dir / sidecar.MANIFEST_JSON).exists()
    assert (output_dir / sidecar.STATUS_MD).exists()


def test_artifact_detection_and_next_action_progression(tmp_path: Path) -> None:
    (tmp_path / "stageA").mkdir()
    (tmp_path / "stageA" / "source_registry.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "stageA" / "handoff_manifest.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "stageB").mkdir()
    (tmp_path / "stageB" / "evidence_packet_v2.json").write_text("{}\n", encoding="utf-8")

    manifest = sidecar.build_sidecar_manifest(tmp_path, stage="evidence_packet_gate", mode="RESEARCH", enabled=True)
    validation = sidecar.validate_sidecar_inputs(manifest)

    assert validation.ok is True
    assert validation.source_registry_present is True
    assert validation.fulltext_handoff_present is True
    assert validation.evidence_packet_present is True
    assert validation.final_traceability_present is False
    assert validation.next_action == "needs_final_traceability"
    assert manifest["source_registry_paths"] == ["stageA/source_registry.json"]
    assert manifest["fulltext_handoff_paths"] == ["stageA/handoff_manifest.json"]
    assert manifest["evidence_packet_paths"] == ["stageB/evidence_packet_v2.json"]


def test_all_artifacts_present_next_action_no_action(tmp_path: Path) -> None:
    for filename in (
        "source_registry.json",
        "handoff_manifest.json",
        "evidence_packet_v2.json",
        "final_answer_traceability.json",
        "report_only_advisory.json",
    ):
        (tmp_path / filename).write_text("{}\n", encoding="utf-8")

    validation = sidecar.validate_sidecar_inputs(
        sidecar.build_sidecar_manifest(tmp_path, stage="advisory_report_gate", mode="DECISION", enabled=True)
    )

    assert validation.ok is True
    assert validation.next_action == "no_action"
    assert validation.advisory_present is True


def test_stage_specific_missing_artifact_is_warning_not_fake_generation(tmp_path: Path) -> None:
    manifest = sidecar.build_sidecar_manifest(tmp_path, stage="fulltext_handoff_gate", mode="RESEARCH", enabled=True)
    validation = sidecar.validate_sidecar_inputs(manifest)

    assert validation.ok is True
    assert validation.fulltext_handoff_present is False
    assert any("fulltext_handoff_gate requested" in warning for warning in validation.warnings)
    assert not (tmp_path / "handoff_manifest.json").exists()


def test_invalid_stage_is_controlled_error_and_output_is_written(tmp_path: Path) -> None:
    result = sidecar.maybe_emit_sidecar(tmp_path, enabled=True, stage="bad_stage")
    validation = _load(Path(result["validation_path"]))

    assert result["status"] == "BLOCKED_EVIDENCE_BACKED_SIDECAR_VALIDATION"
    assert validation["ok"] is False
    assert validation["errors"] == ["unsupported sidecar_stage: bad_stage"]


def test_manifest_safety_flags_are_required(tmp_path: Path) -> None:
    manifest = sidecar.build_sidecar_manifest(tmp_path, stage="status_only", mode="RESEARCH", enabled=True)
    manifest["semantic_evaluator_used"] = True

    validation = sidecar.validate_sidecar_inputs(manifest)

    assert validation.ok is False
    assert any("semantic_evaluator_used" in error for error in validation.errors)


def test_render_status_contains_required_sections(tmp_path: Path) -> None:
    manifest = sidecar.build_sidecar_manifest(tmp_path, stage="status_only", mode="RESEARCH", enabled=True)
    validation = sidecar.validate_sidecar_inputs(manifest)
    markdown = sidecar.render_sidecar_status(manifest, validation)

    assert "# Evidence-Backed Runner Sidecar Status" in markdown
    assert "## Artifact Presence" in markdown
    assert "## Boundary" in markdown
    assert "source_acquisition_performed_by_sidecar" in markdown


def test_write_outputs_does_not_mutate_existing_artifacts(tmp_path: Path) -> None:
    artifact = tmp_path / "source_registry.json"
    artifact.write_text('{"existing": true}\n', encoding="utf-8")
    before = artifact.read_text(encoding="utf-8")

    sidecar.maybe_emit_sidecar(tmp_path, enabled=True, stage="source_registry_gate")

    assert artifact.read_text(encoding="utf-8") == before


def test_sidecar_source_has_no_network_llm_or_pipeline_imports() -> None:
    source = inspect.getsource(sidecar)
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")

    forbidden_imports = {
        "requests",
        "urllib",
        "httpx",
        "aiohttp",
        "openai",
        "anthropic",
        "subprocess",
        "tools.task_engine_runner",
        "tools.evidence_packet_v2",
    }
    assert imports.isdisjoint(forbidden_imports)
    assert not any("semantic" in name for name in imports)
