"""Deterministic decision context contract generation.

Phase 1 only: this module is intentionally standalone and is not imported by
the task runner or decision stages. It converts an original query plus a
production research packet path into a stable, auditable contract object.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "decision_context_contract.v1"
GENERATION_METHOD = "deterministic_query_packet_l2_5_parser_v1"
RUNTIME_INTEGRATION_ENABLED = False

DEFAULT_EVIDENCE_TIERS = [
    "evidence_supported",
    "plausible_inference",
    "forward_looking_hypothesis",
    "unsupported_or_speculative",
]

DEFAULT_FORBIDDEN_INTERNAL_TERMS = [
    "research packet",
    "Stage",
    "pipeline",
    "artifact",
    "convergence report",
    "external calibration",
    "evidence packet",
    "runner",
    "controller",
    "validation gate",
]

DEFAULT_FINAL_ACCEPTANCE_CHECKS = {
    "required_sections_present": True,
    "required_fields_per_item_present": True,
    "key_variables_retained": True,
    "moderator_variables_retained": True,
    "required_dimensions_covered": True,
    "evidence_tier_per_core_item": True,
    "forbidden_content_absent": True,
    "internal_language_absent": True,
    "topic_not_drifted": True,
    "generic_template_residue_absent": True,
}

DEFAULT_CLAIM_STRENGTH_POLICY = {
    "future_claims_cannot_be_evidence_supported_without_direct_current_evidence": True,
    "snippet_only_sources_must_be_low_or_conditional": True,
    "full_text_gap_must_remain_visible": True,
    "overclaim_terms_forbidden_without_support": [
        "proves",
        "guarantees",
        "必然",
        "证明",
        "一定",
    ],
}

TOP5_ITEM_FIELDS = [
    {
        "id": "current_advantage_or_defect",
        "label": "当前优势 / 当前缺陷",
        "required_scope": "per_top_item",
    },
    {
        "id": "trigger_condition",
        "label": "触发条件",
        "required_scope": "per_top_item",
    },
    {
        "id": "mediating_mechanism",
        "label": "中间机制",
        "required_scope": "per_top_item",
    },
    {
        "id": "reversal_outcome",
        "label": "反转后的陷阱 / 反转后的优势",
        "required_scope": "per_top_item",
    },
    {
        "id": "failure_condition",
        "label": "失效条件",
        "required_scope": "per_top_item",
    },
    {
        "id": "certainty_level",
        "label": "确定性等级",
        "required_scope": "per_top_item",
    },
    {
        "id": "evidence_tier",
        "label": "证据层级",
        "required_scope": "per_top_item",
    },
]

REQUIRED_PHASE1_SCHEMA_KEYS = [
    "contract_id",
    "contract_version",
    "task_topic",
    "source_provenance",
    "user_output_contract",
    "key_variables",
    "moderator_variables",
    "required_dimensions",
    "evidence_tiers",
    "forbidden_content",
    "forbidden_internal_terms",
    "claim_strength_policy",
    "final_acceptance_checks",
    "contract_warnings",
    "generation_method",
]

ADHD_AI_REQUIRED_SECTIONS = [
    "未来优势变陷阱 Top5",
    "未来缺陷变优势 Top5",
    "最危险的错误培养路径",
    "最反直觉但值得追踪的假设",
    "danger_flag",
]

ADHD_AI_KEY_VARIABLES = [
    {
        "id": "adhd_attention_variability",
        "label": "ADHD 注意力波动",
        "aliases": ["注意力波动", "attention variability"],
    },
    {
        "id": "interest_driven_attention",
        "label": "兴趣驱动",
        "aliases": ["兴趣驱动", "interest driven"],
    },
    {
        "id": "executive_function",
        "label": "执行功能",
        "aliases": ["执行功能", "executive function"],
    },
    {
        "id": "internal_mind_wandering",
        "label": "内在走神",
        "aliases": ["内在走神", "mind wandering"],
    },
    {
        "id": "ai_information_environment",
        "label": "AI 信息环境",
        "aliases": ["AI 信息环境", "AI", "artificial intelligence"],
    },
    {
        "id": "knowledge_cost_decline",
        "label": "知识获取成本下降",
        "aliases": ["知识获取成本", "知识获取成本下降"],
    },
    {
        "id": "child_long_term_development",
        "label": "儿童长期发展",
        "aliases": ["儿童长期发展", "长期发展"],
    },
]

ADHD_AI_MODERATORS = [
    {
        "id": "iq_124",
        "label": "IQ 124",
        "aliases": ["IQ 124", "IQ124", "智商 124"],
        "moderates": ["learning_speed", "abstraction_capacity", "validation_load"],
    },
    {
        "id": "long_term_bjj_training",
        "label": "长期柔术训练",
        "aliases": ["长期柔术", "柔术", "BJJ", "jiu-jitsu"],
        "moderates": ["body_feedback_system", "delay_tolerance", "self_regulation"],
    },
]

ADHD_AI_REQUIRED_DIMENSIONS = [
    {
        "id": "knowledge_acquisition_ability",
        "label": "知识获取能力",
        "aliases": ["知识获取能力"],
    },
    {
        "id": "problem_selection_ability",
        "label": "问题选择能力",
        "aliases": ["问题选择能力"],
    },
    {
        "id": "validation_ability",
        "label": "验证能力",
        "aliases": ["验证能力"],
    },
    {
        "id": "convergence_ability",
        "label": "收束能力",
        "aliases": ["收束能力"],
    },
    {
        "id": "delayed_feedback_tolerance",
        "label": "延迟反馈耐受",
        "aliases": ["延迟反馈耐受"],
    },
    {
        "id": "body_feedback_system",
        "label": "身体反馈系统",
        "aliases": ["身体反馈系统", "身体反馈"],
    },
]

DEFAULT_FORBIDDEN_CONTENT = [
    {"id": "medical_diagnosis", "label": "医学诊断", "aliases": ["诊断"]},
    {"id": "treatment_advice", "label": "治疗建议", "aliases": ["治疗建议", "治疗"]},
    {"id": "parenting_advice", "label": "家长建议", "aliases": ["家长建议"]},
    {"id": "training_plan", "label": "培养计划", "aliases": ["培养计划"]},
]


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str | None:
    file_path = Path(path)
    if not file_path.is_file():
        return None
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _read_text_if_exists(path: str | Path | None) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.is_file():
        return ""
    return file_path.read_text(encoding="utf-8", errors="replace")


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _extract_metadata_value(text: str, names: list[str]) -> str | None:
    for name in names:
        pattern = re.compile(rf"(?im)^\s*(?:[-*]\s*)?{re.escape(name)}\s*[:：]\s*(.+?)\s*$")
        match = pattern.search(text)
        if match:
            value = match.group(1).strip().strip("`")
            if value:
                return value
    return None


def _infer_run_dir_from_packet_path(packet_path: Path) -> Path | None:
    if packet_path.name != "research_evidence_packet.md":
        return None
    if packet_path.parent.name == "L5_deepseek_acceptance":
        return packet_path.parent.parent
    return packet_path.parent


def _normalize_path(path: str | Path | None) -> str | None:
    if not path:
        return None
    return str(Path(path).expanduser())


def _infer_l2_5_paths(
    stage_a_artifact_dir: str | None,
    sources_path: str | Path | None,
    evidence_path: str | Path | None,
    claims_path: str | Path | None,
    gaps_path: str | Path | None,
) -> dict[str, str | None]:
    paths = {
        "l2_5_sources_path": _normalize_path(sources_path),
        "l2_5_evidence_path": _normalize_path(evidence_path),
        "l2_5_claims_path": _normalize_path(claims_path),
        "l2_5_gaps_path": _normalize_path(gaps_path),
    }
    if stage_a_artifact_dir:
        l2_5_dir = Path(stage_a_artifact_dir) / "L2_5_codex_evidence_organizer"
        defaults = {
            "l2_5_sources_path": l2_5_dir / "sources.csv",
            "l2_5_evidence_path": l2_5_dir / "evidence.csv",
            "l2_5_claims_path": l2_5_dir / "claims.md",
            "l2_5_gaps_path": l2_5_dir / "gaps.md",
        }
        for key, default_path in defaults.items():
            if not paths[key]:
                paths[key] = str(default_path)
    return paths


def _contains_any(text: str, needles: list[str]) -> bool:
    lower = text.lower()
    return any(needle.lower() in lower for needle in needles)


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get("id") or record.get("label"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _record_with_source(
    record: dict[str, Any],
    source: str,
    required_scope: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enriched = dict(record)
    enriched["source"] = source
    enriched["required_in_final"] = True
    enriched["required_scope"] = required_scope
    if extra:
        enriched.update(extra)
    return enriched


def _extract_domain(original_query: str, combined_text: str) -> str:
    text = f"{original_query}\n{combined_text}"
    if _contains_any(text, ["ADHD", "注意力", "执行功能"]) and _contains_any(text, ["AI", "人工智能"]):
        return "research_decision"
    if _contains_any(text, ["literature review", "文献综述", "academic"]):
        return "academic_literature_review"
    if _contains_any(text, ["travel", "itinerary", "hotel", "旅行", "酒店"]):
        return "travel"
    if _contains_any(text, ["finance", "portfolio", "risk", "投资", "财务"]):
        return "finance"
    return "generic"


def _extract_task_topic(original_query: str, combined_text: str) -> dict[str, Any]:
    domain = _extract_domain(original_query, combined_text)
    if domain == "research_decision" and _contains_any(original_query + combined_text, ["ADHD"]):
        title = "AI 信息环境下 ADHD 儿童特征结构性反转"
        must_match_terms = [
            "ADHD",
            "AI",
            "结构性反转",
            "儿童长期发展",
            "知识获取成本下降",
        ]
        must_not_drift_to = [
            "production execution readiness",
            "pipeline readiness",
            "generic professional reversal",
            "generic AI education article",
        ]
    else:
        compact = " ".join(original_query.split())
        title = compact[:120] if compact else "unspecified decision topic"
        must_match_terms = _extract_requirement_terms(original_query)
        must_not_drift_to = ["pipeline readiness", "generic template answer"]
    return {
        "title": title,
        "topic_fingerprint": sha256_text(original_query),
        "domain": domain,
        "must_match_terms": must_match_terms,
        "must_not_drift_to": must_not_drift_to,
    }


def _extract_requirement_terms(text: str) -> list[str]:
    candidates = re.findall(r"[\w\u4e00-\u9fff][\w\u4e00-\u9fff \-×]{2,32}", text)
    cleaned: list[str] = []
    for candidate in candidates:
        term = " ".join(candidate.split()).strip(" ,，。:：")
        if len(term) < 3:
            continue
        if term in cleaned:
            continue
        cleaned.append(term)
        if len(cleaned) >= 10:
            break
    return cleaned


def _extract_required_sections(original_query: str, combined_text: str) -> list[str]:
    text = original_query + "\n" + combined_text
    if all(section in text for section in ADHD_AI_REQUIRED_SECTIONS[:2]) or _contains_any(
        text, ["优势变陷阱", "缺陷变优势", "danger_flag"]
    ):
        return list(ADHD_AI_REQUIRED_SECTIONS)
    sections: list[str] = []
    for line in original_query.splitlines():
        stripped = line.strip(" -*\t")
        if stripped and _contains_any(stripped, ["Top", "必须包含", "danger_flag"]):
            sections.append(stripped)
    return sections


def _extract_key_variables(original_query: str, combined_text: str) -> list[dict[str, Any]]:
    text = original_query + "\n" + combined_text
    records: list[dict[str, Any]] = []
    for item in ADHD_AI_KEY_VARIABLES:
        if _contains_any(text, [item["label"], *item["aliases"]]):
            records.append(_record_with_source(item, "original_query_or_stage_a", "global"))
    if not records:
        for index, term in enumerate(_extract_requirement_terms(original_query)[:8], start=1):
            records.append(
                {
                    "id": f"query_variable_{index}",
                    "label": term,
                    "aliases": [term],
                    "source": "original_query",
                    "required_in_final": True,
                    "required_scope": "global",
                }
            )
    return _dedupe_records(records)


def _extract_moderator_variables(original_query: str, combined_text: str) -> list[dict[str, Any]]:
    text = original_query + "\n" + combined_text
    records: list[dict[str, Any]] = []
    for item in ADHD_AI_MODERATORS:
        if _contains_any(text, [item["label"], *item["aliases"]]):
            records.append(_record_with_source(item, "original_query_or_stage_a", "global"))
    return _dedupe_records(records)


def _extract_required_dimensions(original_query: str, combined_text: str) -> list[dict[str, Any]]:
    text = original_query + "\n" + combined_text
    records: list[dict[str, Any]] = []
    for item in ADHD_AI_REQUIRED_DIMENSIONS:
        if _contains_any(text, [item["label"], *item["aliases"]]):
            records.append(
                _record_with_source(
                    item,
                    "original_query_or_stage_a",
                    "per_core_item",
                    {"coverage_requirement": "applied_per_core_item"},
                )
            )
    return _dedupe_records(records)


def _extract_forbidden_content(original_query: str, combined_text: str) -> list[dict[str, Any]]:
    text = original_query + "\n" + combined_text
    records: list[dict[str, Any]] = []
    for item in DEFAULT_FORBIDDEN_CONTENT:
        if _contains_any(text, [item["label"], *item["aliases"], "不要" + item["label"], "不得" + item["label"]]):
            records.append(
                {
                    "id": item["id"],
                    "label": item["label"],
                    "aliases": item["aliases"],
                    "source": "original_query_or_domain_policy",
                    "policy": "forbidden_in_final_user_output",
                }
            )
    if not records and _contains_any(text, ["ADHD", "儿童"]):
        records = [
            {
                "id": item["id"],
                "label": item["label"],
                "aliases": item["aliases"],
                "source": "domain_policy",
                "policy": "forbidden_in_final_user_output",
            }
            for item in DEFAULT_FORBIDDEN_CONTENT
        ]
    return _dedupe_records(records)


def _build_user_output_contract(
    required_sections: list[str],
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    contract = {
        "required_sections": required_sections,
        "required_item_fields": list(TOP5_ITEM_FIELDS),
        "required_counts": {
            "未来优势变陷阱 Top5": 5 if "未来优势变陷阱 Top5" in required_sections else None,
            "未来缺陷变优势 Top5": 5 if "未来缺陷变优势 Top5" in required_sections else None,
        },
        "section_order": required_sections,
        "style_constraints": [
            "user_facing_only",
            "no_internal_pipeline_language",
            "decision_problem_not_execution_readiness",
        ],
        "forbidden_answer_types": [
            "medical_diagnosis",
            "treatment_advice",
            "parenting_advice",
            "training_plan",
        ],
    }
    contract["required_counts"] = {
        key: value for key, value in contract["required_counts"].items() if value is not None
    }
    if override:
        for key, value in override.items():
            contract[key] = value
    return contract


def _collect_l2_5_text(paths: dict[str, str | None]) -> str:
    return "\n".join(_read_text_if_exists(path) for path in paths.values())


def _build_warnings(
    research_packet_path: Path,
    research_packet_hash: str | None,
    l2_5_paths: dict[str, str | None],
    key_variables: list[dict[str, Any]],
    required_dimensions: list[dict[str, Any]],
    required_sections: list[str],
) -> list[str]:
    warnings: list[str] = []
    if not research_packet_path.is_file():
        warnings.append("research_packet_missing")
    if not research_packet_hash:
        warnings.append("research_packet_hash_missing")
    for key, value in l2_5_paths.items():
        if not value:
            warnings.append(f"{key}_missing")
        elif not Path(value).is_file():
            warnings.append(f"{key}_not_found")
    if not required_sections:
        warnings.append("required_sections_not_detected")
    if not key_variables:
        warnings.append("key_variables_not_detected")
    if not required_dimensions:
        warnings.append("required_dimensions_not_detected")
    return warnings


def generate_decision_context_contract(
    *,
    original_query: str,
    research_packet_path: str | Path,
    l2_5_sources_path: str | Path | None = None,
    l2_5_evidence_path: str | Path | None = None,
    l2_5_claims_path: str | Path | None = None,
    l2_5_gaps_path: str | Path | None = None,
    user_output_contract_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a stable decision context contract.

    The function is offline and deterministic. It reads only the explicitly
    supplied current-run packet and optional L2.5 paths, plus inferred sibling
    L2.5 files when the run directory can be derived from the packet path.
    """

    packet_path = Path(research_packet_path).expanduser()
    packet_text = _read_text_if_exists(packet_path)
    packet_hash = sha256_file(packet_path)
    inferred_run_dir = _infer_run_dir_from_packet_path(packet_path)

    stage_a_run_id = _extract_metadata_value(
        packet_text,
        ["current_run_id", "run_id", "stage_a_run_id"],
    )
    if not stage_a_run_id and inferred_run_dir:
        stage_a_run_id = inferred_run_dir.name

    stage_a_artifact_dir = _extract_metadata_value(
        packet_text,
        ["current_artifact_dir", "artifact_dir", "stage_a_artifact_dir"],
    )
    if not stage_a_artifact_dir and inferred_run_dir:
        stage_a_artifact_dir = str(inferred_run_dir)

    l2_5_paths = _infer_l2_5_paths(
        stage_a_artifact_dir,
        l2_5_sources_path,
        l2_5_evidence_path,
        l2_5_claims_path,
        l2_5_gaps_path,
    )
    l2_5_text = _collect_l2_5_text(l2_5_paths)
    combined_text = "\n".join([packet_text, l2_5_text])

    original_query_hash = sha256_text(original_query)
    current_query_hash = _extract_metadata_value(packet_text, ["current_query_hash", "query_hash"])
    task_topic = _extract_task_topic(original_query, combined_text)
    required_sections = _extract_required_sections(original_query, combined_text)
    key_variables = _extract_key_variables(original_query, combined_text)
    moderator_variables = _extract_moderator_variables(original_query, combined_text)
    required_dimensions = _extract_required_dimensions(original_query, combined_text)
    forbidden_content = _extract_forbidden_content(original_query, combined_text)

    source_provenance = {
        "original_query_hash": original_query_hash,
        "current_query_hash": current_query_hash,
        "research_packet_path": str(packet_path),
        "research_packet_hash": packet_hash,
        "stage_a_run_id": stage_a_run_id,
        "stage_a_artifact_dir": stage_a_artifact_dir,
        **l2_5_paths,
    }
    contract: dict[str, Any] = {
        "contract_id": "",
        "contract_version": CONTRACT_VERSION,
        "task_topic": task_topic,
        "source_provenance": source_provenance,
        "user_output_contract": _build_user_output_contract(
            required_sections,
            user_output_contract_override,
        ),
        "key_variables": key_variables,
        "moderator_variables": moderator_variables,
        "required_dimensions": required_dimensions,
        "evidence_tiers": {
            "allowed": list(DEFAULT_EVIDENCE_TIERS),
            "required_per_core_item": True,
            "tier_label_policy": "user_facing_labels_only",
        },
        "forbidden_content": forbidden_content,
        "forbidden_internal_terms": list(DEFAULT_FORBIDDEN_INTERNAL_TERMS),
        "claim_strength_policy": dict(DEFAULT_CLAIM_STRENGTH_POLICY),
        "final_acceptance_checks": dict(DEFAULT_FINAL_ACCEPTANCE_CHECKS),
        "contract_warnings": [],
        "generation_method": GENERATION_METHOD,
        "runtime_integration_enabled": RUNTIME_INTEGRATION_ENABLED,
    }
    contract["contract_warnings"] = _build_warnings(
        packet_path,
        packet_hash,
        l2_5_paths,
        key_variables,
        required_dimensions,
        required_sections,
    )
    contract["contract_id"] = compute_contract_hash(contract)
    return contract


