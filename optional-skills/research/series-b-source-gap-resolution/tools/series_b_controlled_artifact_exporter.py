#!/usr/bin/env python3
"""Artifact contract validator and dummy exporter for rel_space_029.

The exporter only writes explicitly marked dummy artifacts. It is not a
controlled regression runner and never writes PASS_CONTROLLED_REGRESSION.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_controlled_result_schema import (
    CASE_ID,
    EXECUTION_FALSE_FLAGS,
    REQUIRED_ARTIFACTS,
)


class ArtifactContractError(ValueError):
    """Raised when artifact output policy or contract checks fail."""


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_output_dir_policy(output_dir: str | Path, *, repo_root: str | Path | None = None) -> Path:
    if output_dir in ("", None):
        raise ArtifactContractError("output dir is required")
    resolved = Path(output_dir).expanduser().resolve(strict=False)
    if repo_root and _is_relative_to(resolved, Path(repo_root).expanduser().resolve(strict=False)):
        raise ArtifactContractError("output dir must not be inside the travel repo")

    forbidden_prefixes = [
        Path("/Users/xqdwww/Workspace/AI_Core/hermes-agent"),
        Path("/Users/xqdwww/Workspace/AI_Core/hermes-agent-research-decision"),
        Path("/Users/xqdwww/Workspace/AI_Data/travel_series_b_professional_sources"),
    ]
    for prefix in forbidden_prefixes:
        if _is_relative_to(resolved, prefix):
            raise ArtifactContractError(f"output dir points at forbidden production/worktree path: {prefix}")

    lowered = str(resolved).lower()
    if any(marker in lowered for marker in ("production_default", "official_baseline", "full_series_b")):
        raise ArtifactContractError("output dir looks like a production/baseline/full-Series-B path")
    return resolved


def validate_required_artifact_names(names: list[str] | None = None) -> None:
    names = names or REQUIRED_ARTIFACTS
    missing = sorted(set(REQUIRED_ARTIFACTS) - set(names))
    extra = sorted(set(names) - set(REQUIRED_ARTIFACTS))
    if missing or extra:
        raise ArtifactContractError(f"artifact names mismatch; missing={missing}, extra={extra}")


def write_dummy_artifacts(
    output_dir: str | Path,
    manifest: dict[str, Any],
    chunks: list[dict[str, Any]],
    *,
    repo_root: str | Path | None = None,
) -> list[str]:
    target = validate_output_dir_policy(output_dir, repo_root=repo_root)
    target.mkdir(parents=True, exist_ok=True)

    source_packet = {
        "dummy_test_artifact_only": True,
        "case_id": CASE_ID,
        "source_ids": sorted({chunk["source_id"] for chunk in chunks}),
        "approved_chunk_ids": [chunk["chunk_id"] for chunk in chunks],
        "axes": sorted({chunk["axis"] for chunk in chunks}),
        "supports_terms": sorted({term for chunk in chunks for term in chunk.get("supports_terms", [])}),
        "supports_sections": sorted(
            {section for chunk in chunks for section in chunk.get("supports_sections", [])}
        ),
    }
    result = {
        "dummy_test_artifact_only": True,
        "case_id": CASE_ID,
        "result_enum": "BLOCKED_REPO_PATCH_REQUIRED",
        "passed": False,
        "partial": False,
        "blocked": True,
        "quality": None,
        "artifacts_written": REQUIRED_ARTIFACTS,
        **EXECUTION_FALSE_FLAGS,
    }

    payloads: dict[str, str] = {
        "rel_space_029_controlled_manifest_used.json": json.dumps(
            {"dummy_test_artifact_only": True, "case_id": CASE_ID, "manifest": manifest},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "rel_space_029_controlled_raw_dossier.md": (
            "# rel_space_029 controlled raw dossier\n\n"
            "dummy_test_artifact_only: true\n\nNo controlled dossier was generated.\n"
        ),
        "rel_space_029_controlled_audit_trace.json": json.dumps(
            {
                "dummy_test_artifact_only": True,
                "case_id": CASE_ID,
                "result_enum": "BLOCKED_REPO_PATCH_REQUIRED",
                "stop_reasons": ["dummy artifact skeleton only"],
                **EXECUTION_FALSE_FLAGS,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "rel_space_029_controlled_source_packet.json": json.dumps(
            source_packet,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "rel_space_029_alias_source_guard_report.md": (
            "# rel_space_029 alias/source guard report\n\n"
            "dummy_test_artifact_only: true\n\nNo controlled regression was executed.\n"
        ),
        "rel_space_029_contamination_check.md": (
            "# rel_space_029 contamination check\n\n"
            "dummy_test_artifact_only: true\n\nNo controlled regression was executed.\n"
        ),
        "rel_space_029_controlled_execution_summary.md": (
            "# rel_space_029 controlled execution summary\n\n"
            "dummy_test_artifact_only: true\n\n"
            "result_enum: BLOCKED_REPO_PATCH_REQUIRED\n"
        ),
        "rel_space_029_controlled_execution_result.json": json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    validate_required_artifact_names(sorted(payloads))
    for filename, content in payloads.items():
        (target / filename).write_text(content, encoding="utf-8")
    return [str(target / filename) for filename in REQUIRED_ARTIFACTS]
