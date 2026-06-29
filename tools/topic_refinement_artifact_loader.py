#!/usr/bin/env python3
"""Dry-run artifact loader for Research/Decision topic refinement.

This utility is intentionally standalone. It reads existing artifacts and writes
an initial topic refinement state; it does not select a refinement mode, call an
LLM, rerun a pipeline, acquire sources, or rewrite any final answer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "1.0"
LOADER_VERSION = "slice1.0"
STATE_FILENAME = "topic_refinement_state.initial.json"
PASS_STATUS = "PASS_ARTIFACT_LOADER_DRY_RUN"

BLOCKED_RUN_DIR_MISSING = "BLOCKED_RUN_DIR_MISSING"
BLOCKED_OUTPUT_ALREADY_EXISTS = "BLOCKED_OUTPUT_ALREADY_EXISTS"
BLOCKED_MISSING_FINAL_V1 = "BLOCKED_MISSING_FINAL_V1"
BLOCKED_MISSING_QUALITY_REVIEW = "BLOCKED_MISSING_QUALITY_REVIEW"
BLOCKED_ENVIRONMENT_OR_RUNTIME_ARTIFACT = "BLOCKED_ENVIRONMENT_OR_RUNTIME_ARTIFACT"
BLOCKED_INVALID_USER_FEEDBACK = "BLOCKED_INVALID_USER_FEEDBACK"
BLOCKED_INVALID_TOPIC_ID = "BLOCKED_INVALID_TOPIC_ID"
BLOCKED_INVALID_OUTPUT_DIR = "BLOCKED_INVALID_OUTPUT_DIR"
BLOCKED_ARTIFACT_PATH_ESCAPE = "BLOCKED_ARTIFACT_PATH_ESCAPE"

ARTIFACT_SPECS = {
    "final_v1": ["final_controller_report.md", "final.md", "final_answer.md"],
    "quality_review": ["case_quality_review.md", "final_quality_gate.md", "quality_review.md"],
    "convergence_report": ["convergence_report.md"],
    "calibration_report": ["calibration_report.md"],
    "research_evidence_packet": ["research_evidence_packet.md"],
    "original_user_question": ["original_user_question.txt"],
    "runner_result": ["runner_result.json"],
    "failure_report": ["failure_report.md"],
}

REQUIRED_ARTIFACTS = ("final_v1", "quality_review")

ENVIRONMENT_PATTERNS = {
    "executor_resource_exhausted": "executor_resource_exhausted",
    "ddgs missing": "DDGS missing",
    "modulenotfounderror": "ModuleNotFoundError",
    "blocked_executor_unavailable": "blocked_executor_unavailable",
    "environment blocker": "environment blocker",
    "evidence_judge resource": "evidence_judge resource",
    "omlx": "OMLX",
    "service unhealthy": "service unhealthy",
}

QUALITY_PATTERNS = {
    "final too generic": "final too generic",
    "too generic": "final too generic",
    "low specificity": "low specificity",
    "low_specificity": "low specificity",
    "template": "template",
    "templated": "template",
    "missing section": "missing section",
    "priority weak": "priority weak",
    "weak priority": "priority weak",
    "convergence not absorbed": "convergence not absorbed",
    "convergence_to_final_specificity_loss": "convergence not absorbed",
    "calibration not absorbed": "calibration not absorbed",
    "calibration_absorption_gap": "calibration not absorbed",
}

EVIDENCE_PATTERNS = {
    "snippet": "snippet",
    "full-text verification": "full-text verification",
    "full text verification": "full-text verification",
    "thin evidence": "thin evidence",
    "weak evidence": "weak evidence",
    "speculative": "speculative",
    "unsupported": "unsupported",
    "evidence gap": "evidence gap",
    "evidence_gap": "evidence gap",
}

CALIBRATION_PATTERNS = {
    "overclaim": "overclaim",
    "over-claim": "overclaim",
    "confidence down": "confidence down",
    "downshift": "confidence down",
    "downgrade": "confidence down",
    "caveat": "caveat",
    "plausible": "plausible",
    "speculative": "speculative",
    "contradicted": "contradicted",
    "unsupported": "unsupported",
}

CAVEAT_LINE_PATTERNS = (
    "caveat",
    "limitation",
    "limited",
    "speculative",
    "plausible",
    "unsupported",
    "full-text verification",
    "full text verification",
    "snippet",
)

EVIDENCE_GAP_LINE_PATTERNS = (
    "evidence gap",
    "evidence_gap",
    "full-text verification",
    "full text verification",
    "snippet-backed",
    "snippet backed",
    "weak evidence",
    "thin evidence",
)

MAX_EXTRACTED_LINES = 20
MAX_LINE_CHARS = 320


@dataclass(frozen=True)
class LoadResult:
    status: str
    exit_code: int
    output_dir: Path | None = None
    state_path: Path | None = None
    report_json_path: Path | None = None
    report_md_path: Path | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _is_output_dir_allowed(output_dir: Path) -> bool:
    resolved = output_dir.resolve(strict=False)
    repo_outputs = (_repo_root() / "outputs").resolve(strict=False)
    if _is_relative_to(resolved, repo_outputs):
        return True
    temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
    if _is_relative_to(resolved, temp_root):
        return True
    # macOS often reports tmp_path under /private/var while tempfile may report /var.
    private_tmp = Path("/private/tmp").resolve(strict=False)
    private_var = Path("/private/var").resolve(strict=False)
    return _is_relative_to(resolved, private_tmp) or _is_relative_to(resolved, private_var)


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _read_text(path: Path, max_chars: int = 200_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_rel_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _find_first(run_dir: Path, names: Iterable[str]) -> Path | None:
    for name in names:
        matches = sorted(
            run_dir.rglob(name),
            key=lambda candidate: (len(candidate.relative_to(run_dir).parts), candidate.as_posix()),
        )
        if matches:
            return matches[0]
    return None


def discover_artifacts(run_dir: Path) -> tuple[dict[str, Path | None], str | None]:
    resolved_run_dir = run_dir.resolve()
    artifacts: dict[str, Path | None] = {}
    for key, names in ARTIFACT_SPECS.items():
        found = _find_first(run_dir, names)
        if found is not None and not _is_relative_to(found.resolve(), resolved_run_dir):
            return artifacts | {key: found}, key
        artifacts[key] = found
    return artifacts, None


def _artifact_texts(artifacts: dict[str, Path | None], keys: Iterable[str]) -> dict[str, str]:
    return {key: _read_text(path) for key in keys if (path := artifacts.get(key)) is not None}


def _scan_patterns(texts: Iterable[str], patterns: dict[str, str]) -> list[str]:
    joined = "\n".join(texts).lower()
    signals: list[str] = []
    for pattern, label in patterns.items():
        if pattern in joined and label not in signals:
            signals.append(label)
    return signals


def _extract_matching_lines(texts: Iterable[str], patterns: Iterable[str], limit: int = MAX_EXTRACTED_LINES) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    lowered_patterns = tuple(pattern.lower() for pattern in patterns)
    for text in texts:
        for raw_line in text.splitlines():
            line = " ".join(raw_line.strip().split())
            if not line:
                continue
            lower = line.lower()
            if any(pattern in lower for pattern in lowered_patterns):
                clipped = line[:MAX_LINE_CHARS]
                if clipped not in seen:
                    found.append(clipped)
                    seen.add(clipped)
            if len(found) >= limit:
                return found
    return found


def _environment_signals(artifacts: dict[str, Path | None]) -> list[dict[str, str]]:
    texts = _artifact_texts(artifacts, ("runner_result", "failure_report", "quality_review", "final_v1"))
    signals: list[dict[str, str]] = []
    for key, text in texts.items():
        lower = text.lower()
        for pattern, label in ENVIRONMENT_PATTERNS.items():
            if pattern in lower:
                signal = {"artifact": key, "signal": label}
                if signal not in signals:
                    signals.append(signal)
    return signals


def _artifact_paths_payload(artifacts: dict[str, Path | None]) -> dict[str, str | None]:
    return {key: str(path) if path is not None else None for key, path in artifacts.items()}


def _artifact_hashes_payload(artifacts: dict[str, Path | None]) -> dict[str, str]:
    return {key: _sha256(path) for key, path in artifacts.items() if path is not None}


def _artifacts_found_missing(artifacts: dict[str, Path | None]) -> tuple[dict[str, str], list[str]]:
    found = {key: str(path) for key, path in artifacts.items() if path is not None}
    missing = [key for key, path in artifacts.items() if path is None]
    return found, missing


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_report_md(path: Path, payload: dict) -> None:
    lines = ["# Topic Refinement Artifact Loader Report", ""]
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            lines.append(f"## {key}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(value, indent=2, sort_keys=False, ensure_ascii=False))
            lines.append("```")
            lines.append("")
        else:
            lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_blocked_report(
    status: str,
    run_dir: Path,
    output_dir: Path,
    topic_id: str,
    user_feedback: str,
    reason: str,
    artifacts: dict[str, Path | None] | None = None,
    environment_signals: list[dict[str, str]] | None = None,
    write_report: bool = True,
) -> LoadResult:
    payload = {
        "status": status,
        "generated_at_utc": _utc_now(),
        "topic_id": topic_id,
        "run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "reason": reason,
        "artifacts_found": {},
        "artifacts_missing": [],
        "environment_signals": environment_signals or [],
        "selected_failure_type": None,
        "selected_refinement_mode": None,
        "no_runtime_integration": True,
        "no_llm_called": True,
        "no_pipeline_rerun": True,
        "no_mode_selected": True,
        "no_final_rewritten": True,
    }
    if artifacts is not None:
        found, missing = _artifacts_found_missing(artifacts)
        payload["artifacts_found"] = found
        payload["artifacts_missing"] = missing
    if write_report:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "artifact_loader_blocked_report.json"
        md_path = output_dir / "artifact_loader_blocked_report.md"
        _write_json(json_path, payload)
        _write_report_md(md_path, payload)
        return LoadResult(status=status, exit_code=2, output_dir=output_dir, report_json_path=json_path, report_md_path=md_path)
    sys.stderr.write(json.dumps(payload, sort_keys=False, ensure_ascii=False) + "\n")
    return LoadResult(status=status, exit_code=2, output_dir=None)


def build_initial_state(
    *,
    run_dir: Path,
    output_dir: Path,
    topic_id: str,
    user_feedback: str,
    allow_source_acquisition: bool,
    allow_full_text_verification: bool,
    artifacts: dict[str, Path | None],
    environment_signals: list[dict[str, str]],
) -> dict:
    all_texts = _artifact_texts(artifacts, artifacts.keys())
    quality_texts = _artifact_texts(artifacts, ("quality_review", "final_v1", "convergence_report", "calibration_report"))
    evidence_texts = _artifact_texts(artifacts, ("research_evidence_packet", "calibration_report", "quality_review", "final_v1"))
    calibration_texts = _artifact_texts(artifacts, ("calibration_report", "quality_review", "final_v1"))
    original_question = ""
    if artifacts.get("original_user_question") is not None:
        original_question = _read_text(artifacts["original_user_question"]).strip()

    hashes = _artifact_hashes_payload(artifacts)
    final_path = artifacts["final_v1"]
    assert final_path is not None
    final_hash = hashes.get("final_v1")

    preserved_caveats = _extract_matching_lines(
        [all_texts[key] for key in ("calibration_report", "research_evidence_packet", "final_v1", "quality_review") if key in all_texts],
        CAVEAT_LINE_PATTERNS,
    )
    unresolved_evidence_gaps = _extract_matching_lines(
        [all_texts[key] for key in ("research_evidence_packet", "calibration_report", "quality_review") if key in all_texts],
        EVIDENCE_GAP_LINE_PATTERNS,
    )

    confidence_boundary = "Confidence must not increase without new evidence or stronger artifact support."
    if unresolved_evidence_gaps:
        confidence_boundary += " Existing evidence gaps remain unresolved."

    return {
        "schema_version": SCHEMA_VERSION,
        "state_type": "topic_refinement_state_initial",
        "loader_version": LOADER_VERSION,
        "generated_at_utc": _utc_now(),
        "topic_id": topic_id,
        "original_question": original_question,
        "current_final_version": "final_v1",
        "current_final_version_path": str(final_path),
        "artifact_paths": _artifact_paths_payload(artifacts),
        "artifact_hashes": hashes,
        "user_feedback": user_feedback,
        "user_feedback_history": [
            {
                "feedback": user_feedback,
                "recorded_at_utc": _utc_now(),
                "source": "cli",
            }
        ],
        "detected_quality_signals": _scan_patterns(quality_texts.values(), QUALITY_PATTERNS),
        "detected_evidence_boundary_signals": _scan_patterns(evidence_texts.values(), EVIDENCE_PATTERNS),
        "detected_calibration_boundary_signals": _scan_patterns(calibration_texts.values(), CALIBRATION_PATTERNS),
        "detected_environment_signals": environment_signals,
        "selected_failure_type": None,
        "selected_refinement_mode": None,
        "selection_tie_breaker_reason": None,
        "allowed_scope": {
            "kind": "artifact_loader_dry_run_only",
            "may_select_refinement_mode": False,
            "may_rewrite_final": False,
            "may_rerun_pipeline": False,
            "may_call_llm": False,
        },
        "authorization": {
            "allow_source_acquisition": allow_source_acquisition,
            "allow_full_text_verification": allow_full_text_verification,
        },
        "preserved_caveats": preserved_caveats,
        "unresolved_evidence_gaps": unresolved_evidence_gaps,
        "confidence_boundary": confidence_boundary,
        "final_versions": [
            {
                "version": "final_v1",
                "path": str(final_path),
                "sha256": final_hash,
                "created_by": "existing_artifact",
                "overwritten": False,
            }
        ],
        "refinement_history": [],
        "stop_reason": None,
        "next_action": "needs_mode_router",
        "append_only_warning": "Do not overwrite final_v1; append any future refinement as a new version.",
        "no_runtime_integration": True,
        "no_llm_called": True,
        "no_pipeline_rerun": True,
    }


def load_artifacts(
    *,
    run_dir: Path,
    topic_id: str,
    user_feedback: str,
    output_dir: Path,
    allow_source_acquisition: bool = False,
    allow_full_text_verification: bool = False,
) -> LoadResult:
    if not topic_id.strip():
        return _write_blocked_report(
            BLOCKED_INVALID_TOPIC_ID,
            run_dir,
            output_dir,
            topic_id,
            user_feedback,
            "topic_id is empty",
            write_report=_is_output_dir_allowed(output_dir),
        )
    if not user_feedback.strip():
        return _write_blocked_report(
            BLOCKED_INVALID_USER_FEEDBACK,
            run_dir,
            output_dir,
            topic_id,
            user_feedback,
            "user_feedback is empty",
            write_report=_is_output_dir_allowed(output_dir),
        )
    if not _is_output_dir_allowed(output_dir):
        return _write_blocked_report(
            BLOCKED_INVALID_OUTPUT_DIR,
            run_dir,
            output_dir,
            topic_id,
            user_feedback,
            "output_dir must be under repo outputs/ or a temporary test directory",
            write_report=False,
        )
    if (output_dir / STATE_FILENAME).exists():
        return _write_blocked_report(
            BLOCKED_OUTPUT_ALREADY_EXISTS,
            run_dir,
            output_dir,
            topic_id,
            user_feedback,
            f"{STATE_FILENAME} already exists",
        )
    if not run_dir.exists() or not run_dir.is_dir():
        return _write_blocked_report(
            BLOCKED_RUN_DIR_MISSING,
            run_dir,
            output_dir,
            topic_id,
            user_feedback,
            "run_dir does not exist or is not a directory",
        )

    artifacts, escaped_key = discover_artifacts(run_dir)
    if escaped_key is not None:
        return _write_blocked_report(
            BLOCKED_ARTIFACT_PATH_ESCAPE,
            run_dir,
            output_dir,
            topic_id,
            user_feedback,
            f"artifact {escaped_key} resolves outside run_dir",
            artifacts=artifacts,
        )
    if artifacts.get("final_v1") is None:
        return _write_blocked_report(
            BLOCKED_MISSING_FINAL_V1,
            run_dir,
            output_dir,
            topic_id,
            user_feedback,
            "required final_v1 artifact is missing",
            artifacts=artifacts,
        )
    if artifacts.get("quality_review") is None:
        return _write_blocked_report(
            BLOCKED_MISSING_QUALITY_REVIEW,
            run_dir,
            output_dir,
            topic_id,
            user_feedback,
            "required quality_review artifact is missing",
            artifacts=artifacts,
        )

    env_signals = _environment_signals(artifacts)
    if env_signals:
        return _write_blocked_report(
            BLOCKED_ENVIRONMENT_OR_RUNTIME_ARTIFACT,
            run_dir,
            output_dir,
            topic_id,
            user_feedback,
            "environment or runtime blocker signal detected in artifacts",
            artifacts=artifacts,
            environment_signals=env_signals,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    state = build_initial_state(
        run_dir=run_dir,
        output_dir=output_dir,
        topic_id=topic_id.strip(),
        user_feedback=user_feedback.strip(),
        allow_source_acquisition=allow_source_acquisition,
        allow_full_text_verification=allow_full_text_verification,
        artifacts=artifacts,
        environment_signals=env_signals,
    )
    state_path = output_dir / STATE_FILENAME
    _write_json(state_path, state)

    found, missing = _artifacts_found_missing(artifacts)
    report = {
        "status": PASS_STATUS,
        "generated_at_utc": _utc_now(),
        "topic_id": topic_id.strip(),
        "run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "artifacts_found": found,
        "artifacts_missing": missing,
        "required_artifacts_check": {
            "final_v1": artifacts.get("final_v1") is not None,
            "quality_review": artifacts.get("quality_review") is not None,
            "pass": all(artifacts.get(key) is not None for key in REQUIRED_ARTIFACTS),
        },
        "environment_blocker_check": {
            "pass": True,
            "signals": env_signals,
        },
        "no_llm_called": True,
        "no_pipeline_rerun": True,
        "no_mode_selected": True,
        "no_final_rewritten": True,
        "next_action": "run mode router dry-run utility",
    }
    report_json_path = output_dir / "artifact_loader_report.json"
    report_md_path = output_dir / "artifact_loader_report.md"
    _write_json(report_json_path, report)
    _write_report_md(report_md_path, report)
    return LoadResult(
        status=PASS_STATUS,
        exit_code=0,
        output_dir=output_dir,
        state_path=state_path,
        report_json_path=report_json_path,
        report_md_path=report_md_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run loader for Topic Refinement Loop artifacts.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--topic-id", required=True)
    parser.add_argument("--user-feedback", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--allow-source-acquisition", type=_parse_bool, default=False)
    parser.add_argument("--allow-full-text-verification", type=_parse_bool, default=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = load_artifacts(
        run_dir=args.run_dir,
        topic_id=args.topic_id,
        user_feedback=args.user_feedback,
        output_dir=args.output_dir,
        allow_source_acquisition=args.allow_source_acquisition,
        allow_full_text_verification=args.allow_full_text_verification,
    )
    print(result.status)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
