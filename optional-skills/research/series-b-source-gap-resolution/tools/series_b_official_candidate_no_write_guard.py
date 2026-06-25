#!/usr/bin/env python3
"""No-write guard for Series B official candidate runner planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class OfficialCandidateGuardError(ValueError):
    """Raised when a candidate run request can mutate official or production state."""

    def __init__(self, error_code: str, message: str):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.message = message


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_output_dir(output_dir: str | Path, *, repo_root: str | Path) -> Path:
    target = Path(output_dir).expanduser().resolve(strict=False)
    repo = Path(repo_root).expanduser().resolve(strict=False)
    if _is_relative_to(target, repo):
        raise OfficialCandidateGuardError(
            "OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL",
            "candidate output_dir must be outside the travel repo",
        )
    lowered = str(target).lower()
    forbidden_markers = (
        "official_baseline",
        "baseline_ledger",
        "production_default",
        "production-vector",
        "production_vector",
    )
    if any(marker in lowered for marker in forbidden_markers):
        raise OfficialCandidateGuardError(
            "OFFICIAL_CANDIDATE_BASELINE_WRITE_RISK",
            f"candidate output_dir contains forbidden marker: {target}",
        )
    return target


def validate_no_write_policy(
    *,
    official_baseline_write_enabled: bool,
    production_default_enabled: bool,
    push_enabled: bool,
    tag_enabled: bool,
    candidate_mode: bool,
    output_dir: str | Path,
    repo_root: str | Path,
    write_targets: list[str | Path] | None = None,
    command: str | None = None,
) -> dict[str, Any]:
    if official_baseline_write_enabled:
        raise OfficialCandidateGuardError(
            "OFFICIAL_CANDIDATE_BASELINE_WRITE_RISK",
            "official baseline write must be disabled",
        )
    if production_default_enabled:
        raise OfficialCandidateGuardError(
            "OFFICIAL_CANDIDATE_PRODUCTION_DEFAULT_RISK",
            "production default integration must be disabled",
        )
    if push_enabled:
        raise OfficialCandidateGuardError("OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL", "push must be disabled")
    if tag_enabled:
        raise OfficialCandidateGuardError("OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL", "tag must be disabled")
    if not candidate_mode:
        raise OfficialCandidateGuardError(
            "OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL",
            "candidate mode must be explicit",
        )
    target = validate_output_dir(output_dir, repo_root=repo_root)

    repo = Path(repo_root).expanduser().resolve(strict=False)
    for raw in write_targets or []:
        path = Path(raw).expanduser().resolve(strict=False)
        lowered = str(path).lower()
        if _is_relative_to(path, repo):
            raise OfficialCandidateGuardError(
                "OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL",
                f"write target is inside repo: {path}",
            )
        if "official_baseline" in lowered or "baseline_ledger" in lowered:
            raise OfficialCandidateGuardError(
                "OFFICIAL_CANDIDATE_BASELINE_WRITE_RISK",
                f"write target looks like official baseline state: {path}",
            )
        if "production_default" in lowered or "production_vector" in lowered:
            raise OfficialCandidateGuardError(
                "OFFICIAL_CANDIDATE_PRODUCTION_DEFAULT_RISK",
                f"write target looks like production default state: {path}",
            )

    lowered_command = (command or "").lower()
    destructive_markers = ("--update-official", "--write-baseline", "git push", "git tag", "production-default")
    if any(marker in lowered_command for marker in destructive_markers):
        raise OfficialCandidateGuardError(
            "OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL",
            "candidate command contains destructive or production marker",
        )

    return {
        "status": "PASS",
        "result_enum": "OFFICIAL_CANDIDATE_DRY_RUN_PLAN_PASS",
        "output_dir": str(target),
        "official_baseline_write_enabled": False,
        "production_default_enabled": False,
        "push_enabled": False,
        "tag_enabled": False,
        "candidate_mode": True,
    }
