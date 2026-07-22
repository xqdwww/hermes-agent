from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]


def load(name: str, relative: str):
    path = ROOT / "skills" / "clashverge-openclash-static" / "scripts" / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SKILL = load("functional_skill", "clashverge_to_openclash.py")
BROWSER = load("browser_probe", "browser_service_probe.py")
DISNEY = load("disney_probe", "disney_service_probe.py")


def test_browser_command_is_profile_scoped_and_loopback_only(tmp_path: Path) -> None:
    command = BROWSER.build_chrome_command(
        Path("/Applications/Chrome"), tmp_path / "profile", 12345, 23456
    )
    assert "--proxy-server=http://127.0.0.1:12345" in command
    assert "--remote-debugging-address=127.0.0.1" in command
    assert "--remote-debugging-port=23456" in command
    assert not any("system" in item.lower() or "tun" in item.lower() for item in command)


def test_gemini_current_rich_textarea_selectors_are_supported() -> None:
    selectors = BROWSER.SERVICE_SPECS["gemini"]["inputs"]
    assert "rich-textarea div[contenteditable='true']" in selectors
    assert ".ql-editor[contenteditable='true']" in selectors


def test_safe_page_diagnostics_never_requests_dom_text_values() -> None:
    class FakeBrowser:
        expression = ""

        def evaluate(self, expression: str):
            self.expression = expression
            return {"origin": "https://gemini.google.com", "path": "/app"}

    browser = FakeBrowser()
    result = BROWSER.safe_page_diagnostics(browser, "gemini")
    assert result["origin"] == "https://gemini.google.com"
    assert "innerText:" not in browser.expression
    assert "outerHTML" not in browser.expression


def test_login_marker_has_priority_over_anonymous_prompt_box() -> None:
    class FakeBrowser:
        expression = ""

        def evaluate(self, expression: str):
            self.expression = expression
            return "LOGIN_REQUIRED"

    browser = FakeBrowser()
    assert BROWSER.safe_page_state(browser, "gpt") == "LOGIN_REQUIRED"
    assert "&& !hasInput" not in browser.expression


def test_spa_hydration_wait_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    states = iter(["AUTOMATION_UNAVAILABLE", "AUTOMATION_UNAVAILABLE", "READY"])
    monkeypatch.setattr(BROWSER, "safe_page_state", lambda *_args: next(states))
    monkeypatch.setattr(BROWSER.time, "sleep", lambda _seconds: None)
    assert BROWSER.wait_for_service_state(object(), "gemini", 1) == "READY"


def test_browser_proxy_attribution_requires_matching_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BROWSER, "control_exit_ip", lambda _port: "203.0.113.1")
    monkeypatch.setattr(BROWSER, "browser_exit_ip", lambda _browser: "203.0.113.1")
    assert BROWSER.verify_proxy_attribution(object(), 1234, b"k" * 32)
    monkeypatch.setattr(BROWSER, "browser_exit_ip", lambda _browser: "203.0.113.2")
    with pytest.raises(BROWSER.ProbeError, match="FAIL_BROWSER_PROXY_ATTRIBUTION"):
        BROWSER.verify_proxy_attribution(object(), 1234, b"k" * 32)


@pytest.mark.parametrize(
    ("raw", "result", "error"),
    [
        ("PASS", "PASS", None),
        ("NO_NEW_ANSWER", "FAIL", "FAIL_NO_NEW_ANSWER"),
        ("UNSUPPORTED_REGION", "FAIL", "FAIL_UNSUPPORTED_REGION"),
        ("LOGIN_REQUIRED", "FAIL", "FAIL_NODE_SESSION_REAUTH"),
        ("CHALLENGE", "UNKNOWN", "UNKNOWN_CHALLENGE"),
        ("RATE_LIMIT", "UNKNOWN", "UNKNOWN_ACCOUNT_RATE_LIMIT"),
        ("AUTOMATION_UNAVAILABLE", "UNKNOWN", "UNKNOWN_AUTOMATION_UNAVAILABLE"),
        ("TRANSPORT_FAILURE", "FAIL", "FAIL_TRANSPORT"),
    ],
)
def test_browser_outcomes_are_not_promoted(raw: str, result: str, error: str | None) -> None:
    assert BROWSER.map_outcome(raw) == (result, error)


