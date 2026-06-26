#!/usr/bin/env python3
"""Validation helpers for the Series B canonical official candidate input layer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


DATASET_SCHEMA_VERSION = "series_b_official_60case_dataset.v1"
DATASET_CLASSIFICATION = "CANONICAL_OFFICIAL_DATASET_V1"
SOURCE_STATE_SCHEMA_VERSION = "series_b_source_state_manifest.v1"
FROZEN_LEDGER_SCHEMA_VERSION = "series_b_frozen_baseline_ledger.v1"


class OfficialInputLayerError(ValueError):
    """Raised when the canonical input layer is incomplete or unsafe."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OfficialInputLayerError(f"JSON root must be object: {target}")
    return payload


def validate_official_dataset(path: str | Path) -> dict[str, Any]:
    payload = load_json(path)
    cases = payload.get("cases")
    if payload.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise OfficialInputLayerError("unsupported official dataset schema")
    if payload.get("classification") != DATASET_CLASSIFICATION:
        raise OfficialInputLayerError("dataset is not canonical official dataset v1")
    if payload.get("controlled_evidence_rollup_used_as_dataset") is True:
        raise OfficialInputLayerError("controlled evidence rollup must not be used as official dataset")
    if not isinstance(cases, list) or len(cases) != 60:
        raise OfficialInputLayerError("official dataset must contain exactly 60 cases")
    ids: list[str] = []
    for index, row in enumerate(cases, 1):
        if not isinstance(row, dict):
            raise OfficialInputLayerError(f"dataset case {index} is not an object")
        case_id = str(row.get("case_id") or "").strip()
        if not case_id:
            raise OfficialInputLayerError(f"dataset case {index} missing case_id")
        if not str(row.get("original_prompt") or "").strip():
            raise OfficialInputLayerError(f"dataset case {case_id} missing original_prompt")
        trace = row.get("source_trace")
        if not isinstance(trace, list) or not trace:
            raise OfficialInputLayerError(f"dataset case {case_id} missing source_trace")
        ids.append(case_id)
    if len(set(ids)) != 60:
        raise OfficialInputLayerError("official dataset case_id values must be unique")
    return {
        "status": "PASS",
        "case_count": len(cases),
        "case_ids": ids,
        "dataset_sha256": sha256_file(path),
        "classification": payload.get("classification"),
    }


def validate_frozen_ledger(path: str | Path, dataset_case_ids: list[str]) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("schema_version") != FROZEN_LEDGER_SCHEMA_VERSION:
        raise OfficialInputLayerError("unsupported frozen ledger schema")
    if payload.get("official_baseline_score") != "31/60":
        raise OfficialInputLayerError("frozen ledger must preserve 31/60 baseline score")
    failed = payload.get("failed_cases")
    passed = payload.get("passed_cases")
    if not isinstance(failed, list) or not isinstance(passed, list):
        raise OfficialInputLayerError("frozen ledger must include passed_cases and failed_cases")
    if len(passed) != 31 or len(failed) != 29:
        raise OfficialInputLayerError("frozen ledger pass/fail counts must be 31/29")
    dataset_set = set(dataset_case_ids)
    if set(passed) | set(failed) != dataset_set:
        raise OfficialInputLayerError("frozen ledger case set must equal official dataset case set")
    if set(passed) & set(failed):
        raise OfficialInputLayerError("frozen ledger passed/failed cases overlap")
    return {
        "status": "PASS",
        "official_baseline_score": payload.get("official_baseline_score"),
        "passed_cases": len(passed),
        "failed_cases": len(failed),
        "ledger_sha256": sha256_file(path),
    }


def validate_source_state_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve(strict=False)
    payload = load_json(path)
    if payload.get("schema_version") != SOURCE_STATE_SCHEMA_VERSION:
        raise OfficialInputLayerError("unsupported source-state manifest schema")
    if payload.get("official_write_enabled") is not False:
        raise OfficialInputLayerError("source-state manifest must keep official_write_enabled false")
    if payload.get("production_default_enabled") is not False:
        raise OfficialInputLayerError("source-state manifest must keep production_default_enabled false")
    entries = payload.get("inputs")
    if not isinstance(entries, list) or not entries:
        raise OfficialInputLayerError("source-state manifest inputs missing")
    for entry in entries:
        if not isinstance(entry, dict):
            raise OfficialInputLayerError("source-state entry must be object")
        if entry.get("write_target") is True:
            raise OfficialInputLayerError(f"source-state entry is marked as write target: {entry.get('input_role')}")
        target = entry.get("path")
        if entry.get("exists") is True and target:
            target_path = Path(target).expanduser().resolve(strict=False)
            if target_path == manifest_path:
                continue
            actual = sha256_file(target)
            if entry.get("hash") and entry.get("hash") != actual:
                raise OfficialInputLayerError(f"source-state hash mismatch: {entry.get('input_role')}")
    return {"status": "PASS", "entry_count": len(entries), "source_state_sha256": sha256_file(path)}
