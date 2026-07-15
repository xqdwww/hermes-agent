"""Canonical contracts for Hermes research/decision task engines.

This module is intentionally deterministic. It owns the stage schema,
role/model bindings, fail-closed validation, and final report rendering for
the three heavy task modes. It does not change the default chat model.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ENGINE_RESEARCH = "RESEARCH"
ENGINE_DECISION = "DECISION"
ENGINE_RESEARCH_DECISION = "RESEARCH_DECISION"
ENGINE_MODES = {ENGINE_RESEARCH, ENGINE_DECISION, ENGINE_RESEARCH_DECISION}

PIPELINE_COMPLETE = "PIPELINE_COMPLETE"
PIPELINE_INCOMPLETE = "PIPELINE_INCOMPLETE"
PIPELINE_BLOCKED = "PIPELINE_BLOCKED"

GEMINI_HIGH = "Gemini 3.5 Flash (High)"
GEMINI_PRO_HIGH = "Gemini 3.1 Pro (High)"
DDGS_MODEL = "DDGS"
QWEN72B = "Qwen72B"
NEMOTRON120B = "Nemotron-120B"
LLAMA70B = "Llama70B"
GEMMA431B = "Gemma-4-31B"
R1_32B = "R1-32B"
GPT_OR_GEMINI_EXTERNAL = "GPT Bridge or Gemini/agy"
CONTROLLER_ACCEPTANCE = "controller_acceptance"
FINAL_CONTROLLER = "final_controller_report"

DIVERGENCE_ROLES = {
    "structure_mapper",
    "evidence_judge",
    "premise_auditor",
    "alternative_generator",
    "insight_harvester",
}

R1_ALLOWED_STAGES = {"L3_r1_synthesis", "convergence_report"}

FORBIDDEN_MARKDOWN_TOKENS = (
    "web_search",
    "api_call",
    "codex_exec",
    "delegate_task",
    "persona:",
    "R1 convergence",
)


@dataclass(frozen=True)
class StageSpec:
    stage_name: str
    owner: str
    model: str
    required_outputs: tuple[str, ...] = ("artifact_path",)


@dataclass
class StageRecord:
    stage_name: str
    owner: str
    model: str
    executor_model: str
    artifact_path: str
    created_in_current_run: bool
    legacy_contaminated: bool
    valid_for_pipeline: bool
    outputs: dict[str, str] = field(default_factory=dict)
    status: str = "planned"


RESEARCH_STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        "L1_gemini_search",
        GEMINI_HIGH,
        GEMINI_HIGH,
        ("source_candidates.json",),
    ),
    StageSpec(
        "L2_ddgs_supplement",
        "DDGS",
        DDGS_MODEL,
        ("ddgs_gap_sources.json",),
    ),
    StageSpec(
        "L2_5_codex_evidence_organizer",
        "Codex executor",
        "Codex",
        (
            "source_candidates.json",
            "ddgs_gap_sources.json",
            "evidence_runner_*.request.md",
            "evidence_runner_*.request.json",
            "sources.csv",
            "evidence.csv",
            "claims.md",
            "gaps.md",
        ),
    ),
    StageSpec("L3_r1_synthesis", R1_32B, R1_32B, ("r1_synthesis.md",)),
    StageSpec("L4_gemini_audit", GEMINI_PRO_HIGH, GEMINI_PRO_HIGH, ("gemini_audit_report.md",)),
    StageSpec(
        "L5_deepseek_acceptance",
        CONTROLLER_ACCEPTANCE,
        CONTROLLER_ACCEPTANCE,
        ("research_evidence_packet.md",),
    ),
)

DECISION_STAGES: tuple[StageSpec, ...] = (
    StageSpec("intelligence_layer", GEMINI_HIGH, GEMINI_HIGH, ("intelligence_layer_report.md",)),
    StageSpec("supplementary_search", "DDGS", DDGS_MODEL, ("parent_training_supplement.md",)),
    StageSpec("structure_mapper", QWEN72B, QWEN72B, ("structure_mapper.md",)),
    StageSpec("evidence_judge", NEMOTRON120B, NEMOTRON120B, ("evidence_judge.md",)),
    StageSpec("premise_auditor", LLAMA70B, LLAMA70B, ("premise_auditor.md",)),
    StageSpec("alternative_generator", GEMMA431B, GEMMA431B, ("alternative_generator.md",)),
    StageSpec("insight_harvester", GEMMA431B, GEMMA431B, ("insight_harvester.md",)),
    StageSpec("convergence_report", R1_32B, R1_32B, ("convergence_report.md",)),
    StageSpec("external_calibration", GPT_OR_GEMINI_EXTERNAL, GPT_OR_GEMINI_EXTERNAL, ("external_calibration.md",)),
    StageSpec("final_controller_report", "Controller", FINAL_CONTROLLER, ("final_decision_report.md",)),
)

CANONICAL_STAGES: dict[str, tuple[StageSpec, ...]] = {
    ENGINE_RESEARCH: RESEARCH_STAGES,
    ENGINE_DECISION: DECISION_STAGES,
    ENGINE_RESEARCH_DECISION: RESEARCH_STAGES + DECISION_STAGES,
}


def canonical_schema(mode: str) -> dict[str, Any]:
    """Return the machine-readable schema for a task engine mode."""
    normalized = normalize_mode(mode)
    return {
        "mode": normalized,
        "controller_model": QWEN72B,
        "ordinary_chat_model_replaced": False,
        "stages": [asdict(stage) for stage in CANONICAL_STAGES[normalized]],
        "output_policy": {
            "body_stage": "final_controller_report"
            if normalized != ENGINE_RESEARCH
            else "L5_deepseek_acceptance",
            "include_compact_pipeline_trace": True,
            "required_machine_markers": (
                "entered_engine_run_pipeline=true",
                f"pipeline_mode={normalized}",
                "pipeline_status=PIPELINE_COMPLETE",
                "pipeline_validation.valid=true",
                "delegation_used=false",
            ),
        },
    }


def build_engine_contract(mode: str, user_query: str) -> dict[str, Any]:
    """Build the clean 72B-first controller contract for one engine run."""
    schema = canonical_schema(mode)
    return {
        "contract_version": "hermes-task-engine/v1",
        "mode": schema["mode"],
        "user_query": user_query,
        "controller": {
            "model": QWEN72B,
            "scope": "task_engine_contract_and_execution_control_only",
            "must_not_replace_ordinary_chat": True,
        },
        "schema": schema,
        "fail_closed": {
            "missing_stage": PIPELINE_INCOMPLETE,
            "wrong_model": PIPELINE_BLOCKED,
            "missing_artifact": PIPELINE_BLOCKED,
            "legacy_contamination": PIPELINE_BLOCKED,
        },
    }


def build_dry_run_plan(mode: str, *, base_dir: str | Path | None = None) -> dict[str, Any]:
    """Create canonical StageRecord plans without invoking any executor."""
    normalized = normalize_mode(mode)
    base = Path(base_dir) if base_dir is not None else Path("<artifact_root>")
    stages = [
        asdict(make_stage_record(spec, base_dir=base, created=False, valid=False, status="planned"))
        for spec in CANONICAL_STAGES[normalized]
    ]
    return {
        "mode": normalized,
        "execution_mode": "dry-run",
        "model_calls_made": False,
        "stages": stages,
        "stage_count": len(stages),
    }


def make_stage_record(
    spec: StageSpec,
    *,
    base_dir: str | Path,
    created: bool,
    valid: bool,
    status: str = "ok",
    artifact_path: str | Path | None = None,
    outputs: dict[str, str] | None = None,
    legacy_contaminated: bool = False,
    executor_model: str | None = None,
) -> StageRecord:
    """Build a StageRecord from the canonical StageSpec binding."""
    base = Path(base_dir)
    resolved_outputs = outputs or planned_outputs(spec, base)
    artifact = artifact_path
    if artifact is None:
        artifact = _planned_artifact_path(spec, base, resolved_outputs)
    return StageRecord(
        stage_name=spec.stage_name,
        owner=spec.owner,
        model=spec.model,
        executor_model=executor_model or spec.model,
        artifact_path=str(artifact),
        created_in_current_run=created,
        legacy_contaminated=legacy_contaminated,
        valid_for_pipeline=valid,
        outputs=resolved_outputs,
        status=status,
    )


def planned_outputs(spec: StageSpec, base_dir: str | Path) -> dict[str, str]:
    """Return deterministic artifact filenames expected for a stage."""
    base = Path(base_dir)
    stage_dir = base / spec.stage_name
    outputs: dict[str, str] = {}
    for required in spec.required_outputs:
        if required == "artifact_path":
            continue
        if "*" in required:
            filename = required.replace("*", "001")
        else:
            filename = required
        outputs[required] = str(stage_dir / filename)
    if not outputs:
        outputs["report.md"] = str(stage_dir / "report.md")
    return outputs


def normalize_mode(mode: str) -> str:
    value = (mode or "").strip().upper().replace("-", "_")
    if value not in ENGINE_MODES:
        raise ValueError(f"Unknown task engine mode: {mode!r}")
    return value


# ---------------------------------------------------------------------------
# Explicit heavy-mode declaration detection with negation/code-block filtering
# ---------------------------------------------------------------------------

# Route source constant — emitted in diagnostics when a raw user prompt
# is classified as an explicit affirmative mode declaration.
ROUTE_SOURCE_RAW_USER_EXPLICIT = "raw_user_prompt_explicit_declaration"

# Regex patterns for tokens that suggest a research or decision intent.
# These are checked against the CLEANED text (after stripping fences).
_RESEARCH_TOKENS = ("研究", "research", "最新进展", "latest research", "evidence")
_DECISION_TOKENS = ("决策", "是否", "要不要", "到什么程度", "decision", "should i")

# Negation prefixes — any line beginning with one of these (after stripping
# leading whitespace) is excluded from declaration matching.
_NEGATION_PREFIXES = (
    "不是", "no ", "not ", "don't", "dont", "doesn't", "isn't",
    "aren't", "wasn't", "weren't", "haven't", "hasn't", "hadn't",
    "won't", "wouldn't", "can't", "cannot", "couldn't", "shouldn't",
    "禁止", "不要", "别",
)

# Meta-discussion patterns — when the user is talking ABOUT the detection
# mechanism rather than making a declaration.  These are checked against
# the original (non-cleaned) text.
_META_DISCUSSION_PATTERNS = (
    "识别 bug", "detection bug",
    "识别错误", "false positive",
    "误判为", "mistakenly detected",
    "修复.*RESEARCH.*DECISION.*识别",
    "修复.*DECISION.*RESEARCH.*识别",
    "fix.*research.*decision.*detect",
    "fix.*decision.*research.*detect",
)

# Error/crash context patterns — when a mode keyword appears near an
# error indicator, it's likely copied output rather than a declaration.
# These are checked as contextual clues around mode matches.
_ERROR_CONTEXT_PATTERNS = (
    r"\b(error|traceback|exception|crash|fail|报错|错误|异常|崩溃)\b",
    r"\b(task_engine_runner\s+RESEARCH|task_engine_runner\s+DECISION|task_engine_runner\s+RESEARCH_DECISION)",
    r"(most recent call last|Traceback)",
)

# Known mode field names appearing in log/diagnostic output.
# When one of these fields is assigned a mode-token value via "=" or ":",
# the value is a log artifact, not a user declaration.
_KNOWN_MODE_FIELDS = (
    "mode", "task_mode", "detected_mode", "selected_mode", "route_mode"
)

# Lead-in phrases that introduce a plaintext log or code section.
# Content following these phrases that exhibits log/code structure is
# excluded from explicit-declaration detection.
_LEADIN_PHRASES = (
    "下面是一段错误日志",
    "以下是错误日志",
    "下面是一段日志",
    "以下是日志",
    "下面是一段代码",
    "以下是代码",
    "错误输出",
    "诊断信息",
    "error log",
    "error logs",
    "traceback",
    "diagnostic output",
)


def _check_key_value_context(original: str) -> set[str]:
    """Check the *original* text for known field=value / field: value
    assignments whose value side contains one of the mode tokens.

    Returns a set of lowercased token texts that should be filtered.
    """
    filtered: set[str] = set()
    if not original:
        return filtered
    for field in _KNOWN_MODE_FIELDS:
        for token in _RESEARCH_TOKENS + _DECISION_TOKENS:
            token_lower = token.lower()
            # Pattern: field ⟦spaces⟧ = or : ⟦spaces⟧ … token (case-insensitive)
            pattern = re.compile(
                rf'{re.escape(field)}\s*[=:]\s*[^\n]*{re.escape(token_lower)}',
                re.IGNORECASE,
            )
            if pattern.search(original):
                filtered.add(token_lower)
    return filtered


def _looks_like_log_or_code_line(line: str) -> bool:
    """Heuristic: does *line* look like log output or code source?"""
    stripped = line.strip()
    if not stripped:
        return False
    # key=value (ASCII identifier key)
    if re.match(r'^[a-zA-Z_][a-zA-Z0-9_.-]*\s*=\s*\S', stripped):
        return True
    # key: value (ASCII identifier key, colon, space, then value)
    if re.match(r'^[a-zA-Z_][a-zA-Z0-9_.-]*\s*:\s+\S', stripped):
        return True
    # Method/function call (identifier dotted chain with parens)
    if re.match(r'^[a-zA-Z_][\w.]*(?:\.\w+)*\(', stripped):
        return True
    # Indented line (2+ leading spaces – code body, config, data)
    leading_spaces = len(line) - len(line.lstrip())
    if leading_spaces >= 2:
        return True
    # Function / class / method definition
    if re.match(r'^(?:def |class |async def |sub |func )', stripped):
        return True
    # Status / all-caps constant
    if re.match(r'^[A-Z][A-Z0-9_]{2,}(?:\s|:|$)', stripped):
        return True
    # File path (contains /)
    if '/' in stripped and re.match(r'^[^\s]*/', stripped):
        return True
    # Stack-trace indicator
    if re.match(r'^File ".*", line \d+', stripped):
        return True
    if 'Traceback' in stripped:
        return True
    # Command / shell prompt
    if re.match(r'^[\$#>]\s', stripped) or re.match(r'^[\w@]+:.*\$', stripped):
        return True
    return False


def _check_plaintext_log_or_code_context(original: str) -> set[str]:
    """Check the *original* text for lead-in phrases followed by log/code
    content, and collect any mode tokens appearing inside that content.

    Returns a set of lowercased token texts that should be filtered.
    """
    filtered: set[str] = set()
    if not original:
        return filtered
    lines = original.split('\n')

    for i, line in enumerate(lines):
        line_lower = line.strip().lower()
        # Check for any lead-in phrase in this line
        has_leadin = False
        for phrase in _LEADIN_PHRASES:
            phrase_lower = phrase.lower()
            if phrase_lower in line_lower:
                has_leadin = True
                break
        if not has_leadin:
            continue

        # Scan forward from the NEXT line for log/code content.
        j = i + 1
        while j < len(lines):
            curr = lines[j]
            if not curr.strip():
                # Blank line — stay in context per requirement.
                j += 1
                continue
            if _looks_like_log_or_code_line(curr):
                # Still in log/code context — check for mode tokens.
                curr_lower = curr.lower()
                for token in _RESEARCH_TOKENS + _DECISION_TOKENS:
                    token_lower = token.lower()
                    if token_lower in curr_lower:
                        filtered.add(token_lower)
                j += 1
            else:
                # A non-blank, non-log line = natural language → exit.
                break

    return filtered


def _strip_markdown_fences(text: str) -> tuple[str, list[dict]]:
    """Strip Markdown fenced code blocks, inline code, and block quotes.

    Returns (cleaned_text, removal_records) where each removal_record
    describes what was removed (type, original_text, approx_start).
    """
    removals: list[dict] = []
    lines = text.split("\n")
    cleaned: list[str] = []
    # Fenced code block state
    in_fence = False
    fence_start = 0
    fence_body: list[str] = []
    fence_lang = ""
    # Block quote state (lines starting with >)
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        # --- Fenced code blocks (``` ... ```) ---
        if raw_line.lstrip().startswith("```"):
            if not in_fence:
                in_fence = True
                fence_start = i
                fence_lang = raw_line.strip().lstrip("```").strip()
                fence_body = []
                i += 1
                continue
            else:
                # Closing fence
                in_fence = False
                removals.append({
                    "type": "fenced_code_block",
                    "language": fence_lang,
                    "start_line": fence_start,
                    "end_line": i,
                    "body_snippet": "\n".join(fence_body)[:200],
                })
                i += 1
                continue
        if in_fence:
            fence_body.append(raw_line)
            i += 1
            continue
        # --- Block quotes (lines starting with >) ---
        if raw_line.lstrip().startswith(">"):
            # Include the > line itself and any continuation lines
            quote_lines = [raw_line]
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                if next_line.lstrip().startswith(">") or next_line.strip() == "":
                    quote_lines.append(next_line)
                    j += 1
                else:
                    break
            removals.append({
                "type": "block_quote",
                "start_line": i,
                "end_line": j - 1,
                "body_snippet": "\n".join(quote_lines)[:200],
            })
            i = j
            continue
        cleaned.append(raw_line)
        i += 1

    cleaned_text = "\n".join(cleaned)
    # Strip inline code (backtick-surrounded text)
    cleaned_text = _strip_inline_code(cleaned_text, removals)
    return cleaned_text, removals


def _strip_inline_code(text: str, removals: list[dict]) -> str:
    """Replace inline code spans (single backticks) with spaces.

    Handles single backtick inline code only. Returns modified text
    and appends removal records to *removals*.
    """
    import re
    # Match backtick-quoted inline code, including double-backtick escapes
    pattern = re.compile(r"(?<!\\)`{1,2}([^`]+?)`{1,2}")
    result = []
    last_end = 0
    for m in pattern.finditer(text):
        start, end = m.start(), m.end()
        result.append(text[last_end:start])
        removals.append({
            "type": "inline_code",
            "approx_char_start": start,
            "approx_char_end": end,
            "body_snippet": m.group(1)[:200],
        })
        # Replace the inline code span with spaces to preserve line offsets
        result.append(" " * (end - start))
        last_end = end
    result.append(text[last_end:])
    return "".join(result)


def _check_error_context(vicinity: str) -> bool:
    """Check if *vicinity* (a window of text) contains an error/crash indicator
    near a mode keyword.  Returns True when the context looks like copied
    error output rather than a user declaration.
    """
    for ep in _ERROR_CONTEXT_PATTERNS:
        if re.search(ep, vicinity, re.IGNORECASE):
            return True
    return False


def _has_negation_near_match(text: str, match_word: str, match_start: int) -> bool:
    """Check if a negation prefix appears close before *match_word*.

    Scans backwards from *match_start* through the preceding ~80 chars
    (a reasonable sentence window) for any negation prefix.  This catches
    patterns like "不是 RESEARCH", "这不是 RESEARCH", "not a DECISION task",
    or "don't run DECISION on this".

    The prefix must be within the last 2 words immediately before the match
    word to avoid catching negations from a different clause.
    """
    if match_start == 0:
        return False
    # Look backwards up to 80 characters (sentence-length window)
    window_start = max(0, match_start - 80)
    before = text[window_start:match_start]
    before_stripped = before.strip()
    if not before_stripped:
        return False
    before_lower = before_stripped.lower()

    # Get the last 2 words before the match
    words = before_lower.split()
    last_words = words[-2:] if len(words) >= 2 else words

    last_2_text = " ".join(last_words)

    for prefix in _NEGATION_PREFIXES:
        pl = prefix.lower().rstrip()
        idx = last_2_text.find(pl)
        if idx == -1:
            continue
        # Word-boundary: the character before the prefix (if any) should
        # not be a standard ASCII letter/digit (to avoid matching inside
        # words like "cannot" for "not").  Skip this check for CJK
        # characters (which are also alnum in Python) because they commonly
        # precede negation in Chinese phrases like "这不是" (this is not).
        if idx > 0:
            prev_char = last_2_text[idx - 1]
            if prev_char.isascii() and prev_char.isalnum():
                continue
        return True

    return False


def _find_match_in_clean_text(
    cleaned: str,
    tokens: tuple[str, ...],
) -> list[dict]:
    """Find token matches in cleaned text with position and negation info.

    Returns a list of match records, each with:
      - token: the matched token
      - matched_text: the original text fragment that fulfilled the match
      - char_start: starting character index in cleaned text
      - char_end: ending character index
      - negated: True if a negation prefix precedes this match
    """
    results: list[dict] = []
    lowered = cleaned.lower()
    for token in tokens:
        token_lower = token.lower()
        idx = 0
        while True:
            idx = lowered.find(token_lower, idx)
            if idx == -1:
                break
            negated = _has_negation_near_match(cleaned, token_lower, idx)
            results.append({
                "token": token,
                "matched_text": cleaned[idx:idx + len(token)],
                "char_start": idx,
                "char_end": idx + len(token),
                "negated": negated,
                "matched_via": "substring",
            })
            idx += len(token)
    return results


def check_explicit_heavy_mode_declaration(
    text: str,
) -> tuple[str | None, dict]:
    """Check if the user's text is an explicit, affirmative heavy-mode declaration.

    Returns (detected_mode, diagnostic_dict) where:
      - detected_mode: ``ENGINE_RESEARCH``, ``ENGINE_DECISION``, ``ENGINE_RESEARCH_DECISION``,
        or ``None`` if no valid declaration found.
      - diagnostic_dict: rich diagnostic info for logging.

    Filtering rules (requirements A, B, C, D):
      - Markdown fenced code blocks (`````...`````) are stripped.
      - Inline code (`...`) is replaced with spaces.
      - Markdown block quotes (> ...) are stripped.
      - Lines beginning with negation prefixes are excluded from consideration.
      - A negation prefix within 80 characters before a match excludes it.
      - Only top-level affirmative matches (no negation, not inside filtered
        structures) activate a mode.

    Route source: ``raw_user_prompt_explicit_declaration`` when a mode is
    positively detected.
    """
    diagnostic: dict = {
        "route_source": None,
        "detected_mode": None,
        "all_matches": [],
        "active_matches": [],
        "filtered_by_negation": [],
        "filtered_by_fence": [],
        "filtered_by_blockquote": [],
        "filtered_by_inline_code": [],
        "filtered_by_key_value_context": [],
        "filtered_by_plaintext_log_or_code_context": [],
        "non_negated_research": False,
        "non_negated_decision": False,
    }

    text = text or ""
    original = text

    # Phase 1: Strip markdown fences, inline code, block quotes
    cleaned, removals = _strip_markdown_fences(text)

    # Classify removals by type for diagnostic
    fence_removals = [r for r in removals if r["type"] == "fenced_code_block"]
    quote_removals = [r for r in removals if r["type"] == "block_quote"]
    inline_code_removals = [r for r in removals if r["type"] == "inline_code"]

    has_fences = len(fence_removals) > 0
    has_quotes = len(quote_removals) > 0
    has_inline_code = len(inline_code_removals) > 0

    # Record filtering for diagnostics
    for r in fence_removals:
        snippet = r.get("body_snippet", "")[:120]
        diagnostic["filtered_by_fence"].append({
            "language": r.get("language", ""),
            "snippet": snippet,
        })
    for r in quote_removals:
        snippet = r.get("body_snippet", "")[:120]
        diagnostic["filtered_by_blockquote"].append({"snippet": snippet})
    for r in inline_code_removals:
        snippet = r.get("body_snippet", "")[:120]
        diagnostic["filtered_by_inline_code"].append({"snippet": snippet})

    # Phase 2: Find all matches in cleaned (non-stripped) text
    research_matches = _find_match_in_clean_text(cleaned, _RESEARCH_TOKENS)
    decision_matches = _find_match_in_clean_text(cleaned, _DECISION_TOKENS)
    all_matches = research_matches + decision_matches

    diagnostic["all_matches"] = all_matches

    # Phase 3: Filter out negated matches
    active_research = any(not m["negated"] for m in research_matches)
    active_decision = any(not m["negated"] for m in decision_matches)
    negated_research = [m for m in research_matches if m["negated"]]
    negated_decision = [m for m in decision_matches if m["negated"]]

    diagnostic["non_negated_research"] = active_research
    diagnostic["non_negated_decision"] = active_decision
    diagnostic["filtered_by_negation"] = negated_research + negated_decision

    active_matches = [
        m for m in all_matches if not m["negated"]
    ]
    diagnostic["active_matches"] = active_matches

    # Phase 4: Check line-level negation
    if not active_research and not active_decision:
        return None, diagnostic

    # Phase 4.5: Meta-discussion filter — if the user is talking ABOUT
    # the detection mechanism (not making a declaration), skip.
    diagnostic["meta_discussion_matched"] = False
    for pattern in _META_DISCUSSION_PATTERNS:
        if re.search(pattern, original, re.IGNORECASE):
            diagnostic["meta_discussion_matched"] = True
            diagnostic["meta_discussion_pattern"] = pattern
            return None, diagnostic

    # Phase 4.6: Key-value context filter — log/diagnostic field assignments
    # like "mode=RESEARCH" or "task_mode: DECISION" are not declarations.
    # Runs BEFORE the error-context filter so that legitimate log-field
    # values are caught before Phase 4.8 can short-circuit on "error log".
    diagnostic["filtered_by_key_value_context"] = []
    kv_filtered_set = _check_key_value_context(original)
    if kv_filtered_set:
        for m in all_matches:
            if m["token"].lower() in kv_filtered_set and not m["negated"]:
                diagnostic["filtered_by_key_value_context"].append(m)
        if diagnostic["filtered_by_key_value_context"]:
            kv_filtered_tokens = {
                m["token"].lower()
                for m in diagnostic["filtered_by_key_value_context"]
            }
            active_research = any(
                not m["negated"] and m["token"].lower() not in kv_filtered_tokens
                for m in research_matches
            )
            active_decision = any(
                not m["negated"] and m["token"].lower() not in kv_filtered_tokens
                for m in decision_matches
            )
            active_matches = [
                m for m in all_matches
                if not m["negated"]
                and m not in diagnostic["filtered_by_key_value_context"]
            ]
            diagnostic["active_matches"] = active_matches
            diagnostic["non_negated_research"] = active_research
            diagnostic["non_negated_decision"] = active_decision

    if not active_research and not active_decision:
        return None, diagnostic

    # Phase 4.7: Plaintext log/code context filter — content following
    # lead-in phrases (e.g. "error log", "以下是错误日志") that exhibits
    # log or code structure is not a user declaration.
    diagnostic["filtered_by_plaintext_log_or_code_context"] = []
    lc_filtered_set = _check_plaintext_log_or_code_context(original)
    if lc_filtered_set:
        for m in all_matches:
            if m["token"].lower() in lc_filtered_set and not m["negated"]:
                if m not in diagnostic["filtered_by_key_value_context"]:
                    diagnostic["filtered_by_plaintext_log_or_code_context"].append(m)
        if diagnostic["filtered_by_plaintext_log_or_code_context"]:
            lc_filtered_tokens = {
                m["token"].lower()
                for m in diagnostic["filtered_by_plaintext_log_or_code_context"]
            }
            all_context_filtered_tokens = kv_filtered_set | lc_filtered_set
            active_research = any(
                not m["negated"] and m["token"].lower() not in all_context_filtered_tokens
                for m in research_matches
            )
            active_decision = any(
                not m["negated"] and m["token"].lower() not in all_context_filtered_tokens
                for m in decision_matches
            )
            active_matches = [
                m for m in all_matches
                if not m["negated"]
                and m not in diagnostic["filtered_by_key_value_context"]
                and m not in diagnostic["filtered_by_plaintext_log_or_code_context"]
            ]
            diagnostic["active_matches"] = active_matches
            diagnostic["non_negated_research"] = active_research
            diagnostic["non_negated_decision"] = active_decision

    if not active_research and not active_decision:
        return None, diagnostic

    # Phase 4.8: Error-context filter — if a mode keyword appears near
    # an error/crash indicator, the text is likely copied output rather
    # than a declaration.  Check only remaining active matches so that
    # lead-in phrases like "error log" do not short-circuit Phase 4.6/4.7.
    diagnostic["error_context_matched"] = False
    orig_lower = original.lower()
    has_error_keyword_near_research = False
    for token in _RESEARCH_TOKENS + _DECISION_TOKENS:
        tl = token.lower()
        kv_covered = tl in kv_filtered_set
        lc_covered = tl in lc_filtered_set
        if kv_covered or lc_covered:
            continue
        tidx = orig_lower.find(tl)
        if tidx == -1:
            continue
        m_start = max(0, tidx - 80)
        m_end = min(len(original), tidx + len(tl) + 80)
        vicinity = original[m_start:m_end]
        if _check_error_context(vicinity):
            has_error_keyword_near_research = True
            break
    if has_error_keyword_near_research:
        diagnostic["error_context_matched"] = True
        return None, diagnostic

    # Phase 5: Determine mode from non-negated matches
    # Check for sentence-level negation patterns in original text
    # If the user wrote "不是 RESEARCH" the negation filter already caught it.
    lowered_original = original.lower()

    # Also check if the MATCHED keywords appear only inside structures that
    # were filtered out (fences, quotes, inline code).
    # If ALL matches are inside filtered structures, don't activate.
    match_tokens_in_original_only = False
    non_filtered_research = any(
        not (m["negated"])
        for m in research_matches
    )
    non_filtered_decision = any(
        not (m["negated"])
        for m in decision_matches
    )

    # If there are non-negated matches in the cleaned text that weren't
    # inside fences/quotes/inline code, they are real top-level declarations.
    if non_filtered_research and non_filtered_decision:
        mode = ENGINE_RESEARCH_DECISION
    elif non_filtered_research:
        mode = ENGINE_RESEARCH
    elif non_filtered_decision:
        mode = ENGINE_DECISION
    else:
        mode = None

    if mode is not None:
        diagnostic["detected_mode"] = mode
        diagnostic["route_source"] = ROUTE_SOURCE_RAW_USER_EXPLICIT
        diagnostic["filtered_fences_applied"] = has_fences
        diagnostic["filtered_blockquotes_applied"] = has_quotes
        diagnostic["filtered_inline_code_applied"] = has_inline_code
        diagnostic["negation_filtered"] = len(negated_research) + len(negated_decision) > 0
        diagnostic["clean_text_used_for_matching"] = cleaned[:500]

    return mode, diagnostic


def detect_task_engine_mode(text: str) -> str | None:
    """Classify only the three heavy task modes; ordinary chat returns None.

    .. deprecated::
        Prefer ``check_explicit_heavy_mode_declaration()`` which returns
        both the mode and a diagnostic dict with negation/code-block
        filtering details.

    This function is kept for backward compatibility.  It delegates to the
    new checker and discards the diagnostic dict.
    """
    mode, _diagnostic = check_explicit_heavy_mode_declaration(text)
    return mode


def validate_pipeline(mode: str, run: dict[str, Any], *, base_dir: str | Path | None = None) -> dict[str, Any]:
    """Validate a completed run against the canonical contract.

    Validation is fail-closed: any absent stage, wrong binding, missing artifact,
    legacy contamination marker, or invalid handoff output blocks final reporting.
    """
    normalized = normalize_mode(mode)
    specs = CANONICAL_STAGES[normalized]
    base = Path(base_dir) if base_dir is not None else None
    stage_records = _stage_records(run)
    by_name = {record.get("stage_name"): record for record in stage_records}

    errors: list[str] = []
    warnings: list[str] = []

    if len(by_name) != len(stage_records):
        errors.append("duplicate_stage_name")

    expected_names = [spec.stage_name for spec in specs]
    actual_names = [record.get("stage_name") for record in stage_records]
    if actual_names != expected_names:
        errors.append(
            "stage_order_mismatch:"
            + json.dumps({"expected": expected_names, "actual": actual_names}, ensure_ascii=False)
        )

    for spec in specs:
        record = by_name.get(spec.stage_name)
        if not record:
            errors.append(f"missing_stage:{spec.stage_name}")
            continue

        _require_equal(errors, spec.stage_name, "owner", record.get("owner"), spec.owner)
        _require_equal(errors, spec.stage_name, "model", record.get("model"), spec.model)

        if record.get("created_in_current_run") is not True:
            errors.append(f"{spec.stage_name}:created_in_current_run_not_true")
        if record.get("legacy_contaminated") is not False:
            errors.append(f"{spec.stage_name}:legacy_contaminated_not_false")
        if record.get("valid_for_pipeline") is not True:
            errors.append(f"{spec.stage_name}:valid_for_pipeline_not_true")

        model = str(record.get("model") or "")
        if "R1-32B" in model and spec.stage_name not in R1_ALLOWED_STAGES:
            errors.append(f"{spec.stage_name}:r1_forbidden_here")
        if spec.stage_name == "external_calibration" and (
            "Nemotron" in model or "Controller" in model
        ):
            errors.append("external_calibration:forbidden_model")

        artifact_path = record.get("artifact_path")
        if not artifact_path:
            errors.append(f"{spec.stage_name}:missing_artifact_path")
            continue
        artifact = _resolve_path(artifact_path, base)
        if not artifact.exists():
            errors.append(f"{spec.stage_name}:artifact_path_not_found:{artifact}")
        elif spec.stage_name == "L5_deepseek_acceptance":
            _validate_l5_acceptance_artifact(errors, artifact)

        for required in spec.required_outputs:
            if required == "artifact_path":
                continue
            if not _required_output_exists(record, required, base):
                errors.append(f"{spec.stage_name}:required_output_missing:{required}")

    if normalized in {ENGINE_DECISION, ENGINE_RESEARCH_DECISION}:
        _validate_divergence_models(errors, by_name)

    status = PIPELINE_COMPLETE if not errors else PIPELINE_BLOCKED
    return {
        "valid": not errors,
        "pipeline_status": status,
        "errors": errors,
        "warnings": warnings,
        "stage_count": len(stage_records),
        "expected_stage_count": len(specs),
        "divergence_unique_model_count": _divergence_unique_model_count(by_name),
    }


def render_final_markdown(
    mode: str,
    run: dict[str, Any],
    validation: dict[str, Any] | None = None,
    *,
    base_dir: str | Path | None = None,
) -> str:
    """Render only the accepted final controller report as user-visible body."""
    normalized = normalize_mode(mode)
    validation = validation or validate_pipeline(normalized, run, base_dir=base_dir)
    markers = [
        "entered_engine_run_pipeline=true",
        f"pipeline_mode={normalized}",
        f"pipeline_status={validation['pipeline_status']}",
        f"pipeline_validation.valid={str(bool(validation['valid'])).lower()}",
        "delegation_used=false",
    ]

    if not validation["valid"]:
        return "\n".join(
            markers
            + [
                "",
                validation["pipeline_status"],
                "",
                "Pipeline validation failed closed. No final report was produced.",
                "",
                "Compact Pipeline Trace:",
                _compact_trace(run),
                "",
                "Validation Errors:",
                "\n".join(f"- {error}" for error in validation["errors"]),
            ]
        )

    final_stage = "final_controller_report" if normalized != ENGINE_RESEARCH else "L5_deepseek_acceptance"
    final_text = _read_stage_artifact_text(run, final_stage, base_dir=base_dir)
    if not final_text.strip():
        blocked = dict(validation)
        blocked["valid"] = False
        blocked["pipeline_status"] = PIPELINE_BLOCKED
        blocked["errors"] = [*validation.get("errors", []), f"{final_stage}:empty_final_artifact"]
        return render_final_markdown(normalized, run, blocked, base_dir=base_dir)

    leaked = [token for token in FORBIDDEN_MARKDOWN_TOKENS if token in final_text]
    if leaked:
        blocked = dict(validation)
        blocked["valid"] = False
        blocked["pipeline_status"] = PIPELINE_BLOCKED
        blocked["errors"] = [*validation.get("errors", []), f"final_markdown_forbidden_tokens:{','.join(leaked)}"]
        return render_final_markdown(normalized, run, blocked, base_dir=base_dir)

    return "\n".join(
        markers
        + [
            "",
            final_text.strip(),
            "",
            "Compact Pipeline Trace:",
            _compact_trace(run),
        ]
    )


def _stage_records(run: dict[str, Any]) -> list[dict[str, Any]]:
    stages = run.get("stages")
    if isinstance(stages, list):
        return [stage for stage in stages if isinstance(stage, dict)]
    if isinstance(stages, dict):
        return [stage for stage in stages.values() if isinstance(stage, dict)]
    return []


def _planned_artifact_path(spec: StageSpec, base_dir: Path, outputs: dict[str, str]) -> Path:
    stage_dir = base_dir / spec.stage_name
    if spec.stage_name == "L2_5_codex_evidence_organizer":
        return stage_dir
    if spec.required_outputs == ("artifact_path",):
        return stage_dir / "report.md"
    first_required = spec.required_outputs[0]
    return Path(outputs.get(first_required, stage_dir / first_required))


def _require_equal(errors: list[str], stage_name: str, field: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        errors.append(f"{stage_name}:{field}_mismatch:{actual!r}!={expected!r}")


def _resolve_path(value: str | Path, base_dir: Path | None) -> Path:
    path = Path(value)
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path


def _artifact_dir(record: dict[str, Any], base_dir: Path | None) -> Path | None:
    artifact_path = record.get("artifact_path")
    if not artifact_path:
        return None
    artifact = _resolve_path(artifact_path, base_dir)
    return artifact if artifact.is_dir() else artifact.parent


def _required_output_exists(record: dict[str, Any], required: str, base_dir: Path | None) -> bool:
    outputs = record.get("outputs")
    candidates: list[Path] = []
    if isinstance(outputs, dict):
        value = outputs.get(required)
        if isinstance(value, str):
            candidates.append(_resolve_path(value, base_dir))
        for value in outputs.values():
            if isinstance(value, str) and fnmatch.fnmatch(Path(value).name, required):
                candidates.append(_resolve_path(value, base_dir))
    elif isinstance(outputs, list):
        for value in outputs:
            if isinstance(value, str) and fnmatch.fnmatch(Path(value).name, required):
                candidates.append(_resolve_path(value, base_dir))

    stage_dir = _artifact_dir(record, base_dir)
    if stage_dir is not None:
        if any(ch in required for ch in "*?[]"):
            candidates.extend(stage_dir.glob(required))
        else:
            candidates.append(stage_dir / required)

    return any(candidate.exists() for candidate in candidates)


def _validate_divergence_models(errors: list[str], by_name: dict[str, dict[str, Any]]) -> None:
    missing = sorted(role for role in DIVERGENCE_ROLES if role not in by_name)
    if missing:
        errors.append("divergence_roles_missing:" + ",".join(missing))
        return
    count = _divergence_unique_model_count(by_name)
    if count < 4:
        errors.append(f"divergence_unique_models_lt_4:{count}")


def _validate_l5_acceptance_artifact(errors: list[str], artifact: Path) -> None:
    text = artifact.read_text(encoding="utf-8", errors="replace")
    required_stages = (
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
    )
    lowered = text.lower()
    if "verdict: accepted" not in lowered:
        errors.append("L5_deepseek_acceptance:verdict_not_accepted")
    if "accepted: true" not in lowered:
        errors.append("L5_deepseek_acceptance:accepted_not_true")
    if "evidence_packet_ready_for_decision: true" not in lowered:
        errors.append("L5_deepseek_acceptance:evidence_packet_not_ready")
    for stage_name in required_stages:
        if stage_name not in text:
            errors.append(f"L5_deepseek_acceptance:checked_stage_missing:{stage_name}")
    if "final_controller_report" in lowered:
        errors.append("L5_deepseek_acceptance:forbidden_final_controller_report")
    for token in ("artifact_path", "executor_model", "valid_for_pipeline", "stage_name", "owner="):
        if token in lowered:
            errors.append(f"L5_deepseek_acceptance:raw_metadata:{token}")
    required_sections = (
        "evidence_strength",
        "controversy",
        "evidence_gap",
        "evidence_supported",
        "reasonable_inference",
        "foresight_hypothesis",
    )
    missing_sections = [section for section in required_sections if f"## {section}" not in lowered]
    if missing_sections:
        errors.append("L5_deepseek_acceptance:missing_evidence_packet_sections:" + ",".join(missing_sections))
    for section in required_sections:
        body = _markdown_section_body(text, section)
        if f"## {section}" in lowered and len(body) < 60:
            errors.append(f"L5_deepseek_acceptance:thin_evidence_packet_section:{section}")
    combined_sections = "\n".join(_markdown_section_body(text, section).lower() for section in required_sections)
    if not combined_sections.strip():
        errors.append("L5_deepseek_acceptance:acceptance_summary_only")
    elif "accepted" in combined_sections and not any(
        term in combined_sections
        for term in ("evidence", "证据", "inference", "推断", "hypothesis", "假设", "gap", "缺口", "controvers", "争议")
    ):
        errors.append("L5_deepseek_acceptance:acceptance_summary_only")


def _markdown_section_body(text: str, heading: str) -> str:
    marker = f"## {heading}"
    lowered = (text or "").lower()
    start = lowered.find(marker.lower())
    if start < 0:
        return ""
    body_start = start + len(marker)
    next_index = lowered.find("\n## ", body_start)
    if next_index < 0:
        next_index = len(text or "")
    return (text or "")[body_start:next_index].strip()


def _divergence_unique_model_count(by_name: dict[str, dict[str, Any]]) -> int:
    return len(
        {
            str(by_name[role].get("model"))
            for role in DIVERGENCE_ROLES
            if role in by_name and by_name[role].get("model")
        }
    )


def _read_stage_artifact_text(run: dict[str, Any], stage_name: str, *, base_dir: str | Path | None) -> str:
    base = Path(base_dir) if base_dir is not None else None
    for record in _stage_records(run):
        if record.get("stage_name") != stage_name:
            continue
        artifact = _resolve_path(record.get("artifact_path", ""), base)
        if artifact.is_dir():
            artifact = artifact / "report.md"
        try:
            return artifact.read_text(encoding="utf-8")
        except OSError:
            return ""
    return ""


def _compact_trace(run: dict[str, Any]) -> str:
    lines = []
    for record in _stage_records(run):
        stage = record.get("stage_name", "")
        owner = record.get("owner", "")
        executor_model = record.get("executor_model", "")
        artifact = record.get("artifact_path", "")
        valid = record.get("valid_for_pipeline", "")
        lines.append(f"- {stage} | owner={owner} | executor_model={executor_model} | artifact_path={artifact} | valid_for_pipeline={valid}")
    return "\n".join(lines)


__all__ = [
    "CANONICAL_STAGES",
    "DIVERGENCE_ROLES",
    "ENGINE_DECISION",
    "ENGINE_MODES",
    "ENGINE_RESEARCH",
    "ENGINE_RESEARCH_DECISION",
    "GEMINI_HIGH",
    "GEMINI_PRO_HIGH",
    "PIPELINE_BLOCKED",
    "PIPELINE_COMPLETE",
    "PIPELINE_INCOMPLETE",
    "ROUTE_SOURCE_RAW_USER_EXPLICIT",
    "StageRecord",
    "StageSpec",
    "build_engine_contract",
    "build_dry_run_plan",
    "canonical_schema",
    "check_explicit_heavy_mode_declaration",
    "detect_task_engine_mode",
    "make_stage_record",
    "planned_outputs",
    "render_final_markdown",
    "validate_pipeline",
]
