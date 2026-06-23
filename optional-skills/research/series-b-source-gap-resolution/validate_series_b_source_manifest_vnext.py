#!/usr/bin/env python3
"""Standalone validator for Series B source manifest vNext drafts.

This script is intentionally standalone. It does not import production
builder code, does not run Series B, and does not update any baseline.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "series_b_source_manifest.vNext.draft"

TOP_LEVEL_FIELDS = {
    "schema_version",
    "case_id",
    "case_family",
    "required_professional_axes",
    "required_context_axes",
    "professional_sources",
    "context_sources",
    "prototype_evidence",
    "excluded_sources",
    "axis_satisfaction",
    "formal_pass_gate",
    "production_path_policy",
}

PROFESSIONAL_AXES = {
    "religion_book",
    "history_book",
    "materials_book",
    "archaeology_book",
    "nature_book",
    "geography_book",
    "art_architecture_book",
    "food_book",
    "architecture_book",
    "engineering_book",
    "conservation_book",
    "local_history_book",
}

CONTEXT_AXES = {
    "wiki_or_zim",
    "encyclopedia",
    "gazetteer",
    "local_guide_context",
    "source_backed_extracted_context_packet",
    "domain_glossary",
}

CASE_FAMILIES = {
    "material_object",
    "sacred_space",
    "archaeological_site",
    "natural_ecology",
    "cross_route",
    "adversarial_trap",
    "other",
}

PROVENANCE_READY = {
    "confirmed",
    "approved",
    "reviewed_case_scope_only",
}

EXCLUDED_REASONS = {
    "title_only",
    "query_echo",
    "generated_echo",
    "image_filename_only",
    "wrong_context",
    "listing_or_travel_planning",
    "modern_event_irrelevant",
    "food_only_wrong_case",
    "generic_orientation_or_platform",
    "weak_inventory_only",
}

PROHIBITED_PRO_SOURCE_MARKERS = {
    "title_only",
    "query_echo",
    "generated_echo",
    "image_filename_only",
    "wrong_context",
    "listing_or_travel_planning",
    "modern_event_irrelevant",
    "food_only_wrong_case",
    "generic_orientation_or_platform",
    "weak_inventory_only",
}

FORMAL_DECISIONS = {
    "FORMAL_PASS_READY",
    "SOURCE_AXIS_BLOCKED",
    "EXTERNAL_PROTOTYPE_ONLY",
    "LONG_DEFER_SOURCE_NEEDED",
    "BLOCKED_PROFESSIONAL_SOURCE_UNAVAILABLE",
    "FAIL_CLOSED",
}


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_non_empty_string(item) for item in value)


def _has_locator(source: dict[str, Any]) -> bool:
    return any(
        _is_non_empty_string(source.get(key))
        for key in ("source_path", "source_path_or_locator", "locator")
    )


def _has_identity(source: dict[str, Any]) -> bool:
    sha = source.get("source_sha256")
    if isinstance(sha, str) and re.fullmatch(r"[a-fA-F0-9]{64}", sha):
        return True
    identity = source.get("identity_hash")
    if isinstance(identity, dict):
        return _is_non_empty_string(identity.get("hash_type")) and _is_non_empty_string(
            identity.get("hash_value")
        )
    return False


def _prohibited_professional_marker(source: dict[str, Any]) -> str | None:
    fields = [
        str(source.get("source_id", "")),
        str(source.get("source_group", "")),
        str(source.get("title", "")),
        str(source.get("source_path", "")),
        str(source.get("source_path_or_locator", "")),
    ]
    text = " ".join(fields).lower()
    for marker in sorted(PROHIBITED_PRO_SOURCE_MARKERS):
        if marker in text:
            return marker
    title = str(source.get("title", "")).strip().lower()
    locator = str(source.get("source_path", source.get("source_path_or_locator", ""))).lower()
    if title.startswith(("query:", "generated:", "title-only:", "image:")):
        return "title_or_echo_like_title"
    if locator.startswith(("query:", "generated:", "title:", "image:")):
        return "title_or_echo_like_locator"
    return None


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a JSON object")
    return data


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    missing = sorted(TOP_LEVEL_FIELDS - set(manifest))
    extra = sorted(set(manifest) - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(f"missing top-level fields: {', '.join(missing)}")
    if extra:
        errors.append(f"unexpected top-level fields: {', '.join(extra)}")
    if missing:
        return errors

    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be series_b_source_manifest.vNext.draft")
    if not re.fullmatch(r"[a-z]+_[a-z]+_[0-9]{3}", str(manifest.get("case_id", ""))):
        errors.append("case_id must look like obj_art_003")
    if manifest.get("case_family") not in CASE_FAMILIES:
        errors.append("case_family is not recognized")

    required_prof = manifest.get("required_professional_axes")
    required_ctx = manifest.get("required_context_axes")
    if not isinstance(required_prof, list) or len(required_prof) != len(set(required_prof)):
        errors.append("required_professional_axes must be a unique array")
        required_prof = []
    if not isinstance(required_ctx, list) or len(required_ctx) != len(set(required_ctx)):
        errors.append("required_context_axes must be a unique array")
        required_ctx = []
    for axis in required_prof:
        if axis not in PROFESSIONAL_AXES:
            errors.append(f"required professional axis is invalid: {axis}")
    for axis in required_ctx:
        if axis not in CONTEXT_AXES:
            errors.append(f"required context axis is invalid: {axis}")

    professional_sources = manifest.get("professional_sources")
    context_sources = manifest.get("context_sources")
    prototypes = manifest.get("prototype_evidence")
    excluded_sources = manifest.get("excluded_sources")
    axis_satisfaction = manifest.get("axis_satisfaction")
    gate = manifest.get("formal_pass_gate")
    policy = manifest.get("production_path_policy")

    if not isinstance(professional_sources, list):
        errors.append("professional_sources must be an array")
        professional_sources = []
    if not isinstance(context_sources, list):
        errors.append("context_sources must be an array")
        context_sources = []
    if not isinstance(prototypes, list):
        errors.append("prototype_evidence must be an array")
        prototypes = []
    if not isinstance(excluded_sources, list):
        errors.append("excluded_sources must be an array")
        excluded_sources = []
    if not isinstance(axis_satisfaction, list):
        errors.append("axis_satisfaction must be an array")
        axis_satisfaction = []
    if not isinstance(gate, dict):
        errors.append("formal_pass_gate must be an object")
        gate = {}
    if not isinstance(policy, dict):
        errors.append("production_path_policy must be an object")
        policy = {}

    professional_by_id: dict[str, dict[str, Any]] = {}
    context_by_id: dict[str, dict[str, Any]] = {}
    excluded_ids: set[str] = set()
    prototype_artifacts: set[str] = set()

    for index, source in enumerate(professional_sources):
        if not isinstance(source, dict):
            errors.append(f"professional_sources[{index}] must be an object")
            continue
        source_id = source.get("source_id")
        if not _is_non_empty_string(source_id):
            errors.append(f"professional_sources[{index}].source_id is required")
            continue
        if source_id in professional_by_id or source_id in context_by_id:
            errors.append(f"duplicate source_id: {source_id}")
        professional_by_id[source_id] = source

        axis = source.get("axis")
        if axis not in PROFESSIONAL_AXES:
            errors.append(f"professional source {source_id} has invalid professional axis: {axis}")
        for field in (
            "source_group",
            "title",
            "license_or_provenance_status",
            "ingestion_run_id",
        ):
            if not _is_non_empty_string(source.get(field)):
                errors.append(f"professional source {source_id} missing {field}")
        if not _has_locator(source):
            errors.append(f"professional source {source_id} missing source locator")
        if not _has_identity(source):
            errors.append(f"professional source {source_id} missing source identity hash")
        if source.get("license_or_provenance_status") not in PROVENANCE_READY:
            errors.append(f"professional source {source_id} provenance is not confirmed")
        marker = _prohibited_professional_marker(source)
        if marker:
            errors.append(f"professional source {source_id} uses prohibited source marker: {marker}")
        if source.get("formal_ready") is not True:
            errors.append(f"professional source {source_id} must set formal_ready true to satisfy axes")
        if not _is_string_list(source.get("supports_terms")):
            errors.append(f"professional source {source_id} supports_terms must be an array of strings")
        if not _is_string_list(source.get("supports_sections")):
            errors.append(f"professional source {source_id} supports_sections must be an array of strings")
        if not isinstance(source.get("wrong_context_guard"), list):
            errors.append(f"professional source {source_id} wrong_context_guard must be an array")

        chunks = source.get("accepted_chunks")
        if not isinstance(chunks, list) or not chunks:
            errors.append(f"professional source {source_id} must have non-empty accepted_chunks")
        else:
            for chunk_index, chunk in enumerate(chunks):
                if not isinstance(chunk, dict):
                    errors.append(f"professional source {source_id} chunk {chunk_index} must be an object")
                    continue
                if not _is_non_empty_string(chunk.get("chunk_id")):
                    errors.append(f"professional source {source_id} chunk {chunk_index} missing chunk_id")
                if not _is_string_list(chunk.get("supports_terms")):
                    errors.append(
                        f"professional source {source_id} chunk {chunk_index} supports_terms must be strings"
                    )
                if not _is_string_list(chunk.get("supports_sections")):
                    errors.append(
                        f"professional source {source_id} chunk {chunk_index} supports_sections must be strings"
                    )
                if chunk.get("evidence_strength") not in {"direct", "supporting", "background"}:
                    errors.append(
                        f"professional source {source_id} chunk {chunk_index} evidence_strength is invalid"
                    )
                if not isinstance(chunk.get("wrong_context_guard"), list):
                    errors.append(
                        f"professional source {source_id} chunk {chunk_index} wrong_context_guard must be an array"
                    )

    for index, source in enumerate(context_sources):
        if not isinstance(source, dict):
            errors.append(f"context_sources[{index}] must be an object")
            continue
        source_id = source.get("source_id")
        if not _is_non_empty_string(source_id):
            errors.append(f"context_sources[{index}].source_id is required")
            continue
        if source_id in professional_by_id or source_id in context_by_id:
            errors.append(f"duplicate source_id: {source_id}")
        context_by_id[source_id] = source
        if source.get("axis") not in CONTEXT_AXES:
            errors.append(f"context source {source_id} has invalid context axis: {source.get('axis')}")
        if source.get("role") != "context_only":
            errors.append(f"context source {source_id} role must be context_only")
        if source.get("cannot_satisfy_professional_axis") is not True:
            errors.append(
                f"context source {source_id} must set cannot_satisfy_professional_axis true"
            )
        if not isinstance(source.get("supports_disambiguation"), bool):
            errors.append(f"context source {source_id} supports_disambiguation must be boolean")
        if not _is_string_list(source.get("supports_terms")):
            errors.append(f"context source {source_id} supports_terms must be an array of strings")
        if not _is_string_list(source.get("supports_sections")):
            errors.append(f"context source {source_id} supports_sections must be an array of strings")

    for index, evidence in enumerate(prototypes):
        if not isinstance(evidence, dict):
            errors.append(f"prototype_evidence[{index}] must be an object")
            continue
        artifact = evidence.get("artifact")
        if not _is_non_empty_string(artifact):
            errors.append(f"prototype_evidence[{index}].artifact is required")
        else:
            prototype_artifacts.add(artifact)
        if evidence.get("status") != "prototype_only":
            errors.append(f"prototype_evidence[{index}].status must be prototype_only")
        if evidence.get("cannot_be_counted_as_formal_pass") is not True:
            errors.append(
                f"prototype_evidence[{index}] must set cannot_be_counted_as_formal_pass true"
            )
        if evidence.get("cannot_update_official_baseline") is not True:
            errors.append(
                f"prototype_evidence[{index}] must set cannot_update_official_baseline true"
            )

    for index, excluded in enumerate(excluded_sources):
        if not isinstance(excluded, dict):
            errors.append(f"excluded_sources[{index}] must be an object")
            continue
        source_id = excluded.get("source_id")
        if not _is_non_empty_string(source_id):
            errors.append(f"excluded_sources[{index}].source_id is required")
        else:
            excluded_ids.add(source_id)
        if excluded.get("reason") not in EXCLUDED_REASONS:
            errors.append(f"excluded source {source_id} has invalid reason: {excluded.get('reason')}")
        axes = excluded.get("excluded_from_axes")
        if not isinstance(axes, list) or not axes:
            errors.append(f"excluded source {source_id} excluded_from_axes must be non-empty")
        if not _is_non_empty_string(excluded.get("notes")):
            errors.append(f"excluded source {source_id} notes are required")

    satisfaction_by_axis: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(axis_satisfaction):
        if not isinstance(item, dict):
            errors.append(f"axis_satisfaction[{index}] must be an object")
            continue
        axis = item.get("axis")
        if not _is_non_empty_string(axis):
            errors.append(f"axis_satisfaction[{index}].axis is required")
            continue
        if axis in satisfaction_by_axis:
            errors.append(f"duplicate axis_satisfaction entry: {axis}")
        satisfaction_by_axis[axis] = item

    required_axes = list(required_prof) + list(required_ctx)
    for axis in required_axes:
        if axis not in satisfaction_by_axis:
            errors.append(f"missing axis_satisfaction for required axis: {axis}")
    for axis in satisfaction_by_axis:
        if axis not in required_axes:
            errors.append(f"axis_satisfaction includes non-required axis: {axis}")

    computed_professional_axes_satisfied = True
    for axis in required_prof:
        item = satisfaction_by_axis.get(axis)
        if not item:
            computed_professional_axes_satisfied = False
            continue
        if item.get("axis_type") != "professional":
            errors.append(f"professional axis {axis} must have axis_type professional")
        if item.get("satisfied") is not True:
            computed_professional_axes_satisfied = False
            continue
        ids = item.get("satisfied_by_source_ids")
        if not isinstance(ids, list) or not ids:
            errors.append(f"professional axis {axis} is satisfied but has no source ids")
            computed_professional_axes_satisfied = False
            continue
        if item.get("satisfied_by_category") != "professional_sources":
            errors.append(f"professional axis {axis} must be satisfied by professional_sources")
            computed_professional_axes_satisfied = False
        for source_id in ids:
            if source_id in excluded_ids:
                errors.append(f"professional axis {axis} uses excluded source: {source_id}")
            if source_id in context_by_id:
                errors.append(f"context source {source_id} used as professional axis {axis}")
                computed_professional_axes_satisfied = False
            if source_id in prototype_artifacts:
                errors.append(f"prototype evidence {source_id} used as professional axis {axis}")
                computed_professional_axes_satisfied = False
            source = professional_by_id.get(source_id)
            if source is None:
                errors.append(f"professional axis {axis} references unknown professional source: {source_id}")
                computed_professional_axes_satisfied = False
                continue
            if source.get("axis") != axis:
                errors.append(
                    f"professional axis {axis} references source {source_id} with axis {source.get('axis')}"
                )
                computed_professional_axes_satisfied = False
            if source.get("formal_ready") is not True:
                errors.append(f"professional axis {axis} references non-formal-ready source {source_id}")
                computed_professional_axes_satisfied = False

    for axis in required_ctx:
        item = satisfaction_by_axis.get(axis)
        if not item:
            continue
        if item.get("axis_type") != "context":
            errors.append(f"context axis {axis} must have axis_type context")
        if item.get("satisfied") is not True:
            continue
        ids = item.get("satisfied_by_source_ids")
        if not isinstance(ids, list) or not ids:
            errors.append(f"context axis {axis} is satisfied but has no source ids")
            continue
        if item.get("satisfied_by_category") != "context_sources":
            errors.append(f"context axis {axis} must be satisfied by context_sources")
        for source_id in ids:
            if source_id in excluded_ids:
                errors.append(f"context axis {axis} uses excluded source: {source_id}")
            if source_id not in context_by_id:
                errors.append(f"context axis {axis} references unknown context source: {source_id}")

    gate_required = {
        "required_professional_axes_satisfied",
        "context_sources_used_as_professional_sources",
        "prototype_evidence_used_as_formal_pass",
        "decision",
        "blocked_reasons",
    }
    for field in sorted(gate_required):
        if field not in gate:
            errors.append(f"formal_pass_gate missing {field}")
    if gate.get("context_sources_used_as_professional_sources") is True:
        errors.append("formal_pass_gate says context sources were used as professional sources")
    if gate.get("prototype_evidence_used_as_formal_pass") is True:
        errors.append("formal_pass_gate says prototype evidence was used as formal pass")
    if gate.get("required_professional_axes_satisfied") != computed_professional_axes_satisfied:
        errors.append(
            "formal_pass_gate.required_professional_axes_satisfied does not match axis_satisfaction"
        )
    if gate.get("decision") not in FORMAL_DECISIONS:
        errors.append(f"formal_pass_gate decision is invalid: {gate.get('decision')}")
    if gate.get("decision") == "FORMAL_PASS_READY":
        if not computed_professional_axes_satisfied:
            errors.append("FORMAL_PASS_READY requires all professional axes satisfied")
        if gate.get("blocked_reasons") not in ([], None):
            errors.append("FORMAL_PASS_READY must not include blocked_reasons")
    elif isinstance(gate.get("blocked_reasons"), list) and not gate.get("blocked_reasons"):
        errors.append("blocked formal_pass_gate decisions must include blocked_reasons")

    policy_expectations = {
        "case_scoped_only": True,
        "production_default_loader_enabled": False,
        "full_series_b_enabled": False,
        "official_baseline_update_enabled": False,
    }
    for field, expected in policy_expectations.items():
        if policy.get(field) is not expected:
            errors.append(f"production_path_policy.{field} must be {expected}")

    return errors


def _self_test_manifest_path() -> Path:
    return Path(__file__).resolve().with_name("series_b_source_manifest_vnext_example.json")


def run_self_test() -> tuple[bool, dict[str, Any]]:
    valid = _load_json(_self_test_manifest_path())
    valid_errors = validate_manifest(valid)
    invalid_cases: dict[str, list[str]] = {}

    context_as_professional = copy.deepcopy(valid)
    context_as_professional["axis_satisfaction"][0]["satisfied_by_source_ids"] = [
        "zim:example:Concrete"
    ]
    context_as_professional["axis_satisfaction"][0]["satisfied_by_category"] = "context_sources"
    invalid_cases["context_source_as_professional_axis"] = validate_manifest(
        context_as_professional
    )

    prototype_as_formal = copy.deepcopy(valid)
    prototype_as_formal["formal_pass_gate"]["prototype_evidence_used_as_formal_pass"] = True
    invalid_cases["prototype_evidence_used_as_formal_pass"] = validate_manifest(
        prototype_as_formal
    )

    production_default_enabled = copy.deepcopy(valid)
    production_default_enabled["production_path_policy"][
        "production_default_loader_enabled"
    ] = True
    invalid_cases["production_default_loader_enabled"] = validate_manifest(
        production_default_enabled
    )

    missing_chunks = copy.deepcopy(valid)
    missing_chunks["professional_sources"][0].pop("accepted_chunks", None)
    invalid_cases["professional_source_missing_accepted_chunks"] = validate_manifest(
        missing_chunks
    )

    missing_identity = copy.deepcopy(valid)
    missing_identity["professional_sources"][0].pop("source_sha256", None)
    missing_identity["professional_sources"][0].pop("identity_hash", None)
    invalid_cases["professional_source_missing_identity"] = validate_manifest(missing_identity)

    ok = not valid_errors and all(errors for errors in invalid_cases.values())
    report = {
        "valid_example_errors": valid_errors,
        "invalid_cases_rejected": {
            name: bool(errors) for name, errors in invalid_cases.items()
        },
        "invalid_case_error_counts": {
            name: len(errors) for name, errors in invalid_cases.items()
        },
        "status": "PASS" if ok else "FAIL",
    }
    return ok, report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Series B source manifest vNext draft."
    )
    parser.add_argument("manifest", nargs="?", help="Path to a vNext manifest JSON file.")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in smoke checks using the bundled example.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        ok, report = run_self_test()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if ok else 1

    if not args.manifest:
        parser.error("manifest path is required unless --self-test is used")

    path = Path(args.manifest)
    try:
        manifest = _load_json(path)
    except Exception as exc:  # noqa: BLE001 - CLI should report JSON/path errors.
        print(
            json.dumps(
                {"status": "FAIL", "manifest": str(path), "errors": [str(exc)]},
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    errors = validate_manifest(manifest)
    print(
        json.dumps(
            {
                "status": "PASS" if not errors else "FAIL",
                "manifest": str(path),
                "errors": errors,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
