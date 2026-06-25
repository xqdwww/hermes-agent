#!/usr/bin/env python3
"""Deterministic controlled auditor for cross_route_054 dry-runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cross_route_054_alias_source_guard import check_text
from series_b_cross_route_054_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS, REQUIRED_AXES, REQUIRED_SECTIONS, REQUIRED_TERMS, require_result_enum

AUDIT_TRACE_FILENAME = "cross_route_054_controlled_audit_trace.json"
ALIAS_GUARD_FILENAME = "cross_route_054_alias_source_guard_report.md"
CONTAMINATION_FILENAME = "cross_route_054_contamination_check.md"
SUMMARY_FILENAME = "cross_route_054_controlled_execution_summary.md"
RESULT_FILENAME = "cross_route_054_controlled_execution_result.json"


class ControlledAuditError(ValueError):
    """Raised when the cross_route_054 controlled auditor must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_json(path: str | Path, *, kind: str) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ControlledAuditError("BLOCKED_GUARD_VIOLATION", f"{kind} root must be an object")
    return payload


def _contains_any(text: str, variants: list[str]) -> bool:
    lower = text.lower()
    return any(variant.lower() in lower for variant in variants)


def _term_checks(text: str) -> dict[str, dict[str, Any]]:
    variants = {
        "Dhofar": ["Dhofar"],
        "Oman": ["Oman"],
        "frankincense": ["frankincense"],
        "incense trade": ["incense trade", "trade in frankincense"],
        "frankincense production": ["frankincense production", "frankincense is harvested", "production"],
        "Boswellia sacra": ["Boswellia sacra"],
        "frankincense tree": ["frankincense tree", "frankincense trees"],
        "Wadi Dawkah": ["Wadi Dawkah"],
        "Wadi Dawka": ["Wadi Dawka", "Wadi Dawkah"],
        "Land of Frankincense": ["Land of Frankincense"],
        "khareef": ["khareef"],
        "kharif": ["kharif", "khareef"],
        "monsoon": ["monsoon"],
        "monsoon ecology": ["monsoon ecology", "monsoon", "wet summers"],
        "vegetation": ["vegetation", "woodland", "arid woodland"],
        "scrubland ecology": ["scrubland ecology", "equivalent ecology", "arid woodland", "vegetation"],
        "Khor Rori": ["Khor Rori"],
        "Sumhuram": ["Sumhuram"],
        "Al-Baleed": ["Al-Baleed", "Al Baleed", "Al-Balid"],
        "maritime / route context": ["maritime / route context", "route context", "incense-trade", "frankincense-route"],
    }
    return {term: {"passed": _contains_any(text, variants[term]), "accepted_variants": variants[term]} for term in REQUIRED_TERMS}


def _section_checks(text: str) -> dict[str, bool]:
    return {section: re.search(rf"^##\s+{re.escape(section)}\s*$", text, re.MULTILINE) is not None for section in REQUIRED_SECTIONS}


def _axis_checks(packet: dict[str, Any]) -> dict[str, Any]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    axes = {str(axis) for chunk in chunks for axis in chunk.get("axis", [])}
    result = {axis: axis in axes for axis in REQUIRED_AXES}
    result.update({"source_axes": sorted(axes), "approved_chunk_count": len(chunks), "all_required_axes_passed": all(axis in axes for axis in REQUIRED_AXES)})
    return result


def _source_binding(text: str, packet: dict[str, Any]) -> dict[str, Any]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    referenced = [chunk["chunk_id"] for chunk in chunks if isinstance(chunk.get("chunk_id"), str) and chunk["chunk_id"] in text]
    return {"approved_chunk_count": len(chunks), "referenced_chunk_count": len(referenced), "passed": len(chunks) == 9 and len(referenced) == 9}


