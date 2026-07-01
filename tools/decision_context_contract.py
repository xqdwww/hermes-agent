"""Deterministic decision context contract generation and validation.

The generator converts an original query plus a production research packet path
into a stable, auditable contract object. The validation helpers are deliberately
rule-based and offline so runner stages can fail closed without model calls.
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

META_EXECUTION_DRIFT_TERMS = [
    "pipeline execution",
    "production readiness",
    "schema readiness",
    "schema rollout",
    "pilot rollout",
    "production rollout",
    "task-engine implementation",
    "tool availability",
    "toolset",
    "runner availability",
    "gate artifact",
    "执行准备",
    "生产就绪",
    "模式接入",
    "工具可用性",
    "试点部署",
]

EVIDENCE_TIER_ALIASES = {
    "evidence_supported": ["evidence_supported", "supported", "证据支持", "证据支持项"],
    "plausible_inference": ["plausible_inference", "plausible", "合理推断", "条件性推断"],
    "forward_looking_hypothesis": ["forward_looking_hypothesis", "hypothesis", "假设", "前瞻性假设"],
    "unsupported_or_speculative": [
        "unsupported_or_speculative",
        "unsupported",
        "speculative",
        "证据不足",
        "推测",
    ],
}

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

FINAL_VALIDATION_MISSING_DECISION_CONTEXT_CONTRACT = "FINAL_VALIDATION_MISSING_DECISION_CONTEXT_CONTRACT"
FINAL_VALIDATION_MISSING_MODERATOR_RETENTION = "FINAL_VALIDATION_MISSING_MODERATOR_RETENTION"

GENERIC_TEMPLATE_RESIDUE_SECTION_HEADINGS = [
    "用户画像与约束如何进入判断",
    "逐题回答",
    "证据支持",
    "合理推断",
    "前瞻假设",
    "情景分叉",
    "观察指标与反证信号",
    "最终决策含义",
    "证据边界",
]

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


def _normalize_for_match(text: str) -> str:
    return " ".join((text or "").lower().split())


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


def _match_any_alias(text: str, labels: list[str]) -> bool:
    normalized = _normalize_for_match(text)
    return any(_normalize_for_match(label) in normalized for label in labels if label)


def _record_aliases(record: dict[str, Any]) -> list[str]:
    aliases = [str(record.get("label") or ""), str(record.get("id") or "")]
    aliases.extend(str(alias) for alias in record.get("aliases") or [])
    return [alias for alias in aliases if alias]


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


def validate_convergence_uses_contract(convergence_text: str, contract: dict[str, Any]) -> list[str]:
    errors = validate_contract_schema(contract)
    text = convergence_text or ""
    contract_id = str(contract.get("contract_id") or "")
    title = str(contract.get("task_topic", {}).get("title") or "")
    if contract_id and contract_id not in text:
        errors.append("missing_contract_id")
    if title and title not in text:
        errors.append("missing_task_topic")
    return errors


def validate_no_meta_execution_drift(text: str, contract: dict[str, Any]) -> list[str]:
    errors = validate_contract_schema(contract)
    value = text or ""
    drift_hits = [term for term in META_EXECUTION_DRIFT_TERMS if term.lower() in value.lower()]
    task_terms = list(contract.get("task_topic", {}).get("must_match_terms") or [])
    task_anchor_hits = [term for term in task_terms if term and term.lower() in value.lower()]
    if drift_hits and len(task_anchor_hits) < 2:
        errors.append("meta_execution_drift:" + ",".join(drift_hits[:5]))
    if len(drift_hits) >= 3:
        errors.append("meta_execution_drift_dominant:" + ",".join(drift_hits[:5]))
    return errors


def validate_required_variables_present(text: str, contract: dict[str, Any]) -> list[str]:
    errors = validate_contract_schema(contract)
    value = text or ""
    for variable in contract.get("key_variables") or []:
        if variable.get("required_in_final") and not _match_any_alias(value, _record_aliases(variable)):
            errors.append(f"missing_key_variable:{variable.get('id') or variable.get('label')}")
    for moderator in contract.get("moderator_variables") or []:
        if moderator.get("required_in_final") and not _match_any_alias(value, _record_aliases(moderator)):
            errors.append(f"missing_moderator_variable:{moderator.get('id') or moderator.get('label')}")
    return errors


def validate_required_dimensions_present(text: str, contract: dict[str, Any]) -> list[str]:
    errors = validate_contract_schema(contract)
    value = text or ""
    for dimension in contract.get("required_dimensions") or []:
        if not _match_any_alias(value, _record_aliases(dimension)):
            errors.append(f"missing_required_dimension:{dimension.get('id') or dimension.get('label')}")
    return errors


def validate_evidence_tiers_present(text: str, contract: dict[str, Any]) -> list[str]:
    errors = validate_contract_schema(contract)
    value = text or ""
    allowed = contract.get("evidence_tiers", {}).get("allowed") or []
    found = []
    for tier in allowed:
        aliases = EVIDENCE_TIER_ALIASES.get(str(tier), [str(tier)])
        if _match_any_alias(value, aliases):
            found.append(str(tier))
    if not found:
        errors.append("missing_evidence_tiers")
    return errors


def validate_calibration_object(calibration_text: str, contract: dict[str, Any]) -> list[str]:
    errors = validate_convergence_uses_contract(calibration_text, contract)
    errors.extend(validate_no_meta_execution_drift(calibration_text, contract))
    errors.extend(validate_required_variables_present(calibration_text, contract))
    errors.extend(validate_required_dimensions_present(calibration_text, contract))
    errors.extend(validate_evidence_tiers_present(calibration_text, contract))
    value = calibration_text or ""
    if not _match_any_alias(value, ["calibration_verdict", "校准", "calibrate", "evidence strength"]):
        errors.append("missing_calibration_object_marker")
    return _dedupe_error_list(errors)


def validate_convergence_contract_alignment(convergence_text: str, contract: dict[str, Any]) -> list[str]:
    errors = validate_convergence_uses_contract(convergence_text, contract)
    errors.extend(validate_no_meta_execution_drift(convergence_text, contract))
    errors.extend(validate_required_variables_present(convergence_text, contract))
    errors.extend(validate_required_dimensions_present(convergence_text, contract))
    errors.extend(validate_evidence_tiers_present(convergence_text, contract))
    return _dedupe_error_list(errors)


def validate_final_report_contract_rendering(text: str, contract: dict[str, Any]) -> list[str]:
    errors = validate_contract_schema(contract)
    value = text or ""
    required_sections = contract.get("user_output_contract", {}).get("required_sections") or []
    required_counts = contract.get("user_output_contract", {}).get("required_counts") or {}
    required_item_fields = contract.get("user_output_contract", {}).get("required_item_fields") or []
    required_field_labels = [str(field.get("label") or "") for field in required_item_fields if isinstance(field, dict)]
    for section in required_sections:
        body = _markdown_section_body(value, str(section))
        if not body:
            errors.append(f"missing_required_section:{section}")
            continue
        expected_count = int(required_counts.get(section) or 0)
        if expected_count:
            item_count = len(re.findall(r"(?m)^\s*\d+\.\s+", body))
            if item_count < expected_count:
                errors.append(f"missing_required_count:{section}:{expected_count}")
            for label in required_field_labels:
                if label and body.count(label) < expected_count:
                    errors.append(f"missing_item_field:{section}:{label}")
    for variable in contract.get("key_variables") or []:
        if variable.get("required_in_final") and not _match_any_alias(value, _record_aliases(variable)):
            errors.append(f"missing_key_variable:{variable.get('id') or variable.get('label')}")
    for moderator in contract.get("moderator_variables") or []:
        if moderator.get("required_in_final") and not _match_any_alias(value, _record_aliases(moderator)):
            errors.append(f"missing_moderator_variable:{moderator.get('id') or moderator.get('label')}")
    for dimension in contract.get("required_dimensions") or []:
        if not _match_any_alias(value, _record_aliases(dimension)):
            errors.append(f"missing_required_dimension:{dimension.get('id') or dimension.get('label')}")
    if validate_evidence_tiers_present(value, contract):
        errors.append("missing_evidence_tiers")
    for term in contract.get("forbidden_internal_terms") or []:
        if str(term).lower() in value.lower():
            errors.append(f"forbidden_internal_term:{term}")
    for heading in GENERIC_TEMPLATE_RESIDUE_SECTION_HEADINGS:
        if re.search(rf"(?m)^#{{2,6}}\s*{re.escape(heading)}\s*$", value):
            errors.append(f"generic_template_residue:{heading}")
    return _dedupe_error_list(errors)


def validate_final_report_against_decision_context_contract(
    text: str,
    contract: dict[str, Any],
) -> list[str]:
    """Independently validate a user-facing final report against its contract.

    This is stricter than the renderer self-check: it is intended for the final
    production validation gate and therefore verifies exact TopN counts, per-item
    fields, moderator retention, per-item evidence tier signals, and generic
    template residue.
    """
    errors = validate_final_report_contract_rendering(text, contract)
    value = text or ""
    if not value.strip():
        return _dedupe_error_list([*errors, "final_report_empty"])

    output_contract = contract.get("user_output_contract") or {}
    required_sections = [str(section) for section in output_contract.get("required_sections") or []]
    required_counts = output_contract.get("required_counts") or {}
    required_item_fields = [
        str(field.get("label") or "")
        for field in output_contract.get("required_item_fields") or []
        if isinstance(field, dict) and str(field.get("label") or "").strip()
    ]

    for section in required_sections:
        expected_count = int(required_counts.get(section) or 0)
        if not expected_count:
            continue
        body = _markdown_section_body(value, section)
        if not body:
            continue
        items = _numbered_markdown_items(body)
        if len(items) != expected_count:
            errors.append(f"required_count_mismatch:{section}:{expected_count}:{len(items)}")
        for index, item in enumerate(items[:expected_count], start=1):
            for label in required_item_fields:
                if label not in item:
                    errors.append(f"missing_item_field:{section}:{index}:{label}")
            if "确定性等级" not in item:
                errors.append(f"missing_certainty_level:{section}:{index}")
            if "证据层级" not in item:
                errors.append(f"missing_evidence_tier_field:{section}:{index}")
            if not _item_has_evidence_tier_signal(item, contract):
                errors.append(f"missing_evidence_tier:{section}:{index}")
            if _paragraph_only_item(item, required_item_fields):
                errors.append(f"paragraph_only_item:{section}:{index}")

    for moderator in contract.get("moderator_variables") or []:
        if not isinstance(moderator, dict) or not moderator.get("required_in_final"):
            continue
        aliases = _record_aliases(moderator)
        occurrence_count = _alias_occurrence_count(value, aliases)
        moderator_id = str(moderator.get("id") or moderator.get("label") or "unknown")
        if occurrence_count < 2:
            errors.append(f"{FINAL_VALIDATION_MISSING_MODERATOR_RETENTION}:{moderator_id}")
        if moderator_id == "long_term_bjj_training" and not _match_any_alias(
            value,
            ["身体反馈系统", "身体反馈", "body feedback", "embodied feedback"],
        ):
            errors.append(f"{FINAL_VALIDATION_MISSING_MODERATOR_RETENTION}:{moderator_id}:missing_body_feedback_logic")

    for forbidden in contract.get("forbidden_content") or []:
        if not isinstance(forbidden, dict):
            continue
        if _match_any_alias(value, _record_aliases(forbidden)):
            errors.append(f"forbidden_content:{forbidden.get('id') or forbidden.get('label')}")

    errors.extend(validate_no_meta_execution_drift(value, contract))
    if _topic_anchor_count(value, contract) < _minimum_final_topic_anchor_count(contract):
        errors.append("topic_drift_or_generic_final")
    return _dedupe_error_list(errors)


def _markdown_section_body(text: str, heading: str) -> str:
    pattern = re.compile(rf"(?m)^#{{2,6}}\s*{re.escape(heading)}\s*$")
    match = pattern.search(text or "")
    if not match:
        return ""
    next_heading = re.search(r"(?m)^#{2,6}\s+", text[match.end():])
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end():end].strip()


def _numbered_markdown_items(section_body: str) -> list[str]:
    matches = list(re.finditer(r"(?m)^\s*\d+\.\s+", section_body or ""))
    items: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section_body)
        items.append(section_body[match.end():end].strip())
    return items


def _item_has_evidence_tier_signal(item_text: str, contract: dict[str, Any]) -> bool:
    if "证据层级" in (item_text or ""):
        return True
    allowed = contract.get("evidence_tiers", {}).get("allowed") or []
    for tier in allowed:
        aliases = EVIDENCE_TIER_ALIASES.get(str(tier), [str(tier)])
        if _match_any_alias(item_text, aliases):
            return True
    return False


def _paragraph_only_item(item_text: str, required_item_fields: list[str]) -> bool:
    if not (item_text or "").strip():
        return True
    return not any(label and label in item_text for label in required_item_fields)


def _alias_occurrence_count(text: str, aliases: list[str]) -> int:
    normalized = _normalize_for_match(text)
    counts = [
        normalized.count(_normalize_for_match(alias))
        for alias in aliases
        if _normalize_for_match(alias)
    ]
    return max(counts) if counts else 0


def _topic_anchor_count(text: str, contract: dict[str, Any]) -> int:
    anchors: list[str] = []
    anchors.extend(str(term) for term in contract.get("task_topic", {}).get("must_match_terms") or [])
    for group in ("key_variables", "moderator_variables", "required_dimensions"):
        for record in contract.get(group) or []:
            if isinstance(record, dict):
                anchors.append(str(record.get("label") or ""))
    return sum(1 for anchor in dict.fromkeys(anchors) if anchor and _match_any_alias(text, [anchor]))


def _minimum_final_topic_anchor_count(contract: dict[str, Any]) -> int:
    total = len(contract.get("task_topic", {}).get("must_match_terms") or [])
    total += len(contract.get("key_variables") or [])
    total += len(contract.get("moderator_variables") or [])
    total += len(contract.get("required_dimensions") or [])
    return max(4, min(8, total // 3))


def _dedupe_error_list(errors: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for error in errors:
        if error in seen:
            continue
        seen.add(error)
        deduped.append(error)
    return deduped


def contract_prompt_payload(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_id": contract.get("contract_id"),
        "contract_version": contract.get("contract_version"),
        "task_topic": contract.get("task_topic"),
        "user_output_contract": contract.get("user_output_contract"),
        "key_variables": contract.get("key_variables"),
        "moderator_variables": contract.get("moderator_variables"),
        "required_dimensions": contract.get("required_dimensions"),
        "evidence_tiers": contract.get("evidence_tiers"),
        "forbidden_content": contract.get("forbidden_content"),
        "claim_strength_policy": contract.get("claim_strength_policy"),
        "final_acceptance_checks": contract.get("final_acceptance_checks"),
        "contract_warnings": contract.get("contract_warnings"),
    }


def write_decision_context_contract_artifacts(
    contract: dict[str, Any],
    *,
    base_dir: str | Path,
) -> dict[str, str]:
    contract_dir = Path(base_dir) / "decision_context_contract"
    contract_dir.mkdir(parents=True, exist_ok=True)
    json_path = contract_dir / "decision_context_contract.json"
    md_path = contract_dir / "decision_context_contract.md"
    json_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_contract_markdown(contract), encoding="utf-8")
    return {
        "decision_context_contract_json_path": str(json_path),
        "decision_context_contract_md_path": str(md_path),
    }


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