def compute_contract_hash(contract: dict[str, Any]) -> str:
    payload = copy.deepcopy(contract)
    payload["contract_id"] = ""
    return sha256_text(_stable_json(payload))


def validate_contract_schema(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract_not_dict"]
    for key in REQUIRED_PHASE1_SCHEMA_KEYS:
        if key not in contract:
            errors.append(f"missing_schema_key:{key}")
    if contract.get("contract_version") != CONTRACT_VERSION:
        errors.append("invalid_contract_version")
    if contract.get("generation_method") != GENERATION_METHOD:
        errors.append("invalid_generation_method")
    if contract.get("runtime_integration_enabled") is not False:
        errors.append("runtime_integration_must_be_false_in_phase1")
    return errors


def validate_required_fields(contract: dict[str, Any]) -> list[str]:
    errors = validate_contract_schema(contract)
    output_contract = contract.get("user_output_contract") or {}
    required_sections = output_contract.get("required_sections") or []
    required_item_fields = output_contract.get("required_item_fields") or []
    item_field_ids = {field.get("id") for field in required_item_fields if isinstance(field, dict)}
    if not required_sections:
        errors.append("missing_required_sections")
    for field in TOP5_ITEM_FIELDS:
        if field["id"] not in item_field_ids:
            errors.append(f"missing_required_item_field:{field['id']}")
    if not contract.get("key_variables"):
        errors.append("missing_key_variables")
    if not contract.get("required_dimensions"):
        errors.append("missing_required_dimensions")
    if not contract.get("evidence_tiers", {}).get("allowed"):
        errors.append("missing_evidence_tiers")
    if not contract.get("final_acceptance_checks"):
        errors.append("missing_final_acceptance_checks")
    return errors


def validate_provenance(contract: dict[str, Any]) -> list[str]:
    errors = validate_contract_schema(contract)
    provenance = contract.get("source_provenance") or {}
    required = [
        "original_query_hash",
        "research_packet_path",
        "research_packet_hash",
        "stage_a_run_id",
        "stage_a_artifact_dir",
        "l2_5_sources_path",
        "l2_5_evidence_path",
        "l2_5_claims_path",
        "l2_5_gaps_path",
    ]
    for key in required:
        if not provenance.get(key):
            errors.append(f"missing_provenance:{key}")
    packet_path = provenance.get("research_packet_path")
    if packet_path and not Path(packet_path).is_file():
        errors.append("missing_provenance_file:research_packet_path")
    for key in ["l2_5_sources_path", "l2_5_evidence_path", "l2_5_claims_path", "l2_5_gaps_path"]:
        value = provenance.get(key)
        if value and not Path(value).is_file():
            errors.append(f"missing_provenance_file:{key}")
    return errors


def render_contract_markdown(contract: dict[str, Any]) -> str:
    lines = [
        "# Decision Context Contract",
        "",
        f"- contract_id: {contract.get('contract_id', '')}",
        f"- contract_version: {contract.get('contract_version', '')}",
        f"- task_topic: {contract.get('task_topic', {}).get('title', '')}",
        f"- generation_method: {contract.get('generation_method', '')}",
        "",
        "## Required Sections",
    ]
    for section in contract.get("user_output_contract", {}).get("required_sections", []):
        lines.append(f"- {section}")
    lines.append("")
    lines.append("## Key Variables")
    for variable in contract.get("key_variables", []):
        lines.append(f"- {variable.get('label', '')}")
    lines.append("")
    lines.append("## Moderator Variables")
    for moderator in contract.get("moderator_variables", []):
        lines.append(f"- {moderator.get('label', '')}")
    lines.append("")
    lines.append("## Required Dimensions")
    for dimension in contract.get("required_dimensions", []):
        lines.append(f"- {dimension.get('label', '')}")
    lines.append("")
    lines.append("## Warnings")
    for warning in contract.get("contract_warnings", []):
        lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"
