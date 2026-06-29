"""Safety primitives for lossy context/payload reduction.

This module is intentionally conservative.  It is not a general-purpose
compressor; it answers two questions for callers that already reduce context:

* Is this block safe to send to an LLM prose compressor?
* Did the compressed output preserve the tokens and structure that make the
  original block executable/auditable?

Unknown content is treated as BYPASS_ORIGINAL.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class BlockClassification:
    block_type: str
    allow_compression: bool
    reason: str
    critical_tokens: tuple[str, ...] = ()
    raw_ref_required: bool = False


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reasons: tuple[str, ...] = ()


CRITICAL_KEYWORDS = (
    "DO_NOT",
    "MUST",
    "ONLY",
    "NEVER",
    "must",
    "only",
    "never",
    "do not",
    "forbidden",
    "禁止",
    "不要",
    "必须",
    "只允许",
    "不得",
    "验收",
    "PASS",
    "BLOCKED",
)

MUST_KEEP_TOKENS = (
    "must",
    "only",
    "never",
    "do not",
    "forbidden",
    "禁止",
    "不要",
    "必须",
    "只允许",
    "不得",
    "验收",
    "PASS",
    "BLOCKED",
    "HEAD",
    "branch",
    "commit",
    "outputs/**",
)

ARTIFACT_MARKERS = (
    "evidence packet",
    "research_evidence_packet",
    "stage record",
    "stage records",
    "convergence report",
    "calibration verdict",
    "execution contract",
    "EXECUTION_CONTRACT",
    "ROUTE_CARD",
    "PASS / BLOCKED",
    "PASS/BLOCKED",
    "DO_NOT",
    "Codex handoff",
    "handoff prompt",
)

CONFIG_EXTENSIONS = (
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".plist",
    ".lock",
)

CODE_EXTENSIONS = (
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".scala",
    ".sql",
    ".html",
    ".css",
    ".scss",
    ".vue",
    ".svelte",
)

_FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")
_TRACEBACK_RE = re.compile(
    r"(?m)^(Traceback \(most recent call last\):|  File \"[^\"]+\", line \d+|"
    r"\w+(?:Error|Exception):|Caused by:|Exception in thread|Error: )"
)
_DIFF_RE = re.compile(r"(?m)^(diff --git |@@ |--- |\+\+\+ |[+-](?![+-]))")
_SHELL_RE = re.compile(
    r"(?m)^\s*(?:\$ |%(?:\s|$)|(?:python|python3|pytest|npm|pnpm|yarn|uv|git|gh|"
    r"curl|docker|kubectl|make|cargo|go|node|bun)\s+\S+)"
)
_CODE_LINE_RE = re.compile(
    r"^\s*(?:"
    r"def\s+\w+|class\s+\w+|import\s+|from\s+\S+\s+import\s+|"
    r"function\s+\w+|async\s+function\s+|const\s+\w+|let\s+\w+|var\s+\w+|"
    r"export\s+|interface\s+\w+|type\s+\w+\s*=|enum\s+\w+|"
    r"if\s*\(|for\s*\(|while\s*\(|try\s*\{|catch\s*\(|return\b|"
    r"package\s+\w+|use\s+\w+|namespace\s+\w+|#include\b|"
    r"</?\w+|[}\])];\s*$"
    r")"
)
_YAML_KEY_RE = re.compile(r"(?m)^\s*[A-Za-z0-9_.-]+\s*:\s*(?:\S.*)?$")
_TOML_SECTION_RE = re.compile(r"(?m)^\s*\[[A-Za-z0-9_.-]+]\s*$")
_PLIST_RE = re.compile(r"(?is)<plist\b|<!DOCTYPE\s+plist\b")
_ABS_PATH_RE = re.compile(r"(?:/Users/[^\s`'\"),\]}<>]+|/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)")
_FILE_PATH_RE = re.compile(
    r"(?<![\w.-])(?:[\w@./~ -]+?\.(?:py|md|json|ya?ml|toml|plist|txt|log|diff|patch|"
    r"ts|tsx|js|jsx|sh|go|rs|java|html|css|vue|svelte))(?![\w.-])"
)
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{7,64}\b")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?\b")
_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?%")
_PORT_RE = re.compile(r"(?i)\b(?:port\s*[:=]?\s*)?([1-9]\d{3,5})\b")
_BRANCH_RE = re.compile(r"(?i)\bbranch\s*[:=]?\s*([A-Za-z0-9._/-]+)")
_REPO_RE = re.compile(r"(?i)\brepo(?:sitory)?\s*[:=]?\s*([A-Za-z0-9._/-]+)")
_HEAD_RE = re.compile(r"\bHEAD\b")


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def _casefold_contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()


def _find_present_tokens(text: str, tokens: Iterable[str]) -> tuple[str, ...]:
    return tuple(token for token in tokens if _casefold_contains(text, token))


def _has_unbalanced_fence(text: str) -> bool:
    in_fence = False
    marker = ""
    for line in (text or "").splitlines():
        match = _FENCE_LINE_RE.match(line)
        if not match:
            continue
        current = match.group(1)
        if not in_fence:
            in_fence = True
            marker = current
        elif current == marker:
            in_fence = False
            marker = ""
    return in_fence


def split_markdown_fenced_blocks(text: str) -> list[tuple[str, str]]:
    """Return (kind, content) blocks, keeping fenced blocks atomic.

    kind is one of: text, fenced, unclosed_fenced.
    """
    if not text:
        return [("text", "")]

    blocks: list[tuple[str, str]] = []
    text_lines: list[str] = []
    fence_lines: list[str] = []
    in_fence = False
    marker = ""

    for line in text.splitlines(keepends=True):
        match = _FENCE_LINE_RE.match(line)
        if match and not in_fence:
            if text_lines:
                blocks.append(("text", "".join(text_lines)))
                text_lines = []
            in_fence = True
            marker = match.group(1)
            fence_lines = [line]
            continue
        if in_fence:
            fence_lines.append(line)
            if match and match.group(1) == marker:
                blocks.append(("fenced", "".join(fence_lines)))
                fence_lines = []
                in_fence = False
                marker = ""
            continue
        text_lines.append(line)

    if in_fence:
        blocks.append(("unclosed_fenced", "".join(fence_lines)))
    if text_lines:
        blocks.append(("text", "".join(text_lines)))
    return blocks or [("text", "")]


def _looks_like_json(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        json.loads(stripped)
        return True
    except Exception:
        return bool(re.match(r"^\s*[{[][\s\S]*[}\]]\s*$", stripped))


def _looks_like_yaml(text: str) -> bool:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    key_lines = sum(1 for line in lines if _YAML_KEY_RE.match(line))
    return key_lines >= 3 and key_lines / len(lines) >= 0.45


def _looks_like_toml(text: str) -> bool:
    return bool(_TOML_SECTION_RE.search(text or ""))


def _looks_like_code(text: str) -> bool:
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 4:
        return False
    code_lines = sum(1 for line in lines if _CODE_LINE_RE.search(line))
    indented = sum(1 for line in lines if re.match(r"^\s{2,}\S", line))
    brace_semicolon = sum(1 for line in lines if re.search(r"[{};]\s*$", line))
    signals = code_lines + min(indented, 6) + min(brace_semicolon, 6)
    return code_lines >= 3 and signals / len(lines) >= 0.30


def _has_path_hash_or_branch_dense_text(text: str) -> bool:
    return bool(
        _ABS_PATH_RE.search(text or "")
        or _HEAD_RE.search(text or "")
        or _BRANCH_RE.search(text or "")
        or re.search(r"(?i)\bcommit(?:\s+hash)?\b", text or "")
        or _HEX_RE.search(text or "")
    )


def classify_text_block(
    text: str,
    *,
    role: str | None = None,
    source_path: str | None = None,
) -> BlockClassification:
    raw = text if isinstance(text, str) else str(text or "")
    stripped = raw.strip()
    role = (role or "").strip().lower()
    critical_tokens = _find_present_tokens(raw, CRITICAL_KEYWORDS)

    if not stripped:
        return BlockClassification("empty", False, "empty block")
    if role == "system":
        return BlockClassification(
            "system_prompt",
            False,
            "system/Codex prompt is an execution contract",
            critical_tokens,
        )
    if role == "tool":
        return BlockClassification(
            "tool_output",
            False,
            "tool outputs require raw_ref and must not be LLM-compressed",
            critical_tokens,
            raw_ref_required=True,
        )
    if _has_unbalanced_fence(raw):
        return BlockClassification("markdown_fence_unclosed", False, "unclosed fenced block", critical_tokens)
    if any(kind != "text" for kind, _ in split_markdown_fenced_blocks(raw)):
        return BlockClassification("markdown_fence", False, "markdown fenced block is atomic", critical_tokens)
    if critical_tokens:
        return BlockClassification("critical_instruction", False, "must-keep instruction token", critical_tokens)
    if _TRACEBACK_RE.search(raw):
        return BlockClassification("traceback", False, "traceback stack frames must be verbatim")
    if _DIFF_RE.search(raw):
        return BlockClassification("diff", False, "diff prefixes must be verbatim")
    if _SHELL_RE.search(raw):
        return BlockClassification("shell", False, "shell commands are executable content")
    if _looks_like_json(raw):
        return BlockClassification("json", False, "JSON must be verbatim")
    if _looks_like_yaml(raw):
        return BlockClassification("yaml", False, "YAML must be verbatim")
    if _looks_like_toml(raw):
        return BlockClassification("toml", False, "TOML must be verbatim")
    if _PLIST_RE.search(raw):
        return BlockClassification("plist", False, "plist must be verbatim")
    if source_path and Path(source_path).suffix.lower() in CONFIG_EXTENSIONS:
        return BlockClassification("config", False, "config file content must be verbatim")
    if source_path and Path(source_path).suffix.lower() in CODE_EXTENSIONS:
        return BlockClassification("code", False, "source code must be verbatim")
    if _looks_like_code(raw):
        return BlockClassification("code", False, "code-like content must be verbatim")

    lowered = raw.casefold()
    artifact_hits = tuple(marker for marker in ARTIFACT_MARKERS if marker.casefold() in lowered)
    if artifact_hits:
        return BlockClassification("stage_artifact", False, "stage/evidence artifact marker", artifact_hits)
    if _has_path_hash_or_branch_dense_text(raw):
        return BlockClassification("path_hash_branch_dense", False, "path/hash/branch dense content")
    if "\x00" in raw:
        return BlockClassification("unknown", False, "unknown binary-like content")

    # Low-risk prose: no executable syntax, no must-keep instruction tokens,
    # no path/hash/branch density.  This is the only class eligible for LLM
    # prose compression.
    return BlockClassification("low_risk_prose", True, "low-risk prose")


def _extract_presence_tokens(text: str) -> set[str]:
    found: set[str] = set()
    for token in MUST_KEEP_TOKENS:
        if _casefold_contains(text, token):
            found.add(token)
    return found


def _extract_exact_tokens(text: str) -> set[str]:
    raw = text or ""
    tokens: set[str] = set()
    for regex in (_ABS_PATH_RE, _FILE_PATH_RE, _HEX_RE, _DATE_RE, _PERCENT_RE):
        tokens.update(match.group(0).strip(".,;:") for match in regex.finditer(raw))
    for match in _PORT_RE.finditer(raw):
        port = match.group(1)
        try:
            value = int(port)
        except ValueError:
            continue
        if 1 <= value <= 65535:
            tokens.add(port)
    for regex in (_BRANCH_RE, _REPO_RE):
        for match in regex.finditer(raw):
            tokens.add(match.group(1).strip(".,;:"))
    return {token for token in tokens if token}


def _missing_casefold_tokens(required: Iterable[str], text: str) -> list[str]:
    return [token for token in required if not _casefold_contains(text, token)]


def _missing_exact_tokens(required: Iterable[str], text: str) -> list[str]:
    return [token for token in required if token not in text]


def _looks_truncated(compressed: str, max_tokens: int | None, completion_tokens: int | None) -> list[str]:
    reasons: list[str] = []
    out = (compressed or "").strip()
    if not out:
        return ["empty compressed output"]
    if max_tokens and completion_tokens and completion_tokens >= int(max_tokens * 0.95):
        reasons.append("output token count is close to max_tokens")
    if out.endswith(("...", "…", ",", "，", ":", "：", "-", "and", "or")):
        reasons.append("output appears to end mid-thought")
    if re.search(r"(?i)(?:\[?\.\.\. ?truncated]?)$", out):
        reasons.append("output ended with truncation marker")
    if out[-1] not in ".?!。！？)]}”’\"'`":
        # Headings and list fragments can be valid, but low-risk prose
        # compression should still finish on a closed sentence/structure.
        reasons.append("output lacks terminal punctuation or structural close")
    if out.count("```") % 2 != 0:
        reasons.append("output has unbalanced markdown fences")
    return reasons


def validate_compressed_text(
    original: str,
    compressed: str,
    *,
    max_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> ValidationResult:
    reasons: list[str] = []
    original = original if isinstance(original, str) else str(original or "")
    compressed = compressed if isinstance(compressed, str) else str(compressed or "")

    reasons.extend(_looks_truncated(compressed, max_tokens, completion_tokens))

    must_keep = _extract_presence_tokens(original)
    missing_keep = _missing_casefold_tokens(must_keep, compressed)
    if missing_keep:
        reasons.append("must-keep token loss: " + ", ".join(sorted(missing_keep)[:12]))

    exact_tokens = _extract_exact_tokens(original)
    missing_exact = _missing_exact_tokens(exact_tokens, compressed)
    if missing_exact:
        reasons.append("path/hash/number token loss: " + ", ".join(sorted(missing_exact)[:12]))

    if original.count("```") != compressed.count("```"):
        reasons.append("markdown fence count changed")
    if _looks_like_json(original) or _looks_like_yaml(original) or _looks_like_toml(original) or _PLIST_RE.search(original):
        if original.strip() != compressed.strip():
            reasons.append("structured config content changed")
    if _DIFF_RE.search(original):
        original_prefixes = [line[:1] for line in original.splitlines() if line.startswith(("+", "-"))]
        compressed_prefixes = [line[:1] for line in compressed.splitlines() if line.startswith(("+", "-"))]
        if original_prefixes != compressed_prefixes:
            reasons.append("diff +/- prefix sequence changed")
    if _TRACEBACK_RE.search(original):
        original_frames = re.findall(r'(?m)^  File "[^"]+", line \d+', original)
        compressed_frames = re.findall(r'(?m)^  File "[^"]+", line \d+', compressed)
        if original_frames != compressed_frames:
            reasons.append("traceback frame sequence changed")

    return ValidationResult(ok=not reasons, reasons=tuple(reasons))


def write_raw_ref(text: str, *, block_type: str = "block") -> str | None:
    """Persist an original block to temp storage and return a readable path."""
    try:
        digest = sha256_text(text)
        safe_type = re.sub(r"[^A-Za-z0-9_.-]+", "_", block_type or "block").strip("_") or "block"
        base = Path(tempfile.gettempdir()) / "hermes-context-reducer" / "raw"
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{safe_type}_{digest[:16]}.txt"
        if not path.exists():
            path.write_text(text or "", encoding="utf-8", errors="replace")
        return str(path)
    except Exception:
        return None


def compression_metadata_line(
    *,
    block_type: str,
    original: str,
    compressed: str,
    compression_applied: bool,
    fallback_used: bool,
    reason: str,
    raw_ref: str | None = None,
) -> str:
    return (
        "[context_reducer: "
        f"block_type={block_type}; "
        f"compression_applied={str(compression_applied).lower()}; "
        f"fallback_used={str(fallback_used).lower()}; "
        f"reason={reason}; "
        f"original_sha256={sha256_text(original)}; "
        f"original_length={len(original or '')}; "
        f"compressed_length={len(compressed or '')}; "
        f"raw_ref={raw_ref or 'missing'}]"
    )


def diagnose_payload_reduction(
    input_texts: list[str],
    compressed_texts: list[str] | None = None,
    *,
    validator_failures: list[str] | None = None,
    raw_ref_missing: int = 0,
) -> dict[str, Any]:
    compressed_texts = compressed_texts if compressed_texts is not None else input_texts
    total_input = sum(len(text or "") for text in input_texts)
    total_compressed = sum(len(text or "") for text in compressed_texts)
    classifications = [classify_text_block(text) for text in input_texts]
    critical = [c.block_type for c in classifications if not c.allow_compression]
    compressed_prose = sum(1 for c in classifications if c.allow_compression)
    failures = validator_failures or []
    ratio = (total_compressed / total_input) if total_input else 1.0
    return {
        "total_input_length": total_input,
        "compressed_view_length": total_compressed,
        "compression_ratio": ratio,
        "bypass_blocks": len(critical),
        "compressed_prose_blocks": compressed_prose,
        "fallback_blocks": len(failures),
        "validator_failure_reasons": failures,
        "critical_blocks_detected": critical,
        "safe_for_replacement": not critical and not failures and raw_ref_missing == 0,
        "raw_ref_coverage_complete": raw_ref_missing == 0,
        "raw_ref_missing": raw_ref_missing,
    }