def test_browser_report_rejects_cookie_and_raw_nonce() -> None:
    with pytest.raises(BROWSER.ProbeError, match="SENSITIVE_FIELD"):
        BROWSER.validate_safe_report({"nested": {"cookie": "x"}})
    with pytest.raises(BROWSER.ProbeError, match="RAW_NONCE"):
        BROWSER.validate_safe_report({"value": "GPT_NODE_TEST_abc"})


def baseline_proof() -> dict:
    return {
        "schema_version": 1,
        "status": BROWSER.BASELINE_SESSION_STATUS,
        "source_snapshot_id": "snapshot-x",
        "source_hash": "a" * 64,
        "browser_profile_reused": True,
        "browser_profile_recreated": False,
        "cookies_exported": False,
        "credentials_accessed": False,
        "system_proxy_changed": False,
        "tun_changed": False,
        "sidecar_started": False,
    }


def test_baseline_session_proof_is_snapshot_bound_and_non_sensitive(tmp_path: Path) -> None:
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(baseline_proof()), encoding="utf-8")
    loaded = BROWSER.load_baseline_session_proof(
        path, source_snapshot_id="snapshot-x", source_hash="a" * 64
    )
    assert loaded["status"] == BROWSER.BASELINE_SESSION_STATUS
    altered = baseline_proof()
    altered["source_hash"] = "b" * 64
    path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(BROWSER.ProbeError, match="PROOF_MISMATCH"):
        BROWSER.load_baseline_session_proof(
            path, source_snapshot_id="snapshot-x", source_hash="a" * 64
        )