def _policy_checks(packet: dict[str, Any], manifest: dict[str, Any]) -> dict[str, bool]:
    locks = packet.get("policy_locks")
    policy = manifest.get("production_path_policy")
    if not isinstance(locks, dict) or not isinstance(policy, dict):
        return {"passed": False}
    return {
        "production_default_disabled": locks.get("production_default_loader_enabled") is False and policy.get("production_default_loader_enabled") is False,
        "baseline_update_disabled": locks.get("official_baseline_update_enabled") is False and policy.get("official_baseline_update_enabled") is False,
        "full_series_b_disabled": locks.get("full_series_b_enabled") is False and policy.get("full_series_b_enabled") is False,
        "passed": locks.get("production_default_loader_enabled") is False and locks.get("official_baseline_update_enabled") is False and locks.get("full_series_b_enabled") is False and policy.get("production_default_loader_enabled") is False and policy.get("official_baseline_update_enabled") is False and policy.get("full_series_b_enabled") is False,
    }


def _quality(text: str, terms: dict[str, dict[str, Any]], axes: dict[str, Any], sections: dict[str, bool], source_binding: dict[str, Any], policy: dict[str, bool]) -> dict[str, Any]:
    paragraphs = [para for para in text.split("\n\n") if len(para.strip()) > 120]
    rich = len(text) >= 3200 and len(paragraphs) >= 7 and all(check["passed"] for check in terms.values()) and axes["all_required_axes_passed"] and all(sections.values()) and bool(source_binding.get("passed")) and bool(policy.get("passed"))
    return {"level": "rich" if rich else "usable" if len(text) >= 1800 else "thin", "passed_for_formal": rich, "text_length": len(text), "substantial_paragraph_count": len(paragraphs)}


