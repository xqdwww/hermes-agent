"""Deterministic optional evidence-backed runner sidecar helper.

This helper is intentionally narrow: it detects already-produced evidence-backed
artifacts and writes status/validation sidecars. It does not search, retrieve,
call models, generate evidence packets, rewrite finals, or execute advisory
workflows.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "evidence_backed_runner_sidecar.v1"
SIDECAR_DIRNAME = "evidence_backed_sidecar"
MANIFEST_JSON = "evidence_backed_sidecar_manifest.json"
VALIDATION_JSON = "evidence_backed_sidecar_validation.json"
STATUS_MD = "evidence_backed_sidecar_status.md"

SUPPORTED_STAGES = (
    "status_only",
    "source_registry_gate",
    "fulltext_handoff_gate",
    "evidence_packet_gate",
    "final_traceability_gate",
    "advisory_report_gate",
)

NEXT_ACTIONS = (
    "no_action",
    "needs_source_registry",
    "needs_handoff",
    "needs_evidence_packet",
    "needs_final_traceability",
    "needs_review",
)

SOURCE_REGISTRY_FILENAMES = {"source_registry.json"}
FULLTEXT_HANDOFF_FILENAMES = {"handoff_manifest.json", "fulltext_handoff_manifest.json"}
EVIDENCE_PACKET_FILENAMES = {"evidence_packet_v2.json"}
FINAL_TRACEABILITY_FILENAMES = {"final_answer_traceability.json", "final_traceability.json"}
ADVISORY_FILENAMES = {
    "report_only_advisory.json",
    "advisory_report.json",
    "post_final_topic_refinement_advisory.json",
    "post_final_advisory_report.json",
}


@dataclass(frozen=True)
class SidecarValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]
    enabled: bool
    stage: str
    sidecar_mode: str
    source_registry_present: bool
    fulltext_handoff_present: bool
    evidence_packet_present: bool
    final_traceability_present: bool
    advisory_present: bool
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_sidecar_manifest(run_dir: str | Path, *, stage: str, mode: str, enabled: bool) -> dict[str, Any]:
    """Build a status-only sidecar manifest from existing files under run_dir."""
    root = Path(run_dir).expanduser().resolve(strict=False)
    source_registry_paths = _find_artifact_paths(root, SOURCE_REGISTRY_FILENAMES)
    fulltext_handoff_paths = _find_artifact_paths(root, FULLTEXT_HANDOFF_FILENAMES)
    evidence_packet_paths = _find_artifact_paths(root, EVIDENCE_PACKET_FILENAMES)
    final_traceability_paths = _find_artifact_paths(root, FINAL_TRACEABILITY_FILENAMES)
    advisory_paths = _find_artifact_paths(root, ADVISORY_FILENAMES)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "enabled": bool(enabled),
        "sidecar_stage": stage or "status_only",
        "sidecar_mode": mode or "runner_sidecar_status",
        "task_mode": mode or "unknown",
        "branch_head": "not_collected_by_sidecar",
        "source_registry_paths": source_registry_paths,
        "fulltext_handoff_paths": fulltext_handoff_paths,
        "evidence_packet_paths": evidence_packet_paths,
        "final_traceability_paths": final_traceability_paths,
        "advisory_paths": advisory_paths,
        "validation_summary": {},
        "next_action": "no_action",
        "no_auto_execution": True,
        "semantic_evaluator_used": False,
        "source_acquisition_performed_by_sidecar": False,
        "final_modified_by_sidecar": False,
        "topic_refinement_auto_executed": False,
    }


def validate_sidecar_inputs(manifest: dict[str, Any]) -> SidecarValidationResult:
    """Validate sidecar manifest boundaries and artifact presence.

    Missing evidence-backed artifacts are warnings because this slice is a
    status reporter, not an executor. Invalid contract or unsafe safety flags are
    errors.
    """
    errors: list[str] = []
    warnings: list[str] = []
    stage = str(manifest.get("sidecar_stage") or "status_only")
    enabled = bool(manifest.get("enabled", False))
    sidecar_mode = str(manifest.get("sidecar_mode") or "runner_sidecar_status")

    if stage not in SUPPORTED_STAGES:
        errors.append(f"unsupported sidecar_stage: {stage}")

    for key, expected in (
        ("no_auto_execution", True),
        ("semantic_evaluator_used", False),
        ("source_acquisition_performed_by_sidecar", False),
        ("final_modified_by_sidecar", False),
        ("topic_refinement_auto_executed", False),
    ):
        if manifest.get(key) is not expected:
            errors.append(f"unsafe sidecar boundary flag {key}={manifest.get(key)!r}; expected {expected!r}")

    source_registry_present = bool(manifest.get("source_registry_paths") or [])
    fulltext_handoff_present = bool(manifest.get("fulltext_handoff_paths") or [])
    evidence_packet_present = bool(manifest.get("evidence_packet_paths") or [])
    final_traceability_present = bool(manifest.get("final_traceability_paths") or [])
    advisory_present = bool(manifest.get("advisory_paths") or [])

    if enabled:
        if stage == "source_registry_gate" and not source_registry_present:
            warnings.append("source_registry_gate requested but no source_registry.json was found")
        if stage == "fulltext_handoff_gate" and not fulltext_handoff_present:
            warnings.append("fulltext_handoff_gate requested but no handoff manifest was found")
        if stage == "evidence_packet_gate" and not evidence_packet_present:
            warnings.append("evidence_packet_gate requested but no evidence_packet_v2.json was found")
        if stage == "final_traceability_gate" and not final_traceability_present:
            warnings.append("final_traceability_gate requested but no final traceability artifact was found")
        if stage == "advisory_report_gate" and not advisory_present:
            warnings.append("advisory_report_gate requested but no report-only advisory artifact was found")
        if stage == "status_only" and not source_registry_present:
            warnings.append("status_only sidecar found no source registry; evidence-backed flow has not started")

    next_action = _next_action(
        source_registry_present=source_registry_present,
        fulltext_handoff_present=fulltext_handoff_present,
        evidence_packet_present=evidence_packet_present,
        final_traceability_present=final_traceability_present,
        advisory_present=advisory_present,
    )
    if not enabled:
        next_action = "no_action"

    return SidecarValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        enabled=enabled,
        stage=stage,
        sidecar_mode=sidecar_mode,
        source_registry_present=source_registry_present,
        fulltext_handoff_present=fulltext_handoff_present,
        evidence_packet_present=evidence_packet_present,
        final_traceability_present=final_traceability_present,
        advisory_present=advisory_present,
        next_action=next_action,
    )


def render_sidecar_status(manifest: dict[str, Any], validation: SidecarValidationResult | None = None) -> str:
    if validation is None:
        validation = validate_sidecar_inputs(manifest)
    lines = [
        "# Evidence-Backed Runner Sidecar Status",
        "",
        "## Summary",
        "",
        f"- enabled: {validation.enabled}",
        f"- sidecar_stage: {validation.stage}",
        f"- sidecar_mode: {validation.sidecar_mode}",
        f"- next_action: {validation.next_action}",
        f"- ok: {validation.ok}",
        "",
        "## Validation Result",
        "",
        f"- errors_count: {len(validation.errors)}",
        f"- warnings_count: {len(validation.warnings)}",
        "",
        "## Artifact Presence",
        "",
        f"- source_registry_present: {validation.source_registry_present}",
        f"- fulltext_handoff_present: {validation.fulltext_handoff_present}",
        f"- evidence_packet_present: {validation.evidence_packet_present}",
        f"- final_traceability_present: {validation.final_traceability_present}",
        f"- advisory_present: {validation.advisory_present}",
        "",
        "## Errors",
        "",
    ]
    lines.extend(_render_list(validation.errors))
    lines.extend([
        "",
        "## Warnings",
        "",
    ])
    lines.extend(_render_list(validation.warnings))
    lines.extend([
        "",
        "## Boundary",
        "",
        f"- no_auto_execution: {manifest.get('no_auto_execution')}",
        f"- semantic_evaluator_used: {manifest.get('semantic_evaluator_used')}",
        f"- source_acquisition_performed_by_sidecar: {manifest.get('source_acquisition_performed_by_sidecar')}",
        f"- final_modified_by_sidecar: {manifest.get('final_modified_by_sidecar')}",
        f"- topic_refinement_auto_executed: {manifest.get('topic_refinement_auto_executed')}",
    ])
    return "\n".join(lines) + "\n"


def write_sidecar_outputs(
    run_dir: str | Path,
    manifest: dict[str, Any],
    validation: SidecarValidationResult | None = None,
) -> dict[str, Any]:
    root = Path(run_dir).expanduser().resolve(strict=False)
    if validation is None:
        validation = validate_sidecar_inputs(manifest)
    output_dir = root / SIDECAR_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_to_write = dict(manifest)
    manifest_to_write["validation_summary"] = validation.to_dict()
    manifest_to_write["next_action"] = validation.next_action

    manifest_path = output_dir / MANIFEST_JSON
    validation_path = output_dir / VALIDATION_JSON
    status_path = output_dir / STATUS_MD
    manifest_path.write_text(json.dumps(manifest_to_write, indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")
    validation_path.write_text(json.dumps(validation.to_dict(), indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")
    status_path.write_text(render_sidecar_status(manifest_to_write, validation), encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "manifest_path": str(manifest_path),
        "validation_path": str(validation_path),
        "status_path": str(status_path),
        "validation": validation.to_dict(),
    }


def maybe_emit_sidecar(
    run_dir: str | Path,
    *,
    enabled: bool,
    stage: str = "status_only",
    mode: str = "runner_sidecar_status",
) -> dict[str, Any]:
    root = Path(run_dir).expanduser().resolve(strict=False)
    if not enabled:
        return {
            "status": "SKIPPED_EVIDENCE_BACKED_SIDECAR_DISABLED",
            "enabled": False,
            "sidecar_emitted": False,
            "run_dir": str(root),
            "no_auto_execution": True,
        }
    manifest = build_sidecar_manifest(root, stage=stage, mode=mode, enabled=True)
    validation = validate_sidecar_inputs(manifest)
    outputs = write_sidecar_outputs(root, manifest, validation)
    return {
        "status": "PASS_EVIDENCE_BACKED_SIDECAR_EMITTED" if validation.ok else "BLOCKED_EVIDENCE_BACKED_SIDECAR_VALIDATION",
        "enabled": True,
        "sidecar_emitted": True,
        "run_dir": str(root),
        **outputs,
        "no_auto_execution": True,
    }


def _find_artifact_paths(root: Path, filenames: set[str]) -> list[str]:
    if not root.exists():
        return []
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if SIDECAR_DIRNAME in path.relative_to(root).parts:
            continue
        if path.name in filenames:
            found.append(path.relative_to(root).as_posix())
    return sorted(found)


def _next_action(
    *,
    source_registry_present: bool,
    fulltext_handoff_present: bool,
    evidence_packet_present: bool,
    final_traceability_present: bool,
    advisory_present: bool,
) -> str:
    if not source_registry_present:
        return "needs_source_registry"
    if not fulltext_handoff_present:
        return "needs_handoff"
    if not evidence_packet_present:
        return "needs_evidence_packet"
    if not final_traceability_present:
        return "needs_final_traceability"
    if not advisory_present:
        return "needs_review"
    return "no_action"


def _render_list(values: list[str]) -> list[str]:
    if not values:
        return ["- none"]
    return [f"- {value}" for value in values]


__all__ = [
    "ADVISORY_FILENAMES",
    "EVIDENCE_PACKET_FILENAMES",
    "FINAL_TRACEABILITY_FILENAMES",
    "FULLTEXT_HANDOFF_FILENAMES",
    "MANIFEST_JSON",
    "NEXT_ACTIONS",
    "SCHEMA_VERSION",
    "SIDECAR_DIRNAME",
    "SOURCE_REGISTRY_FILENAMES",
    "STATUS_MD",
    "SUPPORTED_STAGES",
    "SidecarValidationResult",
    "VALIDATION_JSON",
    "build_sidecar_manifest",
    "maybe_emit_sidecar",
    "render_sidecar_status",
    "validate_sidecar_inputs",
    "write_sidecar_outputs",
]