def test_browser_probe_requires_existing_private_profile(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    with pytest.raises(BROWSER.ProbeError, match="PROFILE_MISSING"):
        BROWSER.validate_existing_profile(profile)
    profile.mkdir(mode=0o700)
    (profile / "Local State").write_text("", encoding="utf-8")
    BROWSER.validate_existing_profile(profile)
    profile.chmod(0o755)
    with pytest.raises(BROWSER.ProbeError, match="PERMISSIONS_NOT_PRIVATE"):
        BROWSER.validate_existing_profile(profile)


def test_single_node_restriction_or_reauth_does_not_stop_service() -> None:
    assert BROWSER.classify_node_outcome("UNSUPPORTED_REGION", 0) == (
        "FAIL", "FAIL_UNSUPPORTED_REGION", 0, False
    )
    assert BROWSER.classify_node_outcome("LOGIN_REQUIRED", 0) == (
        "FAIL", "FAIL_NODE_SESSION_REAUTH", 1, False
    )


def test_repeated_session_symptoms_stop_only_affected_service() -> None:
    first = BROWSER.classify_node_outcome("CHALLENGE", 0)
    assert first == ("UNKNOWN", "UNKNOWN_CHALLENGE", 1, False)
    second = BROWSER.classify_node_outcome("LOGIN_REQUIRED", first[2])
    assert second == ("UNKNOWN", "UNKNOWN_SESSION_INVALIDATED", 2, True)
    assert BROWSER.classify_node_outcome("RATE_LIMIT", 0) == (
        "UNKNOWN", "UNKNOWN_ACCOUNT_RATE_LIMIT", 0, True
    )


def test_disney_current_session_level_schema() -> None:
    payload = {
        "extensions": {
            "sdk": {
                "session": {
                    "location": {"countryCode": "JP"},
                    "inSupportedLocation": True,
                }
            }
        }
    }
    assert DISNEY.classify_graphql(payload) == ("JP", True)
    payload["extensions"]["sdk"]["session"]["location"]["inSupportedLocation"] = True
    del payload["extensions"]["sdk"]["session"]["inSupportedLocation"]
    assert DISNEY.classify_graphql(payload) is None


@pytest.mark.parametrize(
    "result",
    sorted(DISNEY.TERMINAL_RESULTS),
)
def test_disney_six_terminal_results_are_stable(result: str) -> None:
    assert result in {
        "PASS_SUPPORTED_REGION", "FAIL_FORBIDDEN_LOCATION", "FAIL_IP_BANNED",
        "FAIL_UNAVAILABLE", "FAIL_TRANSPORT", "UNKNOWN_RESPONSE_SCHEMA",
    }


def base_report() -> dict:
    return {
        "run_timestamp": "2026-07-22T10:00:00+08:00",
        "nodes": [{
            "name": "node-a",
            "services": {
                service: {
                    "raw_result": "UNKNOWN", "final_result": "UNKNOWN",
                    "override": None, "evidence": {},
                }
                for service in SKILL.SERVICE_KEYS
            },
        }],
    }


def manifest() -> dict:
    return {
        "source_snapshot_id": "snapshot-x",
        "source_hash": "a" * 64,
        "nodes": [{"exact_node_name": "node-a", "exact_node_id": "id-a"}],
    }


def functional(result: str, service: str = "gemini") -> dict:
    return {
        "service": service, "node": "node-a", "exact_node_id": "id-a",
        "source_snapshot_id": "snapshot-x", "source_hash": "a" * 64,
        "tested_at": "2026-07-22T10:01:00+08:00", "method": "web-v1",
        "result": result, "error_category": "" if result == "PASS" else "FAIL_REGION",
    }


def test_functional_pass_and_fail_apply_by_exact_snapshot_identity() -> None:
    report = SKILL.apply_functional_results_to_report(base_report(), [functional("PASS")], manifest())
    assert report["nodes"][0]["services"]["gemini"]["final_result"] == "DEFINITIVE_AUTOMATED_PASS"
    report = SKILL.apply_functional_results_to_report(base_report(), [functional("FAIL")], manifest())
    assert report["nodes"][0]["services"]["gemini"]["final_result"] == "DEFINITIVE_AUTOMATED_FAIL"
    mismatch = functional("PASS")
    mismatch["exact_node_id"] = "other"
    report = SKILL.apply_functional_results_to_report(base_report(), [mismatch], manifest())
    assert report["functional_results"]["applied"] == 0


def test_unsupported_region_keeps_specific_definitive_failure() -> None:
    failed = functional("FAIL")
    failed["error_category"] = "FAIL_UNSUPPORTED_REGION"
    report = SKILL.apply_functional_results_to_report(base_report(), [failed], manifest())
    result = report["nodes"][0]["services"]["gemini"]
    assert result["final_result"] == "DEFINITIVE_AUTOMATED_FAIL_UNSUPPORTED_REGION"


def test_manual_fail_conflicts_with_automated_pass_and_excludes_candidate() -> None:
    report = SKILL.apply_functional_results_to_report(base_report(), [functional("PASS")], manifest())
    manual = [{
        "service": "gemini", "node": "node-a", "exact_node_id": "id-a",
        "source_snapshot_id": "snapshot-x", "tested_at": "2026-07-22T10:02:00+08:00",
        "method": next(iter(SKILL.DEFINITIVE_MANUAL_METHODS)), "result": "FAIL",
    }]
    report = SKILL.apply_manual_results_to_report(report, manual, manifest())
    result = report["nodes"][0]["services"]["gemini"]
    assert result["final_result"] == "EVIDENCE_CONFLICT"
    assert result["evidence_conflict"] is True


def test_functional_loader_rejects_nested_sensitive_content(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "schema_version": 1, "results": [{"nested": {"token": "secret"}}]
    }), encoding="utf-8")
    with pytest.raises(SKILL.ConfigError, match="sensitive"):
        SKILL.load_functional_results([path])


def test_disney_loader_downgrades_transport_to_unknown(tmp_path: Path) -> None:
    path = tmp_path / "disney.json"
    path.write_text(json.dumps({
        "schema_version": 1, "service": "disney", "probe_method_version": "v2",
        "source_hash": "a" * 64,
        "nodes": [{
            "exact_node_name": "node-a", "exact_node_id": "id-a",
            "source_snapshot_id": "snapshot-x", "tested_at": "2026-07-22T10:01:00+08:00",
            "result": "FAIL_TRANSPORT",
        }],
    }), encoding="utf-8")
    assert SKILL.load_functional_results([path])[0]["result"] == "UNKNOWN"