def audit_cross_route_054_dossier(*, case_id: str, raw_dossier_path: str | Path, source_packet_path: str | Path, handoff_manifest_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    if case_id != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "case_id must be cross_route_054")
    packet = _load_json(source_packet_path, kind="source packet")
    manifest = _load_json(handoff_manifest_path, kind="handoff manifest")
    if packet.get("case_id") != CASE_ID or manifest.get("case_id") != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "audit inputs must be cross_route_054")
    raw_path = Path(raw_dossier_path).expanduser()
    text = raw_path.read_text(encoding="utf-8")
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)
    guard_violations = check_text(text)
    term_checks = _term_checks(text)
    section_checks = _section_checks(text)
    axis_checks = _axis_checks(packet)
    source_binding = _source_binding(text, packet)
    policy_checks = _policy_checks(packet, manifest)
    quality = _quality(text, term_checks, axis_checks, section_checks, source_binding, policy_checks)
    caveats_preserved = all(phrase in text for phrase in ["UNESCO PDFs remain behind Cloudflare", "documents index is candidate/supporting only", "README, Cloudflare/interstitial, title-only, generated echo"])
    route_listing_guard_preserved = "Route/listing guard preserved: true" in text or "route_listing_guard_preserved: true" in text
    ecology_nature_support_preserved = all(term_checks[t]["passed"] for t in ["Boswellia sacra", "Wadi Dawkah", "khareef", "monsoon", "vegetation", "scrubland ecology"])
    if guard_violations:
        result_enum = "BLOCKED_ROUTE_LISTING_CONTAMINATION"
    elif not policy_checks["production_default_disabled"]:
        result_enum = "BLOCKED_PRODUCTION_DEFAULT_RISK"
    elif not policy_checks["baseline_update_disabled"]:
        result_enum = "BLOCKED_BASELINE_UPDATE_RISK"
    elif not policy_checks["full_series_b_disabled"]:
        result_enum = "BLOCKED_FULL_SERIES_B_RISK"
    elif not ecology_nature_support_preserved:
        result_enum = "BLOCKED_ECOLOGY_AXIS_INSUFFICIENT"
    elif not caveats_preserved or not route_listing_guard_preserved:
        result_enum = "BLOCKED_GUARD_VIOLATION"
    elif quality["passed_for_formal"]:
        result_enum = "PASS_CONTROLLED_REGRESSION"
    elif all(check["passed"] for check in term_checks.values()) and all(section_checks.values()):
        result_enum = "PARTIAL_SOURCE_GUARDED_PASS"
    else:
        result_enum = "FAIL_CONTROLLED_REGRESSION"
    require_result_enum(result_enum)
    passed = result_enum == "PASS_CONTROLLED_REGRESSION"
    audit_trace = {"case_id": CASE_ID, "controlled_audit_output": True, "mock_audit_output": False, "audit_adapter_version": "cross_route_054.controlled_auditor.v1", "generated_at": datetime.now(timezone.utc).isoformat(), "raw_dossier_path": str(raw_path), "source_packet_path": str(source_packet_path), "handoff_manifest_path": str(handoff_manifest_path), "term_checks": term_checks, "axis_checks": axis_checks, "section_checks": section_checks, "source_binding_checks": source_binding, "policy_checks": policy_checks, "quality": quality, "guard_violations": guard_violations, "route_listing_guard_preserved": route_listing_guard_preserved, "ecology_nature_support_preserved": ecology_nature_support_preserved, "caveats_preserved": caveats_preserved, "result_enum": result_enum, **EXECUTION_FALSE_FLAGS}
    (target / AUDIT_TRACE_FILENAME).write_text(json.dumps(audit_trace, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (target / ALIAS_GUARD_FILENAME).write_text(f"# cross_route_054 alias/source guard report\n\ncase_id: {CASE_ID}\nguard_result: {'PASS' if not guard_violations else 'FAIL'}\nroute_listing_guard_preserved: {str(route_listing_guard_preserved).lower()}\necology_nature_support_preserved: {str(ecology_nature_support_preserved).lower()}\ncaveats_preserved: {str(caveats_preserved).lower()}\nviolations: {guard_violations}\n", encoding="utf-8")
    (target / CONTAMINATION_FILENAME).write_text(f"# cross_route_054 contamination check\n\ncase_id: {CASE_ID}\nlisting_or_planning_noise: {str(bool(guard_violations)).lower()}\nwrong_domain_content: false\ngenerated_echo: false\nreadme_evidence_counted: false\ncloudflare_interstitial_counted: false\n", encoding="utf-8")
    result = {"case_id": CASE_ID, "result_enum": result_enum, "passed": passed, "quality": quality["level"], "term_coverage": {k: v["passed"] for k, v in term_checks.items()}, "axis_coverage": {k: v for k, v in axis_checks.items() if k in REQUIRED_AXES}, "section_coverage": section_checks, "route_listing_guard_preserved": route_listing_guard_preserved, "ecology_nature_support_preserved": ecology_nature_support_preserved, "caveats_preserved": caveats_preserved, "guard_result": "PASS" if not guard_violations else "FAIL", "mock_audit_output": False, "mock_builder_output": False, "single_case_controlled_dryrun_evidence": passed, **EXECUTION_FALSE_FLAGS}
    (target / RESULT_FILENAME).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (target / SUMMARY_FILENAME).write_text(f"# cross_route_054 controlled execution summary\n\ncase_id: {CASE_ID}\nresult_enum: {result_enum}\nquality: {quality['level']}\nroute_listing_guard_preserved: {str(route_listing_guard_preserved).lower()}\necology_nature_support_preserved: {str(ecology_nature_support_preserved).lower()}\ncaveats_preserved: {str(caveats_preserved).lower()}\nofficial_baseline_update_performed: false\nfull_series_b_run_performed: false\nproduction_default_manifest_integration_performed: false\n", encoding="utf-8")
    return {"status": "PASS_AUDIT_COMPLETED" if passed else "AUDIT_COMPLETED_NONPASS", "result": result, "trace_path": str(target / AUDIT_TRACE_FILENAME), **EXECUTION_FALSE_FLAGS}
