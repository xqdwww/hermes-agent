from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OCR_SKILL = REPO_ROOT / "skills" / "productivity" / "ocr-and-documents" / "SKILL.md"
CODEX_SKILL = REPO_ROOT / "skills" / "autonomous-ai-agents" / "codex" / "SKILL.md"


def test_document_validation_claim_safety_lesson_is_documented():
    text = OCR_SKILL.read_text(encoding="utf-8")

    assert "Validation Claim Safety" in text
    assert "Parser success is not full PDF validity" in text
    assert "PyMuPDF pass does not imply macOS Preview pass" in text
    assert "EOF/signature checks are separate from parser checks and render checks" in text
    assert "Target app compatibility must be checked" in text
    assert "Unknown or missing checks must be reported as unknown/warning, not pass" in text
    assert '"0 corrupted"' in text
    assert "passive observer plan" in text
    assert "claim ceiling to parser-readable" in text
    assert "document validation claim level must come from those validation events" in text


def test_long_run_watchdog_safety_lesson_is_documented():
    text = CODEX_SKILL.read_text(encoding="utf-8")

    assert "Long-Run Watchdog Safety" in text
    assert "waiting, running, partial, blocked, failed, and completed as separate states" in text
    assert "Timeout with partial output is partial, not success" in text
    assert "Repeated identical failures should block or inspect instead of blind retry" in text
    assert "Auth, session, quota, permission, and path errors are blocked states" in text
    assert "do not use one universal short timeout" in text
    assert "running or waiting task must not be serialized as PASS" in text
    assert "do not force push by default" in text
    assert "passive watchdog observer plan" in text
    assert "without starting, killing, or retrying processes" in text
    assert "passive runtime ledger exists" in text
    assert "verification freshness, remote write/tag verification" in text
