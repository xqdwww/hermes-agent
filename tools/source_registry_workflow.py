"""Deterministic source registry and full-text capture workflow helper.

This module intentionally does not search for sources, access the network,
retrieve full text, call an LLM, verify claims, or integrate with the
production Research/Decision runtime. It only validates and renders structured
source registry JSON as a Stage 1 to Stage 2 gate before Evidence Packet v2.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REQUIRED_FIELDS: tuple[str, ...] = (
    "source_id",
    "case_id",
    "title",
    "url_or_local_ref",
    "source_type",
    "publisher_or_author",
    "publication_date",
    "access_date",
    "as_of_relevance",
    "authority_tier",
    "independence",
    "potential_bias",
    "retrieval_status",
    "full_text_available",
    "full_text_accessed",
    "full_text_hash_or_excerpt_ref",
    "captured_excerpt_or_span",
    "captured_excerpt_summary",
    "source_limitations",
    "usable_for_claim_categories",
    "not_usable_for",
    "next_stage_verification_notes",
)

CRITICAL_NONEMPTY_FIELDS: tuple[str, ...] = (
    "source_id",
    "case_id",
    "title",
    "url_or_local_ref",
    "source_type",
    "retrieval_status",
    "source_limitations",
    "usable_for_claim_categories",
    "next_stage_verification_notes",
)

AUTHORITY_CATEGORIES: tuple[str, ...] = (
    "primary",
    "regulatory",
    "official",
    "peer_reviewed",
    "high_authority",
    "reputable_secondary",
    "industry_benchmark",
    "vendor",
    "consulting",
    "blog",
    "unknown",
)

HIGH_AUTHORITY_CATEGORIES: set[str] = {
    "primary",
    "regulatory",
    "official",
    "peer_reviewed",
    "high_authority",
}

RETRIEVAL_STATUSES: tuple[str, ...] = (
    "not_searched",
    "source_found",
    "source_accessible",
    "full_text_accessed",
    "paywalled_or_unavailable",
    "source_broken",
    "snippet_only",
    "search_result_snippet",
    "metadata_only",
    "doc_only_matched",
)

FULL_TEXT_COMPATIBLE_RETRIEVAL_STATUSES: set[str] = {
    "source_accessible",
    "full_text_accessed",
    "doc_only_matched",
}

SNIPPET_OR_METADATA_STATUSES: set[str] = {
    "snippet_only",
    "search_result_snippet",
    "metadata_only",
    "source_found",
}

DEFAULT_HIGH_RISK_CATEGORIES: tuple[str, ...] = (
    "financial_risk",
    "legal_regulatory",
    "medical_health",
    "statistic",
    "causal_claim",
    "prediction",
)

BIAS_REQUIRED_MARKERS: tuple[str, ...] = (
    "vendor",
    "blog",
    "consulting",
    "practitioner",
    "primary_vendor",
)

DATED_SOURCE_MARKERS: tuple[str, ...] = (
    "benchmark",
    "market",
    "report",
    "statistic",
    "survey",
    "data",
)

NONE_BIAS_VALUES: set[str] = {"", "none", "n/a", "na", "no", "no bias", "unknown"}
MAX_EXCERPT_CHARS = 1200
READY_FOR_EVIDENCE_PACKET_V2 = "READY_FOR_EVIDENCE_PACKET_V2"
READY_WITH_LIMITATIONS = "READY_WITH_LIMITATIONS"
HOLD_FOR_MORE_SOURCES = "HOLD_FOR_MORE_SOURCES"
BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class RegistryValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]
    source_count: int
    accepted_source_count: int
    high_authority_count: int
    full_text_accessed_count: int
    excerpt_or_span_capture_count: int
    bias_labeled_count: int
    missing_required_fields: list[str]
    fulltext_rule_violations: list[str]
    high_risk_rule_violations: list[str]
    readiness: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_registry_json(path: str | Path) -> dict[str, Any] | list[Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, (dict, list)):
        raise ValueError("Source registry JSON must be an object or list.")
    return data


def validate_source_registry(
    registry: dict[str, Any] | list[Any],
    *,
    high_risk_categories: list[str] | None = None,
) -> RegistryValidationResult:
    entries = _registry_entries(registry)
    errors: list[str] = []
    warnings: list[str] = []
    missing_required_fields: list[str] = []
    fulltext_rule_violations: list[str] = []
    high_risk_rule_violations: list[str] = []

    if entries is None:
        return RegistryValidationResult(
            ok=False,
            errors=["registry:expected_list_or_object_with_source_registry"],
            warnings=[],
            source_count=0,
            accepted_source_count=0,
            high_authority_count=0,
            full_text_accessed_count=0,
            excerpt_or_span_capture_count=0,
            bias_labeled_count=0,
            missing_required_fields=[],
            fulltext_rule_violations=[],
            high_risk_rule_violations=[],
            readiness=BLOCKED,
        )

    seen_source_ids: set[str] = set()
    seen_urls: dict[str, str] = {}
    high_risk_need_by_category = {item.lower() for item in (high_risk_categories or list(DEFAULT_HIGH_RISK_CATEGORIES))}
    high_risk_categories_seen: set[str] = set()
    high_risk_categories_with_authority: set[str] = set()

    for idx, entry in enumerate(entries):
        path = f"source_registry[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{path}:not_object")
            continue

        for field in REQUIRED_FIELDS:
            if field not in entry:
                message = f"{path}:missing_field:{field}"
                errors.append(message)
                missing_required_fields.append(message)

        for field in CRITICAL_NONEMPTY_FIELDS:
            if field in entry and _is_empty(entry.get(field)):
                errors.append(f"{path}:empty_field:{field}")

        source_id = _as_text(entry.get("source_id"))
        url_or_local_ref = _as_text(entry.get("url_or_local_ref"))
        source_type = _as_text(entry.get("source_type")).lower()
        authority_tier = _as_text(entry.get("authority_tier"))
        authority_category = _authority_category(authority_tier, source_type)
        retrieval_status = _as_text(entry.get("retrieval_status"))
        usable_categories = _as_text_list(entry.get("usable_for_claim_categories"))
        potential_bias = _as_text(entry.get("potential_bias"))
        captured_excerpt = _as_text(entry.get("captured_excerpt_or_span"))
        captured_summary = _as_text(entry.get("captured_excerpt_summary"))
        full_text_ref = _as_text(entry.get("full_text_hash_or_excerpt_ref"))

        if source_id:
            if source_id in seen_source_ids:
                errors.append(f"{path}:duplicate_source_id:{source_id}")
            seen_source_ids.add(source_id)

        if url_or_local_ref:
            previous = seen_urls.get(url_or_local_ref)
            if previous and previous != source_id:
                warnings.append(f"{path}:duplicate_url_or_local_ref:{url_or_local_ref}:also_used_by:{previous}")
            seen_urls[url_or_local_ref] = source_id or f"source_{idx}"

        if authority_tier and authority_category == "unknown" and authority_tier.lower() not in AUTHORITY_CATEGORIES:
            warnings.append(f"{path}:authority_tier_mapped_to_unknown:{authority_tier}")

        if retrieval_status and retrieval_status not in RETRIEVAL_STATUSES:
            errors.append(f"invalid_enum:{path}.retrieval_status:{retrieval_status}")

        if "full_text_available" in entry and not isinstance(entry.get("full_text_available"), bool):
            errors.append(f"{path}.full_text_available:expected_bool")
        if "full_text_accessed" in entry and not isinstance(entry.get("full_text_accessed"), bool):
            errors.append(f"{path}.full_text_accessed:expected_bool")

        if _requires_bias_label(source_type, authority_category):
            if potential_bias.lower() in NONE_BIAS_VALUES:
                errors.append(f"{path}:bias_required_for_source_type:{entry.get('source_type')}")

        if _requires_as_of_relevance(source_type):
            if _is_empty(entry.get("as_of_relevance")):
                errors.append(f"{path}:as_of_relevance_required_for_dated_source")

        if "not_usable_for" in entry and _is_empty(entry.get("not_usable_for")):
            warnings.append(f"{path}:not_usable_for_should_be_explicit")

        if len(captured_excerpt) > MAX_EXCERPT_CHARS:
            warnings.append(f"{path}:captured_excerpt_or_span_exceeds_{MAX_EXCERPT_CHARS}_chars")

        if entry.get("full_text_accessed") is True:
            fulltext_errors = _validate_full_text_accessed_rule(
                path=path,
                source=entry,
                retrieval_status=retrieval_status,
                captured_excerpt=captured_excerpt,
                captured_summary=captured_summary,
                full_text_ref=full_text_ref,
            )
            errors.extend(fulltext_errors)
            fulltext_rule_violations.extend(fulltext_errors)

        if entry.get("full_text_accessed") is False and entry.get("full_text_available") is True and not captured_excerpt and not full_text_ref:
            warnings.append(f"{path}:full_text_available_without_accessed_excerpt_or_ref")

        if _looks_snippet_only(entry) and entry.get("full_text_accessed") is True:
            message = f"{path}:snippet_or_metadata_source_cannot_be_full_text_accessed"
            errors.append(message)
            fulltext_rule_violations.append(message)

        for category in usable_categories:
            matched = _matching_high_risk_category(category, high_risk_need_by_category)
            if not matched:
                continue
            high_risk_categories_seen.add(matched)
            if authority_category in HIGH_AUTHORITY_CATEGORIES:
                high_risk_categories_with_authority.add(matched)

    for category in sorted(high_risk_categories_seen - high_risk_categories_with_authority):
        message = f"high_risk_category_without_authoritative_source:{category}"
        errors.append(message)
        high_risk_rule_violations.append(message)

    counts = _count_sources(entries)
    readiness = _readiness(
        errors=errors,
        warnings=warnings,
        accepted_source_count=counts["accepted_source_count"],
        full_text_accessed_count=counts["full_text_accessed_count"],
        high_authority_count=counts["high_authority_count"],
    )
    return RegistryValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        source_count=counts["source_count"],
        accepted_source_count=counts["accepted_source_count"],
        high_authority_count=counts["high_authority_count"],
        full_text_accessed_count=counts["full_text_accessed_count"],
        excerpt_or_span_capture_count=counts["excerpt_or_span_capture_count"],
        bias_labeled_count=counts["bias_labeled_count"],
        missing_required_fields=sorted(set(missing_required_fields)),
        fulltext_rule_violations=sorted(set(fulltext_rule_violations)),
        high_risk_rule_violations=sorted(set(high_risk_rule_violations)),
        readiness=readiness,
    )


def validate_fulltext_capture(registry: dict[str, Any] | list[Any]) -> RegistryValidationResult:
    return validate_source_registry(registry)


def validate_fulltext_claims(registry: dict[str, Any] | list[Any]) -> RegistryValidationResult:
    """Backward-compatible alias for the design phrase used before implementation."""

    return validate_fulltext_capture(registry)


def check_excerpt_span_completeness(registry: dict[str, Any] | list[Any]) -> RegistryValidationResult:
    return validate_source_registry(registry)


def normalize_source_registry(registry: dict[str, Any] | list[Any]) -> dict[str, Any]:
    entries = _registry_entries(registry)
    if entries is None:
        raise ValueError("Source registry JSON must be a list or object containing source_registry/sources/accepted_sources/entries.")
    normalized_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            normalized_entries.append({"value": entry})
            continue
        ordered: dict[str, Any] = {}
        for field in REQUIRED_FIELDS:
            if field in entry:
                ordered[field] = copy.deepcopy(entry[field])
        for key in sorted(entry):
            if key not in ordered:
                ordered[key] = copy.deepcopy(entry[key])
        normalized_entries.append(ordered)
    return {"source_registry": normalized_entries}


def score_source_registry(registry: dict[str, Any] | list[Any]) -> dict[str, Any]:
    entries = _registry_entries(registry) or []
    validation = validate_source_registry(registry)
    counts = _count_sources(entries)
    accepted = max(counts["accepted_source_count"], 1)
    unique_categories = _unique_usable_categories(entries)

    source_count_sufficiency = _score_count(counts["accepted_source_count"], good=6, minimum=3)
    authority_mix = _score_ratio(counts["high_authority_count"], accepted, floor=5.5)
    source_relevance_proxy = _score_ratio(counts["sources_with_usable_categories"], accepted, floor=5.0)
    recency_handling = _score_ratio(counts["sources_with_as_of_relevance"], accepted, floor=5.0)
    fulltext_capture_quality = _score_ratio(counts["excerpt_or_span_capture_count"], accepted, floor=4.0)
    bias_handling = _score_ratio(counts["bias_labeled_count"], accepted, floor=5.0)
    claim_category_coverage = min(10.0, 4.0 + min(len(unique_categories), 8) * 0.75)
    high_risk_source_control = 10.0 if not validation.high_risk_rule_violations else 4.0
    if validation.fulltext_rule_violations:
        fulltext_capture_quality = min(fulltext_capture_quality, 4.0)
    if validation.errors:
        next_stage_readiness = 3.0
    elif validation.warnings:
        next_stage_readiness = 8.0
    else:
        next_stage_readiness = 9.5

    score_values = {
        "source_count_sufficiency": source_count_sufficiency,
        "authority_mix": authority_mix,
        "source_relevance_proxy": source_relevance_proxy,
        "recency_handling": recency_handling,
        "fulltext_capture_quality": fulltext_capture_quality,
        "bias_handling": bias_handling,
        "claim_category_coverage": claim_category_coverage,
        "high_risk_source_control": high_risk_source_control,
        "next_stage_readiness": next_stage_readiness,
    }
    score_values["overall_score"] = round(sum(score_values.values()) / len(score_values), 2)
    return {key: round(value, 2) for key, value in score_values.items()}


def render_source_registry_review(
    registry: dict[str, Any] | list[Any],
    validation: RegistryValidationResult | None = None,
) -> str:
    validation = validation or validate_source_registry(registry)
    entries = _registry_entries(registry) or []
    scores = score_source_registry(registry)
    lines: list[str] = [
        "# Source Registry Workflow Review",
        "",
        "## Summary",
        "",
        f"- ok: {_bool_text(validation.ok)}",
        f"- readiness: {validation.readiness}",
        f"- source_count: {validation.source_count}",
        f"- accepted_source_count: {validation.accepted_source_count}",
        "",
        "## Validation Result",
        "",
        f"- errors_count: {len(validation.errors)}",
        f"- warnings_count: {len(validation.warnings)}",
        f"- missing_required_fields_count: {len(validation.missing_required_fields)}",
        "",
        "## Counts",
        "",
        f"- high_authority_count: {validation.high_authority_count}",
        f"- full_text_accessed_count: {validation.full_text_accessed_count}",
        f"- excerpt_or_span_capture_count: {validation.excerpt_or_span_capture_count}",
        f"- bias_labeled_count: {validation.bias_labeled_count}",
        "",
        "## Errors",
        "",
    ]
    lines.extend(_render_list(validation.errors))
    lines.extend(["", "## Warnings", ""])
    lines.extend(_render_list(validation.warnings))
    lines.extend(["", "## Source Quality Scores", ""])
    for key in sorted(scores):
        lines.append(f"- {key}: {scores[key]}")
    lines.extend(
        [
            "",
            "## Full-Text / Excerpt Capture Review",
            "",
            f"- fulltext_rule_violations: {_format_value(validation.fulltext_rule_violations)}",
            f"- max_excerpt_chars: {MAX_EXCERPT_CHARS}",
            "",
            "## High-Risk Source Control",
            "",
            f"- high_risk_rule_violations: {_format_value(validation.high_risk_rule_violations)}",
            "",
            "## Next-Stage Readiness",
            "",
            f"- readiness: {validation.readiness}",
            "- note: This review validates source registry quality only; it does not verify claim correctness.",
            "",
            "## Source-Level Notes",
            "",
        ]
    )
    if not entries:
        lines.append("- none")
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            lines.append(f"### source_{idx}")
            lines.append("")
            lines.append(f"- value: {_format_value(entry)}")
            lines.append("")
            continue
        source_id = _as_text(entry.get("source_id")) or f"source_{idx}"
        lines.append(f"### {source_id}")
        lines.append("")
        lines.append(f"- title: {_as_text(entry.get('title'))}")
        lines.append(f"- source_type: {_as_text(entry.get('source_type'))}")
        lines.append(f"- authority_tier: {_as_text(entry.get('authority_tier'))}")
        lines.append(f"- authority_category: {_authority_category(_as_text(entry.get('authority_tier')), _as_text(entry.get('source_type')).lower())}")
        lines.append(f"- full_text_accessed: {_bool_text(entry.get('full_text_accessed') is True)}")
        lines.append(f"- usable_for_claim_categories: {_format_value(_as_text_list(entry.get('usable_for_claim_categories')))}")
        lines.append(f"- source_limitations: {_format_value(entry.get('source_limitations'))}")
        lines.append(f"- not_usable_for: {_format_value(entry.get('not_usable_for'))}")
        lines.append(f"- next_stage_verification_notes: {_format_value(entry.get('next_stage_verification_notes'))}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_registry_review(registry: dict[str, Any] | list[Any], output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    registry_copy = copy.deepcopy(registry)
    validation = validate_source_registry(registry_copy)
    markdown = render_source_registry_review(registry_copy, validation)
    normalized = normalize_source_registry(registry_copy)
    scores = score_source_registry(registry_copy)

    review_path = out / "source_registry_review.md"
    report_path = out / "source_registry_review.json"
    normalized_path = out / "source_registry.normalized.json"
    review_path.write_text(markdown, encoding="utf-8")
    report_path.write_text(
        json.dumps(
            {
                "validation": validation.to_dict(),
                "scores": scores,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    normalized_path.write_text(json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "review_markdown": str(review_path),
        "review_json": str(report_path),
        "normalized_json": str(normalized_path),
        "validation": validation.to_dict(),
        "scores": scores,
    }


def _registry_entries(registry: Any) -> list[Any] | None:
    if isinstance(registry, list):
        return registry
    if not isinstance(registry, dict):
        return None
    if "source_id" in registry:
        return [registry]
    for key in ("source_registry", "sources", "accepted_sources", "entries"):
        value = registry.get(key)
        if isinstance(value, list):
            return value
    return None


def _count_sources(entries: list[Any]) -> dict[str, int]:
    source_count = len(entries)
    accepted_source_count = 0
    high_authority_count = 0
    full_text_accessed_count = 0
    excerpt_or_span_capture_count = 0
    bias_labeled_count = 0
    sources_with_usable_categories = 0
    sources_with_as_of_relevance = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        accepted_source_count += 1
        authority_category = _authority_category(_as_text(entry.get("authority_tier")), _as_text(entry.get("source_type")).lower())
        if authority_category in HIGH_AUTHORITY_CATEGORIES:
            high_authority_count += 1
        if entry.get("full_text_accessed") is True:
            full_text_accessed_count += 1
        if _as_text(entry.get("captured_excerpt_or_span")) or _as_text(entry.get("full_text_hash_or_excerpt_ref")):
            excerpt_or_span_capture_count += 1
        if _as_text(entry.get("potential_bias")).lower() not in NONE_BIAS_VALUES:
            bias_labeled_count += 1
        if _as_text_list(entry.get("usable_for_claim_categories")):
            sources_with_usable_categories += 1
        if _as_text(entry.get("as_of_relevance")):
            sources_with_as_of_relevance += 1
    return {
        "source_count": source_count,
        "accepted_source_count": accepted_source_count,
        "high_authority_count": high_authority_count,
        "full_text_accessed_count": full_text_accessed_count,
        "excerpt_or_span_capture_count": excerpt_or_span_capture_count,
        "bias_labeled_count": bias_labeled_count,
        "sources_with_usable_categories": sources_with_usable_categories,
        "sources_with_as_of_relevance": sources_with_as_of_relevance,
    }


def _validate_full_text_accessed_rule(
    *,
    path: str,
    source: dict[str, Any],
    retrieval_status: str,
    captured_excerpt: str,
    captured_summary: str,
    full_text_ref: str,
) -> list[str]:
    errors: list[str] = []
    if source.get("full_text_available") is not True:
        errors.append(f"{path}:full_text_accessed_requires_full_text_available")
    if retrieval_status not in FULL_TEXT_COMPATIBLE_RETRIEVAL_STATUSES:
        errors.append(f"{path}:full_text_accessed_invalid_retrieval_status:{retrieval_status}")
    if not captured_excerpt and not full_text_ref:
        errors.append(f"{path}:full_text_accessed_requires_excerpt_span_or_ref")
    if not captured_summary:
        errors.append(f"{path}:full_text_accessed_requires_captured_excerpt_summary")
    return errors


def _readiness(
    *,
    errors: list[str],
    warnings: list[str],
    accepted_source_count: int,
    full_text_accessed_count: int,
    high_authority_count: int,
) -> str:
    if errors:
        return BLOCKED
    if accepted_source_count < 3:
        return HOLD_FOR_MORE_SOURCES
    if warnings or full_text_accessed_count < accepted_source_count:
        return READY_WITH_LIMITATIONS
    if high_authority_count < 1:
        return READY_WITH_LIMITATIONS
    return READY_FOR_EVIDENCE_PACKET_V2


def _authority_category(authority_tier: str, source_type: str = "") -> str:
    text = f"{authority_tier} {source_type}".lower()
    if authority_tier.lower() in AUTHORITY_CATEGORIES:
        return authority_tier.lower()
    if "regulatory" in text or "supervisory" in text or "supervision" in text:
        return "regulatory"
    if "official" in text or "government" in text or "federal" in text:
        return "official"
    if "peer_reviewed" in text or "academic" in text or "journal" in text:
        return "peer_reviewed"
    if "primary" in text:
        return "primary" if "vendor" not in text else "vendor"
    if "tier_1" in text or "banking_standard" in text or "manual" in text:
        return "high_authority"
    if "industry_benchmark" in text or "benchmark" in text:
        return "industry_benchmark"
    if "consulting" in text or "practitioner" in text:
        return "consulting"
    if "vendor" in text:
        return "vendor"
    if "blog" in text:
        return "blog"
    if "secondary" in text or "framework" in text:
        return "reputable_secondary"
    return "unknown"


def _requires_bias_label(source_type: str, authority_category: str) -> bool:
    text = f"{source_type} {authority_category}".lower()
    return any(marker in text for marker in BIAS_REQUIRED_MARKERS)


def _requires_as_of_relevance(source_type: str) -> bool:
    text = source_type.lower()
    return any(marker in text for marker in DATED_SOURCE_MARKERS)


def _looks_snippet_only(source: dict[str, Any]) -> bool:
    retrieval_status = _as_text(source.get("retrieval_status")).lower()
    source_basis = " ".join(
        [
            retrieval_status,
            _as_text(source.get("source_type")).lower(),
            _as_text(source.get("captured_excerpt_or_span")).lower(),
            _as_text(source.get("next_stage_verification_notes")).lower(),
        ]
    )
    return retrieval_status in SNIPPET_OR_METADATA_STATUSES or "snippet" in source_basis or "metadata-only" in source_basis


def _matching_high_risk_category(category: str, high_risk_categories: set[str]) -> str | None:
    lowered = category.lower()
    for high_risk in high_risk_categories:
        if high_risk in lowered:
            return high_risk
    return None


def _unique_usable_categories(entries: list[Any]) -> set[str]:
    categories: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict):
            categories.update(_as_text_list(entry.get("usable_for_claim_categories")))
    return categories


def _score_ratio(numerator: int, denominator: int, *, floor: float) -> float:
    if denominator <= 0:
        return 0.0
    return floor + (10.0 - floor) * min(max(numerator / denominator, 0.0), 1.0)


def _score_count(count: int, *, good: int, minimum: int) -> float:
    if count <= 0:
        return 0.0
    if count < minimum:
        return round(3.0 + count, 2)
    return min(10.0, 6.0 + ((count - minimum) / max(good - minimum, 1)) * 4.0)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_as_text(item) for item in value if _as_text(item)]
    if isinstance(value, tuple):
        return [_as_text(item) for item in value if _as_text(item)]
    text = _as_text(value)
    return [text] if text else []


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return _bool_text(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[" + "; ".join(_format_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    if value is None:
        return "null"
    return str(value)


def _render_list(items: list[str]) -> list[str]:
    if not items:
        return ["- none"]
    return [f"- {item}" for item in items]


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic source registry workflow utility.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate a source registry JSON file.")
    validate.add_argument("--input", required=True, help="Path to source registry JSON.")

    review = subparsers.add_parser("review", help="Render a source registry workflow review.")
    review.add_argument("--input", required=True, help="Path to source registry JSON.")
    review.add_argument("--output", required=True, help="Path to output review markdown.")

    normalize = subparsers.add_parser("normalize", help="Normalize a source registry JSON file.")
    normalize.add_argument("--input", required=True, help="Path to source registry JSON.")
    normalize.add_argument("--output", required=True, help="Path to output normalized JSON.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        registry = load_registry_json(args.input)
        result = validate_source_registry(registry)
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.ok else 1

    if args.command == "review":
        registry = load_registry_json(args.input)
        result = validate_source_registry(registry)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_source_registry_review(registry, result), encoding="utf-8")
        sidecar = output.with_suffix(".json")
        sidecar.write_text(
            json.dumps({"validation": result.to_dict(), "scores": score_source_registry(registry)}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": result.ok, "readiness": result.readiness, "output": str(output), "sidecar": str(sidecar)}, sort_keys=True))
        return 0 if result.ok else 1

    if args.command == "normalize":
        registry = load_registry_json(args.input)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(normalize_source_registry(registry), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(output)}, sort_keys=True))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
