from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "clashverge_to_openclash.py"
spec = importlib.util.spec_from_file_location("verified_registry_converter", SCRIPT)
converter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["verified_registry_converter"] = converter
spec.loader.exec_module(converter)


def sample_config() -> dict:
    return {
        "proxies": [
            {
                "name": "🇨🇳台湾-住宅",
                "type": "ss",
                "server": "tw.example.invalid",
                "port": 1,
            },
            {
                "name": "🇯🇵日本-流媒体02",
                "type": "ss",
                "server": "jp.example.invalid",
                "port": 2,
            },
            {
                "name": "🇸🇬新节点",
                "type": "ss",
                "server": "sg.example.invalid",
                "port": 3,
            },
        ],
        "proxy-groups": [],
        "rules": [],
    }


def write_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: dict,
    entries: list[dict],
    *,
    key: bytes = b"verified-registry-test-key-0123456789",
) -> tuple[Path, Path]:
    registry_path = tmp_path / "verified-service-registry.json"
    registry_path.write_text(
        json.dumps({"schema_version": 1, "nodes": entries}), encoding="utf-8"
    )
    key_path = tmp_path / "source-identity.key"
    key_path.write_bytes(key)
    monkeypatch.setenv("OPENCLASH_VERIFIED_REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(converter, "DEFAULT_SOURCE_IDENTITY_KEY", key_path)
    return registry_path, key_path


def registry_entry(proxy: dict, key: bytes, *, service: str, tier: str, tested_at: str) -> dict:
    method = (
        "chatgpt_guest_generation"
        if service == "gpt"
        else "antigravity_inference"
    )
    return {
        "exact_node_id": converter.stable_node_identity(proxy, key),
        "node": proxy["name"],
        "service": service,
        "tier": tier,
        "enabled": True,
        "tested_at": tested_at,
        "method": method,
    }


def groups_by_name(config: dict) -> dict[str, dict]:
    return {group["name"]: group for group in config["proxy-groups"]}


def test_missing_registry_preserves_legacy_transform(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "OPENCLASH_VERIFIED_REGISTRY_PATH", str(tmp_path / "missing-registry.json")
    )
    result = converter.transform(sample_config())
    groups = groups_by_name(result)
    assert "🇨🇳台湾-住宅" in groups["GPT候选"]["proxies"]
    assert "🇨🇳台湾-住宅" in groups["Gemini候选"]["proxies"]
    assert "🇯🇵日本-流媒体02" not in groups["GPT候选"]["proxies"]


def test_registry_uses_identity_bound_order_and_manual_tiers(monkeypatch, tmp_path):
    data = sample_config()
    key = b"verified-registry-test-key-0123456789"
    entries = [
        registry_entry(
            data["proxies"][0],
            key,
            service="gpt",
            tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
        registry_entry(
            data["proxies"][1],
            key,
            service="gpt",
            tier="preferred",
            tested_at="2026-09-08T05:01:00+00:00",
        ),
        registry_entry(
            data["proxies"][2],
            key,
            service="gpt",
            tier="manual",
            tested_at="2026-09-08T05:02:00+00:00",
        ),
        registry_entry(
            data["proxies"][0],
            key,
            service="gemini",
            tier="preferred",
            tested_at="2026-09-08T05:03:00+00:00",
        ),
    ]
    write_registry(tmp_path, monkeypatch, data, entries, key=key)

    result = converter.transform(copy.deepcopy(data))
    groups = groups_by_name(result)
    assert groups["GPT候选"]["proxies"] == [
        "🇨🇳台湾-住宅",
        "🇯🇵日本-流媒体02",
    ]
    assert groups["GPT手动"]["proxies"] == [
        "🇨🇳台湾-住宅",
        "🇯🇵日本-流媒体02",
        "GPT候选",
    ]
    assert "🇸🇬新节点" not in groups["GPT手动"]["proxies"]
    assert "🇸🇬新节点" in groups["手动选择"]["proxies"]
    assert groups["Gemini候选"]["proxies"] == ["🇨🇳台湾-住宅"]
    # Disney remains based on its accepted legacy set, including the streaming node.
    assert "🇯🇵日本-流媒体02" in groups["迪士尼候选"]["proxies"]


def test_registry_replaces_stale_service_selections(monkeypatch, tmp_path):
    data = sample_config()
    key = b"verified-registry-test-key-0123456789"
    entries = [
        registry_entry(
            data["proxies"][0],
            key,
            service="gpt",
            tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
        registry_entry(
            data["proxies"][1],
            key,
            service="gpt",
            tier="preferred",
            tested_at="2026-09-08T05:01:00+00:00",
        ),
        registry_entry(
            data["proxies"][0],
            key,
            service="gemini",
            tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
    ]
    write_registry(tmp_path, monkeypatch, data, entries, key=key)
    stale = {
        service: {
            "automatic": ["🇸🇬新节点"],
            "manual_candidates": [],
            "historical_lkg": [],
        }
        for service in converter.SERVICE_KEYS
    }
    result = converter.transform(data, stale)
    groups = groups_by_name(result)
    assert groups["GPT候选"]["proxies"] == [
        "🇨🇳台湾-住宅",
        "🇯🇵日本-流媒体02",
    ]


def test_same_identity_rename_matches_but_changed_identity_does_not(monkeypatch, tmp_path):
    key = b"verified-registry-test-key-0123456789"
    original = sample_config()
    entries = [
        registry_entry(
            original["proxies"][0],
            key,
            service="gpt",
            tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
        registry_entry(
            original["proxies"][0],
            key,
            service="gemini",
            tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
    ]
    write_registry(tmp_path, monkeypatch, original, entries, key=key)

    renamed = copy.deepcopy(original)
    renamed["proxies"][0]["name"] = "🇨🇳台湾-住宅02"
    result = converter.transform(renamed)
    assert result["proxy-groups"][5]["proxies"] == ["🇨🇳台湾-住宅02"]
    seed = converter.lkg_seed_config(renamed)
    seed_groups = groups_by_name(seed)
    assert seed_groups["GPT候选"]["proxies"] == ["🇨🇳台湾-住宅02"]
    assert seed_groups["Gemini候选"]["proxies"] == ["🇨🇳台湾-住宅02"]

    changed = copy.deepcopy(original)
    changed["proxies"][0]["port"] = 99
    with pytest.raises(converter.ConfigError, match="BLOCKED_NO_CURRENT_VERIFIED_GPT"):
        converter.transform(changed)


def test_service_selection_metadata_cannot_whitelist_streaming_without_identity(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "OPENCLASH_VERIFIED_REGISTRY_PATH", str(tmp_path / "missing-registry.json")
    )
    selections = {
        service: {
            "automatic": ["🇯🇵日本-流媒体02"] if service == "gpt" else ["🇨🇳台湾-住宅"],
            "manual_candidates": [],
            "historical_lkg": [],
            "verified_names": ["🇯🇵日本-流媒体02"] if service == "gpt" else [],
        }
        for service in converter.SERVICE_KEYS
    }
    with pytest.raises(converter.ConfigError, match="BLOCKED_NO_CURRENT_SERVICE_CANDIDATES: GPT"):
        converter.transform(sample_config(), selections)


def test_registry_controlled_history_is_cleared_from_stale_selections(monkeypatch, tmp_path):
    data = sample_config()
    key = b"verified-registry-test-key-0123456789"
    entries = [
        registry_entry(
            data["proxies"][0], key, service="gpt", tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
        registry_entry(
            data["proxies"][0], key, service="gemini", tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
    ]
    write_registry(tmp_path, monkeypatch, data, entries, key=key)
    selections = {
        service: {
            "automatic": ["🇨🇳台湾-住宅"],
            "manual_candidates": [],
            "historical_lkg": ["🇨🇳台湾-住宅"],
        }
        for service in converter.SERVICE_KEYS
    }
    groups = groups_by_name(converter.transform(data, selections))
    assert "GPT历史LKG" not in groups
    assert "Gemini历史LKG" not in groups


@pytest.mark.parametrize("blocked_reason", ["NEWER_MANUAL_FAIL", "NEWER_FUNCTIONAL_FAIL"])
def test_newer_functional_or_manual_failure_removes_registry_manual_candidate(
    monkeypatch, tmp_path, blocked_reason
):
    data = sample_config()
    key = b"verified-registry-test-key-0123456789"
    entries = [
        registry_entry(
            data["proxies"][0], key, service="gpt", tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
        registry_entry(
            data["proxies"][2], key, service="gpt", tier="manual",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
        registry_entry(
            data["proxies"][0], key, service="gemini", tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
    ]
    write_registry(tmp_path, monkeypatch, data, entries, key=key)
    selections = {
        service: {
            "automatic": ["🇨🇳台湾-住宅"],
            "manual_candidates": [],
            "historical_lkg": [],
        }
        for service in converter.SERVICE_KEYS
    }
    selections["gpt"].update(
        {
            "blocked_names": ["🇸🇬新节点"],
            "blocked_reasons": {"🇸🇬新节点": blocked_reason},
        }
    )
    groups = groups_by_name(converter.transform(data, selections))
    assert "🇸🇬新节点" not in groups["GPT手动"]["proxies"]


def test_streaming_override_requires_exact_registry_identity(monkeypatch, tmp_path):
    data = sample_config()
    key = b"verified-registry-test-key-0123456789"
    entries = [
        registry_entry(
            data["proxies"][0],
            key,
            service="gpt",
            tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
        registry_entry(
            data["proxies"][1],
            key,
            service="gpt",
            tier="preferred",
            tested_at="2026-09-08T05:01:00+00:00",
        ),
        registry_entry(
            data["proxies"][0],
            key,
            service="gemini",
            tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
    ]
    write_registry(tmp_path, monkeypatch, data, entries, key=key)
    groups = groups_by_name(converter.transform(data))
    assert "🇯🇵日本-流媒体02" in groups["GPT候选"]["proxies"]

    unmatched_stream = {
        "name": "🇭🇰香港-流媒体99",
        "type": "ss",
        "server": "other.example.invalid",
        "port": 99,
    }
    data["proxies"].append(unmatched_stream)
    groups = groups_by_name(converter.transform(data))
    assert "🇭🇰香港-流媒体99" not in groups["GPT手动"]["proxies"]


def test_present_registry_requires_existing_identity_key(monkeypatch, tmp_path):
    data = sample_config()
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({"schema_version": 1, "nodes": []}), encoding="utf-8")
    missing_key = tmp_path / "missing.key"
    monkeypatch.setenv("OPENCLASH_VERIFIED_REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(converter, "DEFAULT_SOURCE_IDENTITY_KEY", missing_key)
    with pytest.raises(converter.ConfigError, match="identity key is missing"):
        converter.transform(data)
    assert not missing_key.exists()


def test_malformed_registry_and_method_pair_fail_closed(monkeypatch, tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({"schema_version": 2, "nodes": []}), encoding="utf-8")
    monkeypatch.setenv("OPENCLASH_VERIFIED_REGISTRY_PATH", str(registry_path))
    with pytest.raises(converter.ConfigError, match="Unsupported verified-service-registry schema"):
        converter.load_verified_service_registry()

    key = b"verified-registry-test-key-0123456789"
    bad = {
        "exact_node_id": "node_test",
        "node": "x",
        "service": "gpt",
        "tier": "preferred",
        "enabled": True,
        "tested_at": "2026-09-08T05:00:00+00:00",
        "method": "antigravity_inference",
    }
    registry_path.write_text(json.dumps({"schema_version": 1, "nodes": [bad]}), encoding="utf-8")
    with pytest.raises(converter.ConfigError, match="invalid method"):
        converter.load_verified_service_registry()
    assert key


def _probe_node(name: str, *, final_result: str = "UNKNOWN", observed_at: str) -> dict:
    return {
        "name": name,
        "selector_confirmed": True,
        "observed_at": observed_at,
        "base_result": "BASE_PASS",
        "services": {
            service: {
                "raw_result": final_result,
                "override": None,
                "final_result": final_result,
                "evidence": {},
            }
            for service in converter.SERVICE_KEYS
        },
    }


def test_reconcile_seeds_renamed_registry_nodes_without_legacy_candidate_names(
    monkeypatch, tmp_path
):
    original = sample_config()
    key = b"verified-registry-test-key-0123456789"
    entries = [
        registry_entry(
            original["proxies"][0], key, service="gpt", tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
        registry_entry(
            original["proxies"][0], key, service="gemini", tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
    ]
    write_registry(tmp_path, monkeypatch, original, entries, key=key)
    renamed = copy.deepcopy(original)
    renamed["proxies"][0]["name"] = "🇨🇳台湾-住宅02"
    report_path = tmp_path / "probe.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_timestamp": "2026-09-08T06:00:00+00:00",
                "probable_tun_or_upstream_recapture": False,
                "nodes": [
                    _probe_node(
                        "🇨🇳台湾-住宅02",
                        observed_at="2026-09-08T06:00:00+00:00",
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    manual_path = tmp_path / "manual.json"
    manual_path.write_text(json.dumps({"schema_version": 1, "results": []}), encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"schema_version": 1, "updated_at": "2026-09-08T05:00:00+00:00", "nodes": {}}),
        encoding="utf-8",
    )

    selections, _report = converter.reconcile_existing_probe(
        renamed,
        state_path=state_path,
        probe_report_path=report_path,
        manual_results_path=manual_path,
        report_output_path=tmp_path / "reconciled.json",
        state_output_path=tmp_path / "new-state.json",
    )
    assert selections["gpt"]["automatic"] == ["🇨🇳台湾-住宅02"]
    assert selections["gemini"]["automatic"] == ["🇨🇳台湾-住宅02"]


def test_reconcile_uses_saved_provenance_and_honors_newer_transport_block(
    monkeypatch, tmp_path
):
    data = sample_config()
    key = b"verified-registry-test-key-0123456789"
    entries = [
        registry_entry(
            data["proxies"][0],
            key,
            service="gpt",
            tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
        registry_entry(
            data["proxies"][0],
            key,
            service="gemini",
            tier="preferred",
            tested_at="2026-09-08T05:00:00+00:00",
        ),
    ]
    write_registry(tmp_path, monkeypatch, data, entries, key=key)
    report_path = tmp_path / "probe.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_timestamp": "2026-09-08T06:00:00+00:00",
                "probable_tun_or_upstream_recapture": False,
                "nodes": [_probe_node("🇨🇳台湾-住宅", final_result="FAIL_TRANSPORT", observed_at="2026-09-08T06:00:00+00:00")],
            }
        ),
        encoding="utf-8",
    )
    manual_path = tmp_path / "manual.json"
    manual_path.write_text(json.dumps({"schema_version": 1, "results": []}), encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"schema_version": 1, "updated_at": "2026-09-08T05:00:00+00:00", "nodes": {}}),
        encoding="utf-8",
    )

    selections, report = converter.reconcile_existing_probe(
        data,
        state_path=state_path,
        probe_report_path=report_path,
        manual_results_path=manual_path,
        report_output_path=tmp_path / "reconciled.json",
        state_output_path=tmp_path / "new-state.json",
    )
    assert selections["gpt"]["automatic"] == []
    assert selections["gpt"]["blocked_names"] == ["🇨🇳台湾-住宅"]
    assert selections["gpt"]["manual_candidates"] == ["🇨🇳台湾-住宅", "🇸🇬新节点"]
    assert report["verified_service_registry"]["evidence_provenance"] == (
        "saved_actual_use_evidence"
    )
    assert report["verified_service_registry"]["records"][0]["tested_at"] == (
        "2026-09-08T05:00:00+00:00"
    )
    enriched = next(node for node in report["nodes"] if node["name"] == "🇨🇳台湾-住宅")
    assert enriched["services"]["gpt"]["registry_evidence_provenance"] == (
        "saved_actual_use_evidence"
    )


@pytest.mark.parametrize("service,method", [("gpt","chatgpt_web_generation"),("gemini","gemini_web_generation")])
def test_authenticated_web_proof_is_service_specific(tmp_path,monkeypatch,service,method):
    data=sample_config();key=b"verified-registry-test-key-0123456789"
    entry=registry_entry(data["proxies"][0],key,service=service,tier="preferred",tested_at="2026-09-22T00:00:00+08:00")
    entry["method"]=method
    path,_=write_registry(tmp_path,monkeypatch,data,[entry],key=key)
    assert converter.load_verified_service_registry(path)["nodes"][0]["method"]==method
    entry["service"]="gemini" if service=="gpt" else "gpt"
    path.write_text(json.dumps({"schema_version":1,"nodes":[entry]}))
    with pytest.raises(converter.ConfigError,match="invalid method"):
        converter.load_verified_service_registry(path)
