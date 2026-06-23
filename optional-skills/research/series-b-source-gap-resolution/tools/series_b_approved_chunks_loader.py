#!/usr/bin/env python3
"""Approved chunk loader for the rel_space_029 explicit harness."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_controlled_handoff_loader import manifest_accepted_chunk_ids
from series_b_controlled_result_schema import CASE_ID


class ApprovedChunksValidationError(ValueError):
    """Raised when approved chunk input cannot be used for rel_space_029."""


REQUIRED_CHUNK_FIELDS = {
    "chunk_id",
    "source_id",
    "source_title",
    "axis",
    "page_start",
    "page_end",
    "supports_terms",
    "supports_sections",
    "evidence_strength",
    "wrong_context_guard_passed",
    "reviewer_decision",
}


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ApprovedChunksValidationError("approved chunks root must be a JSON object")
    return data


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_non_empty_string(item) for item in value)


def _validate_chunk(chunk: dict[str, Any], index: int, expected_case_id: str) -> None:
    missing = sorted(REQUIRED_CHUNK_FIELDS - set(chunk))
    if missing:
        raise ApprovedChunksValidationError(f"approved_chunks[{index}] missing fields: {missing}")

    if chunk.get("case_id", expected_case_id) != expected_case_id:
        raise ApprovedChunksValidationError(f"approved_chunks[{index}] case_id mismatch")
    for field in ("chunk_id", "source_id", "source_title", "axis", "evidence_strength"):
        if not _is_non_empty_string(chunk.get(field)):
            raise ApprovedChunksValidationError(f"approved_chunks[{index}].{field} is required")

    if not isinstance(chunk.get("page_start"), int) or not isinstance(chunk.get("page_end"), int):
        raise ApprovedChunksValidationError(f"approved_chunks[{index}] page_start/page_end must be ints")
    if chunk["page_start"] <= 0 or chunk["page_end"] < chunk["page_start"]:
        raise ApprovedChunksValidationError(f"approved_chunks[{index}] page binding is invalid")

    terms = chunk.get("supports_terms")
    sections = chunk.get("supports_sections")
    if not _is_string_list(terms):
        raise ApprovedChunksValidationError(f"approved_chunks[{index}].supports_terms must be strings")
    if not _is_string_list(sections):
        raise ApprovedChunksValidationError(f"approved_chunks[{index}].supports_sections must be strings")
    if not terms and not sections:
        raise ApprovedChunksValidationError(
            f"approved_chunks[{index}] must support at least one term or section"
        )

    if chunk.get("reviewer_decision") != "FORMAL_READY_APPROVED":
        raise ApprovedChunksValidationError(
            f"approved_chunks[{index}] reviewer_decision must be FORMAL_READY_APPROVED"
        )
    if chunk.get("source_backed_text_exists") is not True:
        raise ApprovedChunksValidationError(f"approved_chunks[{index}] lacks source-backed text")
    if chunk.get("page_bound") is not True:
        raise ApprovedChunksValidationError(f"approved_chunks[{index}] lacks page binding")
    if chunk.get("wrong_context_guard_passed") is not True:
        raise ApprovedChunksValidationError(f"approved_chunks[{index}] failed wrong-context guard")


def load_approved_chunks(path: str | Path, *, expected_case_id: str = CASE_ID) -> list[dict[str, Any]]:
    payload = _load_json_object(Path(path).expanduser())
    if payload.get("case_id") != expected_case_id:
        raise ApprovedChunksValidationError(f"approved chunks case_id must be {expected_case_id}")
    if payload.get("case_scope_only") is not True:
        raise ApprovedChunksValidationError("approved chunks must be case_scope_only")
    if payload.get("production_default_enabled") is not False:
        raise ApprovedChunksValidationError("approved chunks must not enable production default")
    chunks = payload.get("approved_chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ApprovedChunksValidationError("approved_chunks must be a non-empty array")

    seen: set[str] = set()
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise ApprovedChunksValidationError(f"approved_chunks[{index}] must be an object")
        _validate_chunk(chunk, index, expected_case_id)
        chunk_id = chunk["chunk_id"]
        if chunk_id in seen:
            raise ApprovedChunksValidationError(f"duplicate approved chunk_id: {chunk_id}")
        seen.add(chunk_id)
    if payload.get("approved_chunks_count") not in (None, len(chunks)):
        raise ApprovedChunksValidationError("approved_chunks_count does not match approved_chunks")
    return chunks


def validate_chunks_against_manifest(
    chunks: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    manifest_chunk_ids = manifest_accepted_chunk_ids(manifest)
    chunk_ids = {chunk["chunk_id"] for chunk in chunks}
    missing = sorted(chunk_ids - manifest_chunk_ids)
    if missing:
        raise ApprovedChunksValidationError(
            "approved chunks are not present in the handoff manifest: " + ", ".join(missing)
        )
    source_ids = {
        source.get("source_id")
        for source in manifest.get("professional_sources", [])
        if isinstance(source, dict)
    }
    unknown_sources = sorted({chunk["source_id"] for chunk in chunks} - source_ids)
    if unknown_sources:
        raise ApprovedChunksValidationError(
            "approved chunks reference unknown professional sources: "
            + ", ".join(unknown_sources)
        )
