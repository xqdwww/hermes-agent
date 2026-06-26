#!/usr/bin/env python3
"""Local background dossier runtime for the explicit Series B production target."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_production_target_loader import DEFAULT_TARGET_MANIFEST, ProductionTargetLayerError, load_explicit_production_target

REPO_ROOT = Path(__file__).resolve().parents[4]
RESULT_PLAN = "SERIES_B_BACKGROUND_DOSSIER_DRY_RUN_PLAN_PASS"
RESULT_EXECUTE = "SERIES_B_BACKGROUND_DOSSIER_EXECUTION_PASS"
REQUIRED_SECTIONS = ["culture", "history", "nature", "regional_relations", "food", "theme_tracks"]
FORBIDDEN_BODY_TERMS = [
    "hotel",
    "booking",
    "ticket",
    "itinerary",
    "reservation",
    "opening hours",
    "酒店",
    "订票",
    "预约建议",
    "机构推荐",
    "广告文案",
    "打卡清单",
]


class BackgroundDossierRuntimeError(ValueError):
    """Raised when the runtime hook is unsafe or invalid."""

    def __init__(self, error_code: str, message: str):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.message = message


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def repo_status() -> dict[str, Any]:
    status = subprocess.run(["git", "status", "--short", "--branch", "-uall"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    diff = subprocess.run(["git", "diff", "--name-only"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    cached = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    dirty_lines = [line for line in status.stdout.splitlines() if not line.startswith("##")]
    return {
        "status_short_branch": status.stdout.strip(),
        "tracked_diff": [line for line in diff.stdout.splitlines() if line.strip()],
        "staged_diff": [line for line in cached.stdout.splitlines() if line.strip()],
        "dirty_lines": dirty_lines,
        "clean": status.returncode == 0 and not dirty_lines and not diff.stdout.strip() and not cached.stdout.strip(),
    }


def git_head() -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_HEAD_UNREADABLE", proc.stderr.strip())
    return proc.stdout.strip()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_output_dir(output_dir: str | Path) -> Path:
    target = Path(output_dir).expanduser().resolve(strict=False)
    if _is_relative_to(target, REPO_ROOT):
        raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_OUTPUT_DIR_INSIDE_REPO", "output_dir must be outside the travel repo")
    lowered = str(target).lower()
    risky = ("source_raw", "normalized_text", "vector_index", "production_vector", "official_baseline_current.json")
    if any(term in lowered for term in risky):
        raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_OUTPUT_DIR_WRITE_RISK", f"output_dir contains write-risk marker: {target}")
    return target


def validate_no_write_flags(*, no_source_write: bool, no_vector_write: bool, no_official_baseline_write: bool) -> None:
    if not no_source_write:
        raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_SOURCE_WRITE_RISK", "--no-source-write is required")
    if not no_vector_write:
        raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_VECTOR_WRITE_RISK", "--no-vector-write is required")
    if not no_official_baseline_write:
        raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_BASELINE_WRITE_RISK", "--no-official-baseline-write is required")


def load_target(production_target: str | Path) -> dict[str, Any]:
    if not production_target:
        raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_TARGET_REQUIRED", "--production-target is required")
    target = Path(production_target).expanduser()
    if not target.is_absolute():
        target = (REPO_ROOT / target).resolve(strict=False)
    default_target = DEFAULT_TARGET_MANIFEST.resolve(strict=False)
    if target.resolve(strict=False) != default_target:
        raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_TARGET_AMBIGUOUS", "runtime hook only accepts the explicit Series B production target manifest")
    try:
        return load_explicit_production_target(target)
    except ProductionTargetLayerError as exc:
        raise BackgroundDossierRuntimeError(exc.error_code, exc.message) from exc


def infer_place_profile(query: str) -> dict[str, Any]:
    lowered = query.lower()
    if "新疆" in query or "北疆" in query or "xinjiang" in lowered:
        return {
            "title": "Northern Xinjiang Background Dossier",
            "place_frame": "Northern Xinjiang as a mountain, basin, steppe, oasis, and cross-border cultural region",
            "culture": ["multiethnic frontier context", "pastoral and oasis lifeways", "language and festival awareness"],
            "history": ["Silk Road corridor layers", "imperial frontier governance", "modern mobility and border-region context"],
            "nature": ["Tian Shan and Altai mountain systems", "arid basin ecology", "grassland, forest, lake, and desert transitions"],
            "regional_relations": ["Central Asian adjacency", "oasis route networks", "links between Ili, Altay, Urumqi, and Turpan contexts"],
            "food": ["wheat, lamb, dairy, fruit, tea, and market foodways as cultural context"],
            "theme_tracks": ["landscape formation", "oasis-pastoral interface", "ethnic cultural etiquette", "route history"],
        }
    if "东京" in query or "tokyo" in lowered:
        return {
            "title": "Tokyo Family Travel Background Dossier",
            "place_frame": "Tokyo as an Edo-to-modern metropolis organized by rail, neighborhoods, museums, and public learning spaces",
            "culture": ["Edo urban memory", "neighborhood craft and pop culture", "public manners and family learning norms"],
            "history": ["Edo capital formation", "Meiji modernization", "postwar reconstruction and contemporary metropolitan governance"],
            "nature": ["bay edge, river corridors, gardens, and disaster-aware urban geography"],
            "regional_relations": ["Kanto rail network", "Tokyo Bay relations", "subcenter links such as Ueno, Odaiba, Shibuya, and Marunouchi"],
            "food": ["washoku basics, department-store food halls, ramen/soba/curry family contexts, seasonal sweets"],
            "theme_tracks": ["science literacy", "art viewing habits", "transit urbanism", "food culture as neighborhood reading"],
        }
    if "首尔" in query or "seoul" in lowered or "医美" in query:
        return {
            "title": "Seoul Medical Beauty And Urban Observation Background Dossier",
            "place_frame": "Seoul as a capital region shaped by river geography, districts, media industries, consumer culture, and medical service clustering",
            "culture": ["appearance culture as social context", "K-culture media influence", "urban consumer norms and privacy awareness"],
            "history": ["Joseon capital layers", "rapid postwar urbanization", "Gangnam-era service economy development"],
            "nature": ["Han River corridor", "mountain-ringed basin setting", "dense district-scale urban form"],
            "regional_relations": ["Gangnam, Myeongdong, Hongdae, Jongno, and airport-region relations", "capital-region service flows"],
            "food": ["Korean meal structure, cafes, street snacks, barbecue, soup, and market foodways"],
            "theme_tracks": ["urban aesthetics industry", "medical consumption context", "district comparison", "media and consumer culture"],
        }
    return {
        "title": "Travel Background Dossier",
        "place_frame": "General travel background orientation",
        "culture": ["local etiquette", "daily life", "cultural memory"],
        "history": ["historical layers", "urban or regional change"],
        "nature": ["landscape and climate context"],
        "regional_relations": ["nearby regions and route context"],
        "food": ["foodways and meal culture"],
        "theme_tracks": ["culture", "history", "nature", "regional relations", "food"],
    }


def build_plan(query: str, validation: dict[str, Any]) -> dict[str, Any]:
    profile = infer_place_profile(query)
    return {
        "status": "PASS",
        "mode": "background_dossier_build_plan",
        "query": query,
        "production_target_id": validation["layer_id"],
        "official_baseline_current": validation["official_baseline_ref"],
        "sections": REQUIRED_SECTIONS,
        "place_frame": profile["place_frame"],
        "no_write_policy": {
            "source_data_write_enabled": False,
            "vector_write_enabled": False,
            "official_baseline_write_enabled": False,
            "production_vector_write_enabled": False,
        },
        "output_policy": "repo_external_only",
        "content_policy": {
            "background_dossier_only": True,
            "itinerary_listing_excluded": True,
            "hotel_ticket_booking_excluded": True,
        },
    }


def render_dossier(query: str, validation: dict[str, Any]) -> str:
    profile = infer_place_profile(query)
    lines = [
        f"# {profile['title']}",
        "",
        "## Runtime Metadata",
        "",
        f"- production_target_id: `{validation['layer_id']}`",
        f"- official_baseline_current: `{validation['official_baseline_ref']}`",
        "- mode: `background_dossier_only`",
        "- logistics_planning: `excluded`",
        "- source_vector_writes: `disabled`",
        "",
        "## Orientation",
        "",
        profile["place_frame"],
        "",
    ]
    section_titles = {
        "culture": "Culture",
        "history": "History",
        "nature": "Nature And Geography",
        "regional_relations": "Regional Relations",
        "food": "Food Culture",
        "theme_tracks": "Theme Tracks",
    }
    for section in REQUIRED_SECTIONS:
        lines.extend([f"## {section_titles[section]}", ""])
        for item in profile[section]:
            lines.append(f"- {item}")
        lines.append("")
    lines.extend(
        [
            "## Use Guidance",
            "",
            "Use this as a background knowledge frame before planning. Keep the next step focused on source-aware cultural, historical, ecological, regional, and food context.",
            "",
        ]
    )
    return "\n".join(lines)


def guard_dossier_body(body: str) -> dict[str, Any]:
    lowered = body.lower()
    hits = [term for term in FORBIDDEN_BODY_TERMS if term.lower() in lowered]
    sections_present = [section for section in REQUIRED_SECTIONS if section.replace("_", " ") in lowered or section in lowered]
    return {
        "status": "PASS" if not hits and len(sections_present) == len(REQUIRED_SECTIONS) else "FAIL",
        "forbidden_terms_found": hits,
        "sections_required": REQUIRED_SECTIONS,
        "sections_detected": sections_present,
        "itinerary_listing_contamination": bool(hits),
    }


def run_background_dossier(
    *,
    query: str,
    production_target: str | Path,
    output_dir: str | Path,
    no_source_write: bool,
    no_vector_write: bool,
    no_official_baseline_write: bool,
    background_dossier_only: bool,
    no_itinerary: bool,
    dry_run_plan_only: bool,
    execute: bool,
) -> tuple[int, dict[str, Any]]:
    try:
        if not query.strip():
            raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_QUERY_REQUIRED", "--query is required")
        validate_no_write_flags(
            no_source_write=no_source_write,
            no_vector_write=no_vector_write,
            no_official_baseline_write=no_official_baseline_write,
        )
        if not background_dossier_only:
            raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_BACKGROUND_ONLY_REQUIRED", "--background-dossier-only is required")
        if not no_itinerary:
            raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_ITINERARY_RISK", "--no-itinerary is required")
        if dry_run_plan_only == execute:
            raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_MODE_INVALID", "choose exactly one of --dry-run-plan-only or --execute")
        target_output = validate_output_dir(output_dir)
        target_output.mkdir(parents=True, exist_ok=True)
        before_status = repo_status()
        loaded = load_target(production_target)
        validation = loaded["validation"]
        plan = build_plan(query, validation)
        body = "" if dry_run_plan_only else render_dossier(query, validation)
        guard = {"status": "PASS", "itinerary_listing_contamination": False, "forbidden_terms_found": [], "sections_required": REQUIRED_SECTIONS, "sections_detected": []}
        artifacts: list[str] = []
        if dry_run_plan_only:
            plan_path = target_output / "series_b_background_dossier_plan.json"
            plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            artifacts.append(str(plan_path))
            result_enum = RESULT_PLAN
        else:
            guard = guard_dossier_body(body)
            if guard["status"] != "PASS":
                raise BackgroundDossierRuntimeError("SERIES_B_BACKGROUND_DOSSIER_GUARD_FAIL", "generated dossier failed itinerary/listing or section guard")
            md_path = target_output / "series_b_background_dossier.md"
            md_path.write_text(body, encoding="utf-8")
            artifacts.append(str(md_path))
            result_enum = RESULT_EXECUTE
        after_status = repo_status()
        payload = {
            "status": "PASS",
            "result_enum": result_enum,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repo_path": str(REPO_ROOT),
            "repo_head": git_head(),
            "query": query,
            "production_target_loaded": True,
            "production_target_id": validation["layer_id"],
            "official_baseline_current": validation["official_baseline_ref"],
            "source_state_manifest": validation["resolved_paths"]["source_state_manifest_file"],
            "production_target_manifest": validation["manifest_path"],
            "sections_generated": REQUIRED_SECTIONS if execute else [],
            "dry_run_plan_only": dry_run_plan_only,
            "execute": execute,
            "background_dossier_only": background_dossier_only,
            "no_itinerary": no_itinerary,
            "source_vector_mutation_performed": False,
            "official_baseline_modified": False,
            "production_vector_index_written": False,
            "source_data_written": False,
            "pre_repo_status": before_status,
            "post_repo_status": after_status,
            "repo_clean_after": after_status["clean"],
            "plan": plan,
            "dossier_sha256": sha256_text(body) if body else None,
            "guard": guard,
            "artifacts_written": artifacts,
        }
        result_path = target_output / "series_b_background_dossier_result.json"
        result_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        artifacts.append(str(result_path))
        payload["artifacts_written"] = artifacts
        return 0, payload
    except BackgroundDossierRuntimeError as exc:
        payload = {
            "status": "BLOCKED",
            "result_enum": exc.error_code,
            "message": exc.message,
            "source_vector_mutation_performed": False,
            "official_baseline_modified": False,
            "production_vector_index_written": False,
            "source_data_written": False,
        }
        try:
            target_output = validate_output_dir(output_dir)
            target_output.mkdir(parents=True, exist_ok=True)
            (target_output / "series_b_background_dossier_result.json").write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass
        return 2, payload
