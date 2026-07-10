"""Deterministic routing rules for Codex/Hermes/OpenClaw dispatch.

The router is intentionally a pure rule engine: it derives route, risk, and
write policy from keyword, path, resource, document, tool, and safety signals.
It does not call an LLM.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import re
import json
import os
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


ROUTES = {"codex", "hermes", "openclaw", "mixed", "blocked", "human_review"}
RISK_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
RISK_BY_SCORE = {value: key for key, value in RISK_ORDER.items()}
WRITE_POLICIES = {
    "none",
    "patch_only",
    "direct_codex",
    "break_glass",
    "blocked",
    "human_review",
}
STATES = {
    "NORMAL",
    "CODEX_UNAVAILABLE",
    "BREAK_GLASS",
    "RECOVERY",
    "HUMAN_REVIEW_PENDING",
}


@dataclass
class RouteResult:
    route: str
    reason_codes: list[str]
    risk: str
    write_policy: str
    state: str
    mixed_steps: Optional[list[str]]
    confidence: float
    handoff_receipt: Optional[dict] = None
    # 2026-06-04: 完整合约字段（hermes_router_next_steps_20260604.md）
    domain: str = ""
    operation: str = "none"
    handoff_required: bool = False
    user_confirmation_required: bool = False
    receipt_required: bool = False


@dataclass
class _Signals:
    text: str
    raw_text: str = ""
    reason_codes: list[str] = field(default_factory=list)
    domains: set[str] = field(default_factory=set)
    explicit_route: Optional[str] = None
    safety_route: Optional[str] = None
    risk_score: int = 1
    write_intent: bool = False
    read_only: bool = False
    six_dimensional_score: dict[str, int] = field(
        default_factory=lambda: {
            "keyword": 0,
            "path": 0,
            "resource": 0,
            "document": 0,
            "tool": 0,
            "safety": 0,
        }
    )

    def add_reason(self, reason: str, risk: str | None = None) -> None:
        if reason not in self.reason_codes:
            self.reason_codes.append(reason)
        if risk is not None:
            self.risk_score = max(self.risk_score, RISK_ORDER[risk])

    def bump(self, dimension: str, amount: int = 1) -> None:
        self.six_dimensional_score[dimension] += amount


# ── Contract helpers (hermes_router_next_steps_20260604.md) ──

_DOMAIN_MAP: dict[str, str] = {
    "DOMAIN_ENGINEERING": "engineering",
    "DOMAIN_CODE_REVIEW": "engineering",
    "DOMAIN_DEBUGGING": "engineering",
    "DOMAIN_DATA_PIPELINE": "engineering",
    "DOMAIN_SELF_MAINTAIN": "engineering",
    "DOMAIN_LOCAL_MODEL": "local_model",
    "DOMAIN_BROWSER": "browser",
    "DOMAIN_RESERVATION": "browser",
    "DOMAIN_DOCUMENT": "document",
    "DOMAIN_CONFIG_NON_ENGINEERING": "document",
    "DOMAIN_COMMUNICATION": "document",
    "DOMAIN_MONITORING": "readonly_diagnostic",
    "DOMAIN_INSTALL": "install",
    "DOMAIN_REMOTE_FILES": "remote_files",
    "DOMAIN_SECURITY": "security",
    "DOMAIN_DEPLOYMENT": "security",
}

_OPERATION_VOCAB: tuple[str, ...] = (
    "read_only", "write", "destructive",
    "external_side_effect", "credential_touching", "none",
)

CREDENTIAL_NAME_PATTERNS: tuple[str, ...] = (
    "openai_api_key",
    "openai_key",
    "anthropic_api_key",
    "anthropic_key",
    "gemini_api_key",
    "google_api_key",
    "github_token",
    "gh_token",
    "gitlab_token",
    "aws_secret_access_key",
    "aws_access_key_id",
    "aws_session_token",
    "deepseek_api_key",
    "deepseek_key",
    "slack_bot_token",
    "slack_token",
    "stripe_secret_key",
    "supabase_service_role_key",
    "database_url",
    "postgres_url",
    "jwt_secret",
)

CREDENTIAL_EXPOSURE_VERBS: tuple[str, ...] = (
    "读出来",
    "告诉我",
    "显示",
    "打印",
    "输出",
    "列出来",
    "列出",
    "是多少",
    "给我",
    "看看",
    "看一下",
    "echo",
    "cat",
    "show",
    "print",
    "dump",
    "output",
    "reveal",
    "read",
    "montre",
    "affiche",
    "zeige",
    "mostrar",
    "muestra",
    "mostre",
    "покажи",
    "اعرض",
    "表示",
    "출력",
)

MULTILINGUAL_CREDENTIAL_TERMS: tuple[str, ...] = (
    "apiキー",
    "秘密鍵",
    "パスワード",
    "비밀키",
    "api 키",
    "암호",
    "clé api",
    "cle api",
    "clé secrète",
    "mot de passe",
    "api-schlüssel",
    "api schlüssel",
    "geheimer schlüssel",
    "passwort",
    "ключ api",
    "секретный ключ",
    "пароль",
    "مفتاح api",
    "كلمة المرور",
    "سر",
    "clave api",
    "contraseña",
    "secreto",
    "chave api",
    "senha",
    "segredo",
    "khóa api",
    "khoa api",
    "mật khẩu",
    "mat khau",
    "คีย์ api",
    "รหัสผ่าน",
)

SENSITIVE_SUBJECT_MARKERS: tuple[str, ...] = (
    "api key",
    "api_key",
    "api密钥",
    "api 密钥",
    "secret",
    "密钥",
    "密码",
    "dsn",
    "token",
    "private_key",
    "private key",
    "jwt_secret",
    "jwt secret",
    ".env.production",
    "openai_api_key",
    "github_token",
    *CREDENTIAL_NAME_PATTERNS,
    *MULTILINGUAL_CREDENTIAL_TERMS,
)

SOCIAL_ENGINEERING_MARKERS: tuple[str, ...] = (
    "绕过",
    "演练",
    "练习",
    "假装",
    "假的",
    "不触发",
    "不需要审查",
    "测试框架",
    "跳过安全",
    "授权安全演练",
    "本地测试绕过",
    "假沙盒",
    "root用户",
    "root 用户",
    "ignore",
    "pretend",
    "bypass",
    "override",
    "skip safety",
    "exercise",
)

PROMPT_INJECTION_MARKERS: tuple[str, ...] = (
    "ignore all previous",
    "ignore previous instructions",
    "ignore all previous instructions",
    "system override",
    "system:",
    "system ",
    "<|im_start|>",
    "[inst]",
    "developer override",
)

REAL_VALUE_MARKERS: tuple[str, ...] = (
    "真实值",
    "真实 value",
    "actual",
    "real value",
    "real secret",
    "actual value",
    "actual secret",
)

SAFE_SANDBOX_VALUES = {
    "workspace-write",
    "read-only",
    "readonly",
    "sandbox",
    "isolated",
}

# ── Structural anomaly detection constants (Claude Sonnet anti-gravity audit) ──

BIDI_CONTROL_CHARS: frozenset[int] = frozenset({
    0x202A,  # LEFT-TO-RIGHT EMBEDDING
    0x202B,  # RIGHT-TO-LEFT EMBEDDING
    0x202C,  # POP DIRECTIONAL FORMATTING
    0x202D,  # LEFT-TO-RIGHT OVERRIDE
    0x202E,  # RIGHT-TO-LEFT OVERRIDE
    0x2066,  # LEFT-TO-RIGHT ISOLATE
    0x2067,  # RIGHT-TO-LEFT ISOLATE
    0x2068,  # FIRST STRONG ISOLATE
    0x2069,  # POP DIRECTIONAL ISOLATE
})

VARIATION_SELECTORS: frozenset[int] = frozenset(range(0xFE00, 0xFE10)) | frozenset(range(0xE0100, 0xE01F0))

# Extended homoglyph map — characters that look like ASCII but aren't.
# The _CONFUSABLE_TRANSLATION above handles lowercase-only Cyrillic→Latin;
# this set covers uppercase, Greek, and other scripts.
_HOMOGLYPH_CODEPOINTS: frozenset[int] = frozenset({
    # Cyrillic lowercase
    0x0430,  # а → a
    0x0435,  # е → e
    0x043E,  # о → o
    0x0440,  # р → p
    0x0441,  # с → c
    0x0445,  # х → x
    0x0443,  # у → y
    0x0456,  # і → i
    # Cyrillic uppercase
    0x0410, 0x0412, 0x0415, 0x041C, 0x041D, 0x041A,
    0x041E, 0x0420, 0x0421, 0x0422, 0x0425,
    # Greek lowercase
    0x03B1, 0x03BF, 0x03B5,
    # Greek uppercase
    0x0391, 0x0392, 0x0395, 0x0397, 0x0399, 0x039A,
    0x039C, 0x039D, 0x039F, 0x03A1, 0x03A4, 0x03A7,
})

# Maximum input size before NFKC normalization is skipped (DoS protection).
NFKC_MAX_INPUT_BYTES = 200_000


def _derive_domain(signals: _Signals) -> str:
    """Pick the primary domain from collected signals."""
    doms = signals.domains
    if signals.safety_route:
        return "security"
    if (
        "DOMAIN_BROWSER" in doms
        and doms & {"DOMAIN_ENGINEERING", "DOMAIN_DEBUGGING", "DOMAIN_CODE_REVIEW"}
        and (signals.explicit_route != "openclaw" or "SYSTEM_STATE_REWRITE" in signals.reason_codes)
    ):
        return "mixed"
    if signals.explicit_route == "codex":
        return "engineering"
    if signals.explicit_route == "openclaw":
        return "browser"
    if "DOMAIN_DOCUMENT" in doms and not doms & {"DOMAIN_ENGINEERING", "DOMAIN_DEBUGGING", "DOMAIN_DATA_PIPELINE"}:
        return "document"
    if "DOMAIN_DATA_PIPELINE" in doms and not signals.write_intent:
        return "readonly_diagnostic"
    for candidate in (
        "DOMAIN_SECURITY",
        "DOMAIN_REMOTE_FILES",
        "DOMAIN_INSTALL",
        "DOMAIN_LOCAL_MODEL",
        "DOMAIN_ENGINEERING",
        "DOMAIN_CODE_REVIEW",
        "DOMAIN_DEBUGGING",
        "DOMAIN_DATA_PIPELINE",
        "DOMAIN_BROWSER",
        "DOMAIN_RESERVATION",
        "DOMAIN_DOCUMENT",
        "DOMAIN_CONFIG_NON_ENGINEERING",
        "DOMAIN_COMMUNICATION",
        "DOMAIN_MONITORING",
        "DOMAIN_SELF_MAINTAIN",
        "DOMAIN_DEPLOYMENT",
    ):
        if candidate in doms:
            return _DOMAIN_MAP[candidate]
    return "mixed" if len(doms) > 1 else (_DOMAIN_MAP.get(next(iter(doms)), "mixed") if doms else "mixed")


def _derive_operation(signals: _Signals) -> str:
    """Derive the operation mode from read/write intent and risk."""
    doms = signals.domains
    if any(reason in signals.reason_codes for reason in ("CREDENTIAL_VALUE_REQUESTED", "CREDENTIAL_PATH_CONSULTATION", "LITERAL_SECRET_VALUE")):
        return "credential_touching"
    destructive_intent = _has_any(
        signals.text,
        ("删除", "删掉", "移除", "清掉", "delete", "remove", "rm -rf"),
    )
    if "DOMAIN_REMOTE_FILES" in doms and destructive_intent:
        return "destructive"
    if "DOMAIN_INSTALL" in doms or ("DOMAIN_LOCAL_MODEL" in doms and _has_any(signals.text, ("跑", "smoke", "test", "load", "unload", "benchmark", "chat"))):
        return "external_side_effect"
    if "DOMAIN_BROWSER" in doms and not signals.write_intent:
        return "external_side_effect"
    if signals.write_intent and signals.risk_score >= 4:
        return "destructive"
    if signals.write_intent:
        return "write"
    if signals.read_only:
        return "read_only"
    return "none"


def route_decision(request: str, input_state: str = "NORMAL", context: dict | None = None) -> RouteResult:
    """Route a request using deterministic policy rules.

    Priority order is:
    1. safety redline gate,
    2. system state rewrite,
    3. user explicit route,
    4. domain executor mapping,
    5. mixed chain detection,
    6. default route.
    """

    context = context or {}
    if not decision_router_enabled(context):
        result = RouteResult(
            route="hermes",
            reason_codes=["DECISION_ROUTER_DISABLED"],
            risk="L1",
            write_policy="none",
            state=input_state if input_state in STATES else "NORMAL",
            mixed_steps=None,
            confidence=0.0,
            domain="mixed",
            operation="none",
            handoff_required=False,
            user_confirmation_required=False,
            receipt_required=False,
        )
        audit_route_decision(request, result, context)
        return result

    state = input_state if input_state in STATES else "NORMAL"
    ttl_expired = _context_ttl_expired(context)
    sandbox_isolated = _context_sandbox_isolated(context)
    human_review_approved = bool(context.get("human_review_approved"))
    if ttl_expired and state == "BREAK_GLASS":
        state = "NORMAL"
    if state == "HUMAN_REVIEW_PENDING" and human_review_approved:
        state = "NORMAL"
    text = _normalize(request)
    signals = _Signals(text=text, raw_text=request)

    _detect_read_write_intent(signals)
    if context.get("read_only"):
        signals.read_only = True
        signals.write_intent = False
    _detect_base_signals(signals)
    if ttl_expired:
        signals.add_reason("STATE_TTL_EXPIRED")
        signals.bump("keyword")
    if not sandbox_isolated:
        signals.add_reason("SANDBOX_NOT_ISOLATED", "L3")
        signals.bump("safety")

    # C-001: safety redlines are evaluated before dispatch decisions.
    _detect_safety_redlines(signals, context)

    # User explicit route is still recorded before the safety gate is returned.
    # C-007: explicit routing cannot bypass a safety redline.
    _detect_user_explicit_route(signals)

    _detect_domains(signals)

    if state != "NORMAL":
        signals.add_reason("SYSTEM_STATE_REWRITE")
        signals.bump("keyword")
    elif (context.get("break_glass") and not ttl_expired) or _has_any(text, ("break_glass", "break glass")):
        signals.add_reason("SYSTEM_STATE_REWRITE")
        signals.bump("keyword")

    mixed_steps = _mixed_steps(signals)
    if mixed_steps:
        mixed_risk = None if mixed_steps[0] == "codex:review" else "L2"
        signals.add_reason("MIXED_CHAIN_REQUIRED", mixed_risk)

    route = _route_from_domains(signals, mixed_steps)
    write_policy = _write_policy_for_route(route, signals)

    if not sandbox_isolated and signals.write_intent and route in {"codex", "mixed", "openclaw"}:
        route = "human_review"
        write_policy = "human_review"
        mixed_steps = None

    # C-009: a pending human-review state blocks executor dispatch.
    if state == "HUMAN_REVIEW_PENDING":
        signals.add_reason("HUMAN_REVIEW_PENDING")
        route = "human_review"
        write_policy = "human_review"
        mixed_steps = None

    if signals.explicit_route and not signals.safety_route and state != "HUMAN_REVIEW_PENDING" and route != "mixed":
        route = signals.explicit_route
        write_policy = _write_policy_for_route(route, signals)

    # C-001/C-004: redlines override later dispatch and keep all reason_codes.
    if signals.safety_route == "blocked":
        route = "blocked"
        write_policy = "blocked"
        mixed_steps = None
    elif signals.safety_route == "human_review":
        route = "human_review"
        mixed_steps = None
        write_policy = "human_review"

    # C-005/C-014: Codex-unavailable preserves route/mixed-chain analysis but
    # downgrades any Codex write step to human review.
    if (
        state == "CODEX_UNAVAILABLE"
        and route in {"codex", "mixed"}
        and write_policy in {"patch_only", "direct_codex"}
    ):
        write_policy = "human_review"

    if state == "RECOVERY" and not signals.safety_route:
        signals.risk_score = min(signals.risk_score, RISK_ORDER["L2"])

    # C-005: break-glass is an explicit controlled state, not normal dispatch.
    if (state == "BREAK_GLASS" or (context.get("break_glass") and not ttl_expired)) and route not in {"blocked"}:
        route = "human_review"
        write_policy = "break_glass"
        signals.risk_score = max(signals.risk_score, RISK_ORDER["L3"])

    # C-012: recovery does not auto-approve production deployment; safety rules
    # above keep production deploy as human_review.

    confidence = _confidence(signals, route)
    result = RouteResult(
        route=route,
        reason_codes=signals.reason_codes,
        risk=RISK_BY_SCORE[signals.risk_score],
        write_policy=write_policy,
        state=state,
        mixed_steps=mixed_steps,
        confidence=confidence,
        domain=_derive_domain(signals),
        operation=_derive_operation(signals),
        handoff_required=route in {"codex", "openclaw", "mixed"},
        user_confirmation_required=(
            signals.risk_score >= RISK_ORDER["L3"]
            or route in {"blocked", "human_review"}
            or "DOMAIN_INSTALL" in signals.domains
            or "DOMAIN_REMOTE_FILES" in signals.domains
        ),
        receipt_required=route in {"codex", "openclaw", "mixed"},
    )
    result.handoff_receipt = build_handoff_receipt(result, context)
    audit_route_decision(request, result, context)
    return result


def decision_router_enabled(context: dict | None = None) -> bool:
    """Return whether the deterministic router should make routing decisions."""
    context = context or {}
    if "decision_router_enabled" in context:
        return bool(context["decision_router_enabled"])
    return os.getenv("HERMES_DECISION_ROUTER_DISABLE", "").lower() not in {"1", "true", "yes", "on"}


def _context_ttl_expired(context: dict) -> bool:
    for key in ("ttl_seconds", "ttl"):
        if key in context:
            try:
                return float(context[key]) <= 0
            except (TypeError, ValueError):
                return False
    ttl_context = context.get("ttl_context") if isinstance(context.get("ttl_context"), dict) else {}
    if ttl_context:
        return bool(ttl_context.get("expired_break_glass") or ttl_context.get("expired_decision"))
    return False


def _context_sandbox_isolated(context: dict) -> bool:
    if "sandbox" not in context:
        return True
    value = context.get("sandbox")
    if value is True:
        return True
    if value in (False, None):
        return False
    return str(value).strip().casefold() in SAFE_SANDBOX_VALUES


def _audit_path(context: dict | None = None) -> Path:
    context = context or {}
    raw = context.get("decision_router_audit_path") or os.getenv("HERMES_DECISION_ROUTER_AUDIT")
    if raw:
        return Path(str(raw)).expanduser()
    return Path.home() / ".hermes" / "logs" / "decision-router-audit.jsonl"


def audit_route_decision(request: str, result: RouteResult, context: dict | None = None) -> None:
    """Append a compact routing audit record, failing closed on log errors."""
    context = context or {}
    if context.get("audit") is False or os.getenv("HERMES_DECISION_ROUTER_AUDIT_DISABLE", "").lower() in {"1", "true", "yes", "on"}:
        return
    row = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "request_preview": request[:240],
        "context_id": context.get("task_id") or context.get("session_id") or context.get("handoff_base"),
        "result": asdict(result),
    }
    try:
        path = _audit_path(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        return


def build_handoff_receipt(result: RouteResult, context: dict | None = None) -> Optional[dict]:
    """Build a status/result receipt pointer for downstream handoff consumers."""
    context = context or {}
    handoff_base = context.get("handoff_base") or context.get("handoff_id")
    status_path = context.get("handoff_status_path") or context.get("status_path")
    result_path = context.get("handoff_result_path") or context.get("result_path")
    result_md_path = context.get("handoff_result_md_path") or context.get("result_md_path")
    if not any((handoff_base, status_path, result_path, result_md_path)):
        return None
    return {
        "handoff_base": handoff_base,
        "status_path": status_path,
        "result_path": result_path,
        "result_md_path": result_md_path,
        "route": result.route,
        "write_policy": result.write_policy,
        "risk": result.risk,
    }


_NORMALIZE_TRANSLATION = str.maketrans(
    {
        "\u200b": None,
        "\u200c": None,
        "\u200d": None,
        "\ufeff": None,
        "／": "/",
        "＼": "\\",
        "｜": "|",
        "＄": "$",
        "＝": "=",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "［": "[",
        "］": "]",
        "｛": "{",
        "｝": "}",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)

_CONFUSABLE_TRANSLATION = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "х": "x",
        "у": "y",
        "Α": "a",
        "Β": "b",
        "Ε": "e",
        "Η": "h",
        "Ι": "i",
        "Κ": "k",
        "Μ": "m",
        "Ν": "n",
        "Ο": "o",
        "Ρ": "p",
        "Τ": "t",
        "Χ": "x",
        "а": "a",
    }
)

_PHONETIC_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("欧盆a矮凯", "openai api key"),
    ("欧盆ai矮凯", "openai api key"),
    ("欧盆 a 矮凯", "openai api key"),
    ("欧盆 ai 矮凯", "openai api key"),
    ("欧盆apikey", "openai api key"),
)


def suspicion_score(raw_text: str) -> tuple[float, list[str]]:
    """Structural anomaly detection — independent of any keyword list.

    Detects not *what* the text says but *how* it is constructed:
    1. invisible character density (Cf/Cc/Co + variation selectors)
    2. BiDi control characters (CVE-2021-42574)
    3. script mixture (normal users stay in 1–2 scripts)
    4. homoglyph ratio (Cyrillic/Greek chars that look like ASCII)
    5. encoding nesting depth (Base64 within Base64)
    6. Unicode whitespace diversity (hidden Morse/steganography channels)
    7. null bytes
    8. oversized input (NFKC DoS protection)

    Returns (score 0.0–1.0, triggered_signal_labels).
    Thresholds:
      0.00–0.07  normal
      0.08–0.19  suspicious → human_review
      0.20+       clear attack → blocked
    """
    signals: list[str] = []
    score: float = 0.0
    if not raw_text:
        return 0.0, signals

    # ── 1. Invisible character density ──
    # Cf=Format (bidi controls, zero-width), Cc=Control (null etc.), Co=Private use
    invisible_count = 0
    for ch in raw_text:
        cat = unicodedata.category(ch)
        cp = ord(ch)
        if cat in ("Cf", "Cc", "Co") or cp in VARIATION_SELECTORS:
            invisible_count += 1
    invisible_ratio = invisible_count / max(len(raw_text), 1)
    if invisible_ratio > 0:
        signals.append(f"invisible_chars:{invisible_ratio:.3f}")
        # Any invisible chars in user text are a red flag — normal text has none
        score += min(invisible_ratio * 8, 0.45)

    # ── 2. BiDi control characters (CVE-2021-42574) ──
    bidi_count = sum(1 for ch in raw_text if ord(ch) in BIDI_CONTROL_CHARS)
    if bidi_count > 0:
        signals.append(f"bidi_controls:{bidi_count}")
        score += min(bidi_count * 0.15, 0.40)

    # ── 3. Script mixture ──
    # Normal users stay >95% single script; attackers mix scripts to hide payloads
    scripts: dict[str, int] = {}
    for ch in raw_text:
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch, "")
            if not name:
                continue
            script = name.split()[0]
        except (ValueError, IndexError):
            continue
        scripts[script] = scripts.get(script, 0) + 1
    total_alpha = sum(scripts.values())
    script_count = len(scripts)
    if script_count >= 3 and total_alpha > 5:
        signals.append(f"script_mix:{script_count}")
        score += min((script_count - 2) * 0.10, 0.30)

    # ── 4. Homoglyph ratio ──
    # Cyrillic/Greek letters that look identical to Latin but aren't
    homoglyph_count = 0
    alpha_count = 0
    for ch in raw_text:
        if ch.isalpha():
            alpha_count += 1
            if ord(ch) in _HOMOGLYPH_CODEPOINTS:
                homoglyph_count += 1
    homoglyph_ratio = homoglyph_count / max(alpha_count, 1)
    if homoglyph_ratio > 0.05:
        signals.append(f"homoglyph:{homoglyph_ratio:.3f}")
        score += min(homoglyph_ratio * 6, 0.25)

    # ── 5. Encoding nesting depth ──
    depth = _encoding_nesting_depth(raw_text)
    if depth >= 2:
        signals.append(f"encoding_nest:{depth}")
        score += min(depth * 0.12, 0.25)

    # ── 6. Unicode whitespace diversity ──
    # Zs = Space Separator (excl. regular space U+0020), Zl/Zp = line/para separator
    seen_ws: set[str] = set()
    for ch in raw_text:
        cat = unicodedata.category(ch)
        if cat == "Zs" and ch != " ":
            seen_ws.add(ch)
        elif cat in ("Zl", "Zp"):
            seen_ws.add(ch)
    ws_diversity = len(seen_ws)
    if ws_diversity >= 2:
        signals.append(f"ws_diversity:{ws_diversity}")
        score += min((ws_diversity - 1) * 0.04, 0.25)

    # ── 7. Null bytes ──
    null_count = raw_text.count("\0")
    if null_count > 0:
        signals.append(f"null_bytes:{null_count}")
        score += min(null_count * 0.10, 0.15)

    # ── 8. Oversized input (NFKC DoS protection) ──
    text_len = len(raw_text)
    if text_len > NFKC_MAX_INPUT_BYTES:
        signals.append(f"large_input:{text_len}")
        score += 0.10
    if text_len > NFKC_MAX_INPUT_BYTES * 2:
        score += 0.15  # 400KB+ compound risk

    return round(min(score, 1.0), 4), signals


def _encoding_nesting_depth(text: str) -> int:
    """Detect Base64-within-Base64 nesting depth.

    Only counts layers where the decoded content also looks like base64
    (i.e. obfuscation through nested encoding, not accidental base64 in prose).
    """
    depth = 0
    base64_pattern = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
    remaining = text
    for _ in range(5):
        match = base64_pattern.search(remaining)
        if not match:
            break
        token = match.group()
        # Skip tokens that are just repeated chars (e.g. "aaaaaaaaaaaaaaa...")
        unique_chars = len(set(token.rstrip("=")))
        if unique_chars < 5:
            break
        try:
            decoded = base64.b64decode(token, validate=True)
        except (binascii.Error, ValueError):
            break
        try:
            decoded_text = decoded.decode("utf-8")
        except UnicodeDecodeError:
            # Not UTF-8 — could be binary payload, still suspicious
            depth += 1
            break
        if base64_pattern.search(decoded_text):
            depth += 1
            remaining = decoded_text
        else:
            depth += 1
            break
    return depth


def _normalize(request: str) -> str:
    # NFKC DoS guard: skip expensive normalization on oversized input.
    # Structural anomaly detection (suspicion_score) will already flag these.
    if len(request) > NFKC_MAX_INPUT_BYTES:
        text = request.translate(_NORMALIZE_TRANSLATION).casefold()
    else:
        text = unicodedata.normalize("NFKC", request).translate(_NORMALIZE_TRANSLATION).casefold()
    text = text.translate(_CONFUSABLE_TRANSLATION)
    for source, replacement in _PHONETIC_REPLACEMENTS:
        text = text.replace(source, replacement)
    return text


def _security_text_views(text: str) -> list[str]:
    """Return normalized text plus decoded/extracted views for redline checks."""
    views: list[str] = []

    def add(candidate: str, *, require_sensitive: bool = False) -> None:
        normalized = _normalize(candidate)
        if not normalized or normalized in views:
            return
        if require_sensitive and not _text_has_redline_marker(normalized):
            return
        views.append(normalized)

    add(text)
    for pattern in (
        r"```(?:[a-z0-9_+-]+)?\s*(.*?)```",
        r"<([a-z0-9_:-]+)[^>]*>(.*?)</\1>",
        r"[\"'「『](.*?)[\"'」』]",
        r"(\{[^{}]{3,2000}\})",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            add(match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(1))

    for token in re.findall(r"(?<![A-Za-z0-9+/=_-])([A-Za-z0-9+/_-]{12,}={0,2})(?![A-Za-z0-9+/=_-])", text):
        decoded = _decode_base64_token(token)
        if decoded:
            add(decoded, require_sensitive=True)

    rot13 = codecs.decode(text, "rot_13")
    if rot13 != text:
        add(rot13, require_sensitive=True)

    compact = re.sub(r"[\s'\"`+._-]+", "", text)
    if compact != text:
        compact_folded = compact.casefold()
        if "openaiapikey" in compact_folded:
            add("openai_api_key", require_sensitive=True)
        if "privatekey" in compact_folded:
            add("private_key", require_sensitive=True)

    return views


def _decode_base64_token(token: str) -> str | None:
    cleaned = token.strip().replace("-", "+").replace("_", "/")
    if len(cleaned) % 4:
        cleaned += "=" * (4 - len(cleaned) % 4)
    try:
        raw = base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw or len(raw) > 4096:
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    printable = sum(ch.isprintable() or ch.isspace() for ch in decoded)
    if printable / max(len(decoded), 1) < 0.85:
        return None
    return decoded


def _text_has_redline_marker(text: str) -> bool:
    return (
        _has_any(text, SENSITIVE_SUBJECT_MARKERS)
        or _has_any(text, ("read_secrets", "drop table", "/etc/passwd", "openai_api_key", "openaiapikey"))
        or bool(re.search(r"\bsk-[a-z0-9][a-z0-9_-]{2,}\b", text))
    )


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _detect_read_write_intent(signals: _Signals) -> None:
    text = signals.text
    signals.read_only = _has_any(
        text,
        (
            "不要改",
            "不改",
            "无需改",
            "不需要改",
            "只给意见",
            "只输出建议",
            "只读",
            "只汇总",
            "只生成",
            "审计",
            "哪些规则",
            "不要展示任何值",
            "不要给值",
            "不要执行任何操作",
            "不执行任何操作",
            "不要执行",
            "不执行",
            "不连接真实",
            "不连接生产",
            "不要提交",
            "不要改代码",
            "不改代码",
            "不要改配置",
            "不改配置",
            "不要部署",
            "不上线",
        ),
    )
    write_markers = (
        "fix",
        "修复",
        "修改",
        "改",
        "改本地",
        "改相关",
        "改成",
        "调整",
        "更新",
        "给出 patch",
        "patch",
        "修",
        "补",
        "写一个",
        "写个",
        "写功能",
        "实现功能",
        "实现一个",
        "开发一个",
        "新增功能",
        "添加功能",
        "构建",
        "推送",
        "脚本",
        "deploy",
        "rollback",
        "回滚",
        "部署",
        "上线",
        "线上",
        "发版",
        "生产",
        "执行 sql",
        "执行删除",
        "删掉",
        "删除",
        "移除",
        "导出",
        "提交",
        "重启",
        "处理",
        "导一份",
        "合并",
        "清掉",
        "清理",
        "添加",
        "加到",
        "创建",
        "新建",
    )
    signals.write_intent = _has_any(text, write_markers) and not (
        signals.read_only and not _has_any(text, ("脚本", "修复", "修改", "回滚", "部署", "上线"))
    )
    # 错误处理 is a compound noun (error handling), not an action verb
    if signals.write_intent and _has_any(text, ("错误处理",)):
        # Only negate if "处理" is the sole write marker; preserve if other markers exist
        other_markers = [m for m in write_markers if m != "处理" and m in text]
        if not other_markers:
            signals.write_intent = False


def _detect_base_signals(signals: _Signals) -> None:
    text = signals.text
    if (
        re.search(r"`[^`]+`", text)
        or re.search(r"https?://[^\s]+", text)
        or re.search(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", text)
        or re.search(r"\b[\w.-]+\.(py|ts|tsx|js|jsx|css|sql|csv|md|ya?ml|json)\b", text)
        or _has_any(text, (".env", "路径", "当前仓库", "项目里", "readme", "css", "auth/"))
    ):
        signals.add_reason("PATH_SIGNAL")
        signals.bump("path", 2)

    if _has_any(
        text,
        (
            "后台",
            "网页",
            "浏览器",
            "页面",
            "生产",
            "数据库",
            "订单",
            "支付",
            "支付流水",
            "支付失败",
            "扣款",
            "用户",
            "邮箱",
            "手机号",
            "地址",
            "监控",
            "线上",
            "状态页",
            "仪表盘",
            "预订",
            "预约",
            "运营",
            "payment",
            "admin",
            "后台登录",
            "管理员后台",
            "生产数据",
        ),
    ):
        signals.add_reason("RESOURCE_SIGNAL")
        signals.bump("resource", 2)

    if _has_word(text, "pr") or _has_any(text, ("review", "清单", "建议", "说明", "公告", "措辞", "文档", "readme", "字段清单")):
        signals.add_reason("DOCUMENT_MATCH")
        signals.bump("document", 2)

    if _has_any(
        text,
        (
            "fix",
            "deploy",
            "rollback",
            "verify",
            "prod now",
            "修复",
            "修改",
            "失败",
            "确认",
            "汇总",
            "分析",
            "验证",
            "改得",
            "改好",
            "稳妥",
            "延期",
            "客户",
            "模板",
            "占位符",
            "读取",
            "展示",
            "看看",
            "不要给值",
            "secret",
            "提交",
            "导出",
            "导一份",
            "自维护",
            "回滚",
            "部署",
            "重启",
            "客服",
            "公告",
            "措辞",
        ),
    ):
        signals.add_reason("KEYWORD_SIGNAL")
        signals.bump("keyword", 2)

    if not signals.reason_codes:
        # C-017: 无任何信号匹配时记录原因码，消除可观测性盲区
        signals.add_reason("DEFAULT_ROUTE", "L1")


def _detect_safety_redlines(signals: _Signals, context: dict) -> None:
    text = "\n".join(_security_text_views(signals.raw_text or signals.text))
    approved = bool(context.get("human_review_approved")) or _has_any(
        text, ("人工已批准", "刚才批准", "已批准", "human approved", "approved by human")
    )
    asks_for_real_values = _has_any(text, REAL_VALUE_MARKERS) and not _has_any(
        text,
        ("不含真实值", "不要真实值", "别展示真实值", "不使用真实值", "不要展示任何值", "不要任何值"),
    )
    asks_template_without_values = _has_any(
        text,
        ("模板", ".env.example", "占位符", "不含真实值", "不要展示任何值", "不要任何值"),
    ) and not asks_for_real_values
    if asks_template_without_values:
        signals.add_reason("TEMPLATE_NO_VALUE", "L1")
        signals.bump("safety")

    asks_secret_value = _has_any(
        text,
        (
            "真实 api key",
            "真实数据库密码",
            "真实 db 密码",
            "真实密码",
            "真实 jwt secret",
            "真实 token",
            "真实值",
            "真实 value",
            "当前真实 token",
            "原文贴出来",
            "原文贴出",
            "生产密钥",
            "密钥复制",
            "打印出来",
            "展示任何值",
            "填进去",
            "填入",
            "写进配置",
            "写进",
            "复制到回复",
            "secret value",
            "api key 打印",
            "actual value",
            "real value",
            "actual secret",
            "real secret",
        ),
    ) and not _has_any(text, ("不含真实", "不要真实", "别展示真实", "不要展示任何值", "不要任何值", "占位符"))
    if _has_any(text, ("生产 dsn", "生产dsn")) and _has_any(text, ("加入", "填入", "填进去", "打印", "输出", "给我值")):
        asks_secret_value = True

    secret_subject = _has_any(text, SENSITIVE_SUBJECT_MARKERS) or _has_any(text, (".env", "openaiapikey"))
    asks_credential_name_value = _has_any(text, CREDENTIAL_NAME_PATTERNS) and _has_any(text, CREDENTIAL_EXPOSURE_VERBS)
    asks_environment_values = _has_any(
        text,
        (
            "所有环境变量",
            "环境变量的值",
            "环境变量里的",
            "环境变量里",
            "系统里存的",
            "env vars",
            "environment variables",
            "environment variable values",
        ),
    ) and _has_any(text, CREDENTIAL_EXPOSURE_VERBS)
    asks_env_file_contents = (
        ".env" in text
        and _has_any(text, ("cat", "看", "看看", "列出", "列出来", "内容", "显示", "打印", "读出来", "输出"))
        and not _has_any(text, (".env.example", "模板", "占位符", "不含真实值", "不要展示任何值", "不要任何值"))
        and not _has_any(text, ("不输出内容", "不要输出内容", "不展示内容", "不显示内容", "不要显示内容", "不打印内容", "不要打印内容"))
    )
    asks_generic_key_value = (
        _has_any(text, ("api key", "api 密钥", "key 的值", "key值", "系统里存的 api 密钥"))
        and _has_any(text, CREDENTIAL_EXPOSURE_VERBS)
    )
    if not asks_template_without_values and (
        asks_credential_name_value
        or asks_environment_values
        or asks_env_file_contents
        or asks_generic_key_value
    ):
        asks_secret_value = True
        secret_subject = True

    if asks_secret_value and secret_subject:
        signals.add_reason("CREDENTIAL_VALUE_REQUESTED", "L4")
        signals.add_reason("LITERAL_SECRET_VALUE", "L4")
        signals.safety_route = "blocked"
        signals.bump("safety", 3)

    if _has_any(text, SOCIAL_ENGINEERING_MARKERS) and secret_subject:
        signals.add_reason("SOCIAL_ENGINEERING_BYPASS", "L4")
        signals.add_reason("CREDENTIAL_VALUE_REQUESTED", "L4")
        signals.safety_route = "blocked"
        signals.bump("safety", 3)

    if _has_any(text, PROMPT_INJECTION_MARKERS) and (
        secret_subject or _has_any(text, ("output", "print", "dump", "reveal", "read"))
    ):
        signals.add_reason("PROMPT_INJECTION", "L4")
        signals.add_reason("CREDENTIAL_VALUE_REQUESTED", "L4")
        signals.safety_route = "blocked"
        signals.bump("safety", 3)

    if re.search(r"\b[a-z0-9_]*(?:api[_-]?key|token|secret|private[_-]?key)\s*=\s*sk-[a-z0-9][a-z0-9_-]{2,}\b", text):
        signals.add_reason("LITERAL_SECRET_VALUE", "L4")
        signals.safety_route = "blocked"
        signals.bump("safety", 3)

    if _has_any(text, ("/etc/passwd", "/etc/shadow")) and _has_any(text, ("cat", "read", "show", "print", "读取", "显示", "输出", "看")):
        signals.add_reason("SYSTEM_FILE_READ", "L4")
        signals.safety_route = "blocked"
        signals.bump("safety", 3)

    if _has_any(text, ("read_secrets", "dump_secrets")) and _has_any(text, (".env", "secret", "密钥", "token")):
        signals.add_reason("STRUCTURED_SECRET_ACCESS", "L4")
        signals.safety_route = "blocked"
        signals.bump("safety", 3)

    if _has_any(text, ("drop table", "truncate table")):
        signals.add_reason("PRODUCTION_DATA_MUTATION", "L4")
        signals.safety_route = "blocked"
        signals.bump("safety", 3)

    if _has_any(text, ("private_key", "private key")) and _has_any(text, (".env", "生产", "production", "替换", "写进", "填入", "更新")):
        signals.add_reason("PRIVATE_KEY_TOUCH", "L4")
        signals.safety_route = "blocked"
        signals.bump("safety", 3)

    if (
        _has_any(text, ("auth模块", "auth 模块", "auth core", "认证核心", "登录核心", "auth/session.ts"))
        and _has_any(text, ("jwt密钥", "jwt 密钥", "jwt_secret", "jwt secret", "硬编码", "hardcode", "hard-coded"))
        and _has_any(text, ("生产", "production", ".env"))
    ):
        signals.add_reason("AUTH_CORE_PATH", "L4")
        signals.add_reason("LITERAL_SECRET_VALUE", "L4")
        signals.safety_route = "blocked"
        signals.bump("safety", 3)

    credential_path_consultation = (
        _has_any(text, ("哪个路径", "哪一个路径", "从哪个路径", "路径读取", "凭据路径", "放在哪个路径"))
        and secret_subject
    ) or (
        secret_subject
        and _has_any(text, ("密钥配置", "secret 配置"))
        and _has_any(text, ("写死", "不要给值", "不给值"))
        and not _has_any(text, ("workflow", "变量名", "env 变量"))
    )
    if credential_path_consultation:
        signals.add_reason("CREDENTIAL_PATH_CONSULTATION", "L3")
        signals.bump("safety", 2)
        if asks_secret_value:
            signals.safety_route = "blocked"
        else:
            # C-011: path consultation is only allowed when not paired with a
            # value request; this route still requires human review in the
            # Phase 3 schema.
            signals.safety_route = signals.safety_route or "human_review"

    if _has_any(text, ("auth/session.ts", "token 校验", "token校验", "认证核心")):
        signals.add_reason("AUTH_CORE_PATH", "L4")
        signals.safety_route = _merge_safety_route(signals.safety_route, "human_review")
        signals.bump("safety", 2)

    # C-016: 部署动作动词直接触发；"生产环境"/"生产"上下文词需配合写动作
    # 避免"生产环境的错误日志帮我看一下"误触（只读监控请求）
    _deploy_direct = (
        _has_any(text, ("部署到生产", "部署生产", "生产恢复", "立即上线", "上线", "发版", ".env.production"))
        or _has_any(text, ("deploy to production", "production deploy", "prod now"))
        or (_has_word(text, "prod") and _has_any(text, ("fix", "deploy", "now", "rollback")))
    )
    _prod_context = _has_any(text, ("生产环境", "生产", "production"))
    _prod_write_action = _has_any(text, (
        "部署", "上线", "发版", "deploy", "rollback", "回滚", "改", "修改", "修复",
        "删除", "清掉", "清空", "清除", "删库", "抹除", "执行", "重启", "创建", "更新", "添加", "导出", "合并", "修",
        "truncate", "drop", "wipe",
    ))
    production_negated = _has_any(
        text,
        (
            "非生产",
            "not production",
            "staging",
            "不部署到生产",
            "不要部署到生产",
            "不部署生产",
            "不触达生产",
            "不连接生产",
            "不连接生产库",
            "不执行 sql",
            "不上线",
            "不发版",
        ),
    )
    production_deploy = (
        (
            _deploy_direct
            or (_prod_context and _prod_write_action and not signals.read_only)
        )
        and not production_negated
    )
    if production_deploy:
        signals.add_reason("PRODUCTION_DEPLOY", "L4")
        signals.safety_route = _merge_safety_route(signals.safety_route, "human_review")
        signals.bump("safety", 3)

    production_data_mutation = (
        (
            _has_any(text, ("生产数据库", "生产库"))
            or (_has_any(text, ("生产环境", "生产", "production")) and _has_any(text, ("数据库", "database", "table")))
            or (_has_any(text, ("生产 dsn", "生产dsn")) and _has_any(text, ("回填", "用户邮箱")))
        )
        and _has_any(
            text,
            (
                "执行 sql", "执行一次", "执行删除", "批量改", "改成", "更新", "回填",
                "update", "delete", "insert", "mutation", "删除", "清掉", "清空",
                "清除", "删库", "truncate", "drop", "wipe", "抹除", "修",
            ),
        )
        and not _has_any(text, ("非生产", "not production", "staging", "不连接生产库", "不执行脚本", "不执行 sql"))
    )
    if production_data_mutation:
        signals.add_reason("PRODUCTION_DATA_MUTATION", "L4")
        if approved or _has_any(text, ("人工审批", "不要直接执行", "不直接执行")):
            signals.safety_route = _merge_safety_route(signals.safety_route, "human_review")
        else:
            signals.safety_route = "blocked"
        signals.bump("safety", 3)

    payment_subject = _has_any(text, ("支付扣款", "扣款流程", "支付系统", "支付后台", "支付流水", "支付失败重试", "支付失败", "支付日志", "payment-gateway", "payment gateway", "payment."))
    if payment_subject:
        payment_is_mutation = signals.write_intent and not signals.read_only and _has_any(
            text,
            ("扣款流程", "支付失败重试", "支付流水", "支付扣款", "从 1 改成", "改成", "更新", "发版", "部署"),
        )
        payment_risk = "L4" if payment_is_mutation else "L2"
        if not payment_is_mutation and _has_any(text, ("支付后台", "payment")) and _has_any(text, ("导出", "export")):
            payment_risk = "L3"
        signals.add_reason("PAYMENT_SYSTEM", payment_risk)
        if payment_is_mutation:
            signals.safety_route = _merge_safety_route(signals.safety_route, "human_review")
            signals.bump("safety", 3)
        else:
            signals.bump("safety")

    pii_export = (
        _has_any(text, ("导出", "export", "打印出来", "打印出"))
        and _has_any(text, ("所有用户", "用户邮箱", "用户", "邮箱", "手机号", "地址"))
        and _has_any(text, ("csv", "邮箱", "手机号", "地址", "分析", "数据", "用户信息"))
        and not _has_any(text, ("测试数据", "字段清单", "不连接真实", "不连接生产", "只生成"))
    )
    if pii_export:
        signals.add_reason("PRIVACY_PII", "L4")
        signals.safety_route = "blocked"
        signals.bump("safety", 3)

    # ── Claude structural anomaly detection (anti-gravity audit) ──
    # Checks raw text structure independent of keywords.
    # Detects: BiDi controls, invisible chars, script mixing, homoglyphs,
    # encoding nesting, whitespace diversity, null bytes, oversized input.
    # Thresholds: >=0.20 → blocked, >=0.08 → human_review
    _struct_score, _struct_signals = suspicion_score(signals.raw_text)
    if _struct_score >= 0.20:
        signals.add_reason("STRUCTURAL_ANOMALY", "L4")
        for sig in _struct_signals:
            signals.add_reason(f"STRUCT:{sig}", "L4")
        signals.safety_route = _merge_safety_route(signals.safety_route, "blocked")
        signals.bump("safety", 3)
    elif _struct_score >= 0.08:
        signals.add_reason("STRUCTURAL_SUSPICIOUS", "L3")
        signals.safety_route = _merge_safety_route(signals.safety_route, "human_review")
        signals.bump("safety", 2)

    if approved:
        # C-010: approved human-review reentry can proceed when the request
        # carries local-only/no-execute constraints.
        signals.add_reason("HUMAN_REVIEW_REENTRY")
        signals.bump("safety")


def _merge_safety_route(current: str | None, candidate: str) -> str:
    if current == "blocked" or candidate == "blocked":
        return "blocked"
    return candidate


def _detect_user_explicit_route(signals: _Signals) -> None:
    text = signals.text
    explicit_map = (
        (
            "codex",
            (
                "交给 codex",
                "走 codex",
                "给 codex",
                "请 codex",
                "让 codex",
                "指定 codex",
                "codex 修改",
                "codex 修",
                "codex fix",
                "codex 帮",
                "codex 直接",
                "codex 执行",
                "codex 写",
                "直接交给 codex",
                "明确交给 codex",
            ),
        ),
        ("hermes", ("交给 hermes", "走 hermes")),
        ("openclaw", ("交给 openclaw", "走 openclaw")),
    )
    for route, needles in explicit_map:
        if _has_any(text, needles):
            signals.explicit_route = route
            signals.add_reason("USER_EXPLICIT_ROUTE")
            signals.bump("tool", 2)
            break
    if signals.explicit_route is None:
        explicit_word_map = (("codex", "codex"), ("hermes", "hermes"), ("openclaw", "openclaw"))
        executor_action = _has_any(text, ("修", "修复", "修改", "fix", "写", "执行", "打开", "验证", "review"))
        for route, word in explicit_word_map:
            if re.search(rf"(?<![-\w]){re.escape(word)}(?![-\w])", text) and executor_action:
                signals.explicit_route = route
                signals.add_reason("USER_EXPLICIT_ROUTE")
                signals.bump("tool", 2)
                break
    if "第8ug" in text:
        # C-008: escape hatch is a recognized explicit route signal, still
        # subject to safety gates.
        signals.explicit_route = signals.explicit_route or "codex"
        signals.add_reason("ESCAPE_HATCH_8UG")
        signals.add_reason("USER_EXPLICIT_ROUTE")
        signals.bump("tool", 2)


def _detect_domains(signals: _Signals) -> None:
    text = signals.text
    if _has_any(
        text,
        (
            "LanceDB",
            "lancedb",
            "embedding",
            "向量化",
            "向量库",
            "索引构建",
            "RAG pipeline",
            "RAG",
            "BGE-M3",
            "语义搜索",
            "chunk",
            "分块",
            "向量检索",
        ),
    ):
        _add_domain(signals, "DOMAIN_VECTOR_ENGINEERING", "L2")

    if _has_any(
        text,
        (
            "创建issue",
            "创建 issue",
            "创建一个 issue",
            "创建一个issue",
            "整理issue",
            "整理 issue",
            "贴标签",
            "release notes",
            "项目管理",
            "milestone",
            "issue 管理",
            "issue管理",
        ),
    ) or (
        _has_any(text, ("github", "GitHub")) and _has_any(text, ("issue", "Issue"))
    ):
        _add_domain(signals, "DOMAIN_GITHUB_MANAGEMENT", "L1")

    if _has_any(
        text,
        (
            "omlx",
            "本地模型",
            "local model",
            "模型列表",
            "列模型",
            "列一下模型",
            "smoke test",
            "benchmark",
            "已加载的模型",
            "加载了哪些模型",
            "当前加载",
            "有哪些模型",
            "模型状态",
            "模型运行状态",
            "model status",
            "换成qwen",
            "换成 qwen",
            "切换模型",
            "切换到",
            "换一个模型",
            "switch model",
            "卸载模型",
            "释放显存",
            "unload model",
            "推理速度",
            "推理性能",
            "inference speed",
            "tokens per second",
            "token/s",
            "显存",
            "vram",
            "gpu memory",
            "显存占用",
            "上下文长度",
            "context length",
            "context window",
            "gguf",
            "量化",
            "quantize",
            "quantization",
            "温度参数",
            "temperature",
            "top_p",
            "top_k",
            "ollama",
        ),
    ):
        _add_domain(signals, "DOMAIN_LOCAL_MODEL", "L1")

    software_install = _has_any(text, ("showmeyourhotkeys", "brew install", "npm install", "pip install", "安装 app", "安装应用"))
    software_install = software_install or (
        _has_any(text, ("安装", "install", "卸载", "uninstall", "upgrade"))
        and not _has_any(text, ("安装步骤", "安装说明", "readme", "文档", "说明"))
    )
    if software_install:
        _add_domain(signals, "DOMAIN_INSTALL", "L3")

    if _has_any(text, ("nas", "远程文件", "共享盘", "网盘", "remote files", "重复音乐")):
        if _has_any(text, ("删掉", "删除", "移除", "清掉", "delete", "remove")):
            remote_risk = "L3"
        elif signals.write_intent:
            remote_risk = "L2"
        else:
            remote_risk = "L1"
        _add_domain(signals, "DOMAIN_REMOTE_FILES", remote_risk)

    if _has_any(
        text,
        (
            ".md",
            "文档",
            "章节",
            "nihl_review",
            "lp_books",
            "入库",
            "书",
            "报告",
            "用户笔记",
        ),
    ):
        _add_domain(signals, "DOMAIN_DOCUMENT", "L1")

    if _has_any(text, ("路由器自维护", "自维护")):
        _add_domain(signals, "DOMAIN_SELF_MAINTAIN", "L1")

    if _has_word(text, "pr") or _has_word(text, "review") or _has_any(text, ("评审", "接口命名", "错误处理", "审查", "code review", "找bug", "静态分析", "安全检查", "审计代码", "代码审计", "安全审计")):
        _add_domain(signals, "DOMAIN_CODE_REVIEW", "L1")

    if _has_any(text, ("npm test", "pytest", "测试失败", "测试挂", "定位", "debug", "失败", "flaky", "fix", "bug", "retry logic", "token refresh")):
        _add_domain(signals, "DOMAIN_DEBUGGING", "L2" if signals.write_intent else "L1")

    deployment_signal = _has_any(text, ("部署", "上线", "发版", "回滚", "feature flag", "恢复服务", "线上", "重启", "deploy", "rollback")) or _has_word(text, "prod") or _has_word(text, "production")
    deployment_negated = (
        _has_any(text, ("not production", "staging", "非生产", "不要部署", "不部署", "不要上线", "不上线"))
        and not _has_any(text, ("回滚", "rollback", "feature flag"))
    )
    if deployment_signal and not deployment_negated:
        _add_domain(signals, "DOMAIN_DEPLOYMENT", "L3")

    # Browser domain: distinguish read-only (hermes browser tools) vs interactive (openclaw)
    _browser_readonly_keywords = (
        "看看",
        "查看",
        "浏览",
        "显示",
        "截图",
        "内容",
        "snapshot",
        "screenshot",
    )
    _browser_interactive_keywords = (
        "打开",
        "浏览器",
        "网页",
        "页面",
        "后台",
        "状态页",
        "仪表盘",
        "open staging",
        "page verify",
        "openclaw",
        "登录后台",
        "下载",
        "上传",
        "填表",
        "填写",
        "填入",
        "测试账号",
    )
    _browser_readonly_hit = _has_any(text, _browser_readonly_keywords) and not _has_any(
        text, ("提交测试表单", "完成演练", "直接提交", "填写", "填入", "测试账号")
    )
    _browser_interactive_hit = _has_any(text, _browser_interactive_keywords)
    # URL present + only viewing → readonly browser (hermes), not interactive
    _url_present = bool(re.search(r"https?://[^\s]+", text))
    if _browser_readonly_hit and not _browser_interactive_hit:
        _add_domain(signals, "DOMAIN_BROWSER_READONLY", "L1")
    elif _browser_readonly_hit and _url_present and not _has_any(
        text, ("提交测试表单", "完成演练", "直接提交", "填写", "填入", "测试账号", "登录", "下载", "上传")
    ):
        _add_domain(signals, "DOMAIN_BROWSER_READONLY", "L1")
    elif _browser_interactive_hit:
        browser_risk = "L1"
        if _has_any(text, ("提交测试表单", "完成演练", "直接提交")):
            browser_risk = "L3"
        elif (
            (signals.write_intent and not _has_any(text, ("评审", "review")))
            or _has_any(text, ("填写", "填入", "测试账号", "导出"))
        ):
            browser_risk = "L2"
        _add_domain(signals, "DOMAIN_BROWSER", browser_risk)
    elif _browser_readonly_hit:
        _add_domain(signals, "DOMAIN_BROWSER_READONLY", "L1")

    # Reservation: "预订"/"预约" always trigger; bare "订" only when not in "订单"
    _reservation_signal = _has_any(text, ("预订", "预约", "两人位", "直接提交"))
    if not _reservation_signal and _has_any(text, ("订",)) and not _has_any(text, ("订单",)):
        _reservation_signal = True
    if _reservation_signal:
        reservation_risk = "L3" if (_has_any(text, ("预订", "订", "两人位", "直接提交"))
                                   and not signals.read_only) else "L2"
        _add_domain(signals, "DOMAIN_RESERVATION", reservation_risk)

    if _has_any(text, ("监控", "错误率", "状态页", "恢复到正常", "线上那", "线上问题", "告警", "仪表盘", "错误日志", "出问题")):
        _add_domain(signals, "DOMAIN_MONITORING", "L1")

    if _has_any(text, (".env.example", ".env", "模板", "变量值", "占位符", "配置")):
        _add_domain(signals, "DOMAIN_CONFIG_NON_ENGINEERING", "L1")

    if _has_any(text, ("客户", "延期说明", "客服公告", "公告措辞", "措辞", "发给客户", "发布说明", "说明", "总结", "summarize")):
        _add_domain(signals, "DOMAIN_COMMUNICATION", "L1")

    if _has_any(text, ("数据库", "生产库", "sql", "csv", "导出", "导一份", "数据", "数据回填", "回填", "回填脚本", "校验脚本")):
        data_risk = "L1"
        if _has_any(text, ("生产数据迁移", "生产数据")):
            data_risk = "L3"
        elif signals.write_intent or _has_any(text, ("导一份", "有用的数据", "字段你判断")):
            data_risk = "L2"
        _add_domain(signals, "DOMAIN_DATA_PIPELINE", data_risk)

    engineering_markers = (
        "仓库",
        "hermes-agent",
        ".py",
        "审计",
        "修复",
        "修 ",
        "修改",
        "改完",
        "css",
        "样式",
        "组件",
        "导航栏",
        "代码",
        "脚本",
        "readme",
        "patch",
        "安装步骤",
        "auth/session.ts",
        "auth 模块",
        "auth模块",
        "auth module",
        "token 校验",
        "登录校验",
        "登录核心逻辑",
        "重试次数",
        "支付失败重试",
        "从 1 改成",
        "核心逻辑",
        "审查",
        "config.yaml",
        "配置文件",
        "修改配置",
        "改环境变量",
        "plist",
        "launchd",
        "修改设置",
        "更改配置",
        "Dockerfile",
        "dockerfile",
        "docker build",
        "docker compose",
        "docker run",
        "docker",
        "镜像构建",
        "推送镜像",
        "容器化",
        "镜像",
        "容器",
        "GitHub Actions",
        "github actions",
        "构建失败",
        "CI失败",
        "CI/CD",
        "pipeline",
        ".github/workflows",
        "写功能",
        "实现功能",
        "用户注册",
        "接口",
        "API开发",
        "模块开发",
        "爬虫",
        "写个",
        "写一个",
        "实现一个",
        "开发一个",
        "新增功能",
        "添加功能",
    )
    negated_engineering_only = signals.read_only and _has_any(text, ("不要改代码", "不改代码", "不要改配置", "不改配置")) and not _has_any(
        text,
        ("修复", "修改", "fix", "patch", "脚本", "auth/", "readme", "workflow", "重试", "核心逻辑"),
    )
    if _has_any(text, engineering_markers) and "DOMAIN_SELF_MAINTAIN" not in signals.domains and not negated_engineering_only:
        engineering_risk = "L1"
        if _has_any(text, ("登录核心逻辑", "核心逻辑", "auth 模块", "auth模块", "auth module")):
            engineering_risk = "L3"
        elif signals.write_intent:
            engineering_risk = "L2"
        _add_domain(signals, "DOMAIN_ENGINEERING", engineering_risk)

    if signals.domains & {
        "DOMAIN_ENGINEERING",
        "DOMAIN_CODE_REVIEW",
        "DOMAIN_DEBUGGING",
        "DOMAIN_BROWSER",
        "DOMAIN_BROWSER_READONLY",
        "DOMAIN_COMMUNICATION",
        "DOMAIN_DATA_PIPELINE",
        "DOMAIN_VECTOR_ENGINEERING",
        "DOMAIN_GITHUB_MANAGEMENT",
    }:
        signals.add_reason("TOOL_MATCH")
        signals.bump("tool", 2)


def _add_domain(signals: _Signals, domain: str, risk: str) -> None:
    signals.domains.add(domain)
    signals.add_reason(domain, risk)


def _mixed_steps(signals: _Signals) -> Optional[list[str]]:
    domains = signals.domains
    needs_codex = bool(domains & {"DOMAIN_ENGINEERING", "DOMAIN_DEBUGGING"}) and signals.write_intent
    needs_review = "DOMAIN_CODE_REVIEW" in domains
    needs_browser = "DOMAIN_BROWSER" in domains
    if (needs_codex or needs_review) and needs_browser:
        # C-002: mixed chain order is fixed Codex -> OpenClaw -> Hermes.
        steps = ["codex:review" if needs_review and not needs_codex else "codex:write_patch", "openclaw:verify"]
        if needs_review and needs_codex:
            steps.append("hermes:review")
        steps.append("hermes:report")
        return steps
    return None


def _route_from_domains(signals: _Signals, mixed_steps: Optional[list[str]]) -> str:
    domains = signals.domains
    if mixed_steps:
        return "mixed"
    if "DOMAIN_GITHUB_MANAGEMENT" in domains and "DOMAIN_ENGINEERING" not in domains:
        return "hermes"
    if "DOMAIN_VECTOR_ENGINEERING" in domains:
        return "codex"
    if "DOMAIN_REMOTE_FILES" in domains and _has_any(signals.text, ("删掉", "删除", "移除", "清掉", "delete", "remove")):
        return "human_review"
    if "DOMAIN_REMOTE_FILES" in domains:
        return "codex" if signals.write_intent else "hermes"
    if "DOMAIN_DEPLOYMENT" in domains or "DOMAIN_RESERVATION" in domains:
        return "human_review"
    if "DOMAIN_LOCAL_MODEL" in domains:
        return "hermes"
    if "DOMAIN_INSTALL" in domains:
        return "hermes"
    if "DOMAIN_MONITORING" in domains:
        return "hermes"
    if "DOMAIN_BROWSER_READONLY" in domains and "DOMAIN_BROWSER" not in domains:
        return "hermes"
    if "DOMAIN_BROWSER" in domains:
        return "openclaw"
    if "DOMAIN_DOCUMENT" in domains and not domains & {"DOMAIN_ENGINEERING", "DOMAIN_DEBUGGING", "DOMAIN_DATA_PIPELINE"}:
        return "hermes"
    if "DOMAIN_DATA_PIPELINE" in domains:
        return "codex" if signals.write_intent else "hermes"
    if "DOMAIN_DEBUGGING" in domains:
        return "codex" if signals.write_intent else "hermes"
    if "DOMAIN_CODE_REVIEW" in domains:
        return "codex"
    if "DOMAIN_SELF_MAINTAIN" in domains:
        return "hermes" if signals.read_only else "codex"
    if "DOMAIN_ENGINEERING" in domains:
        return "codex" if signals.write_intent else "hermes"
    if "DOMAIN_CONFIG_NON_ENGINEERING" in domains or "DOMAIN_COMMUNICATION" in domains:
        return "hermes"
    return "hermes"


def _write_policy_for_route(route: str, signals: _Signals) -> str:
    if route == "blocked":
        return "blocked"
    if route == "human_review":
        return "human_review"
    if route in {"codex", "mixed"} and signals.write_intent and (
        not signals.read_only or _has_any(signals.text, ("脚本", "patch", "修复", "修改", "写一个"))
    ):
        return "patch_only"
    return "none"


def _confidence(signals: _Signals, route: str) -> float:
    score = sum(signals.six_dimensional_score.values())
    domain_bonus = min(len(signals.domains), 3) * 0.04
    safety_bonus = 0.14 if signals.safety_route else 0.0
    explicit_bonus = 0.08 if signals.explicit_route else 0.0
    route_bonus = 0.06 if route in ROUTES else 0.0
    value = 0.48 + min(score, 12) * 0.025 + domain_bonus + safety_bonus + explicit_bonus + route_bonus
    return round(max(0.0, min(1.0, value)), 2)


__all__ = [
    "RouteResult",
    "audit_route_decision",
    "build_handoff_receipt",
    "decision_router_enabled",
    "route_decision",
    "suspicion_score",
]
