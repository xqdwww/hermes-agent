from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


SKILL_ROOT = Path(__file__).parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REGIONCHECK = load_module(
    "formal_regioncheck_probe",
    SKILL_ROOT / "scripts" / "regioncheck_service_probe.py",
)
DISNEY = load_module(
    "formal_disney_probe",
    SKILL_ROOT / "scripts" / "disney_service_probe.py",
)
CONVERTER = load_module(
    "formal_update_converter",
    SKILL_ROOT / "scripts" / "clashverge_to_openclash.py",
)


def test_gemini_fallback_uses_antigravity_health_and_hysteresis() -> None:
    groups = CONVERTER.build_groups(
        ["tw-node", "us-node"],
        ["us-node"],
        ["tw-node", "us-node"],
        ["us-node"],
    )
    gemini = {group["name"]: group for group in groups}["Gemini候选"]
    assert gemini["url"] == "https://daily-cloudcode-pa.googleapis.com/generate_204"
    assert gemini["max-failed-times"] == 2


def test_gemini_manual_defaults_to_first_functionally_filtered_node() -> None:
    groups = CONVERTER.build_groups(
        ["tw02-node", "tw-node", "us-node"],
        ["us-node"],
        ["tw02-node", "tw-node"],
        ["us-node"],
    )
    manual = {group["name"]: group for group in groups}["Gemini手动"]
    assert manual["proxies"][:3] == ["tw02-node", "tw-node", "Gemini候选"]


def test_disney_safe_report_allows_redacted_token_stage() -> None:
    DISNEY.validate_safe_report(
        {
            "nodes": [
                {
                    "result": "PASS_SUPPORTED_REGION",
                    "stages": {
                        "devices": {"curl_code": 0, "http_status": 200, "attempts": 1},
                        "token": {"curl_code": 0, "http_status": 200, "attempts": 1},
                        "graphql": {"curl_code": 0, "http_status": 200, "attempts": 1},
                        "redirect": {"curl_code": 0, "http_status": 200, "attempts": 1},
                    },
                }
            ]
        }
    )


def test_disney_chain_discards_transient_credentials_before_validation() -> None:
    responses = [
        {
            "curl_code": 0,
            "http_status": 200,
            "attempts": 1,
            "raw": json.dumps({"assertion": "transient-assertion"}),
        },
        {
            "curl_code": 0,
            "http_status": 200,
            "attempts": 1,
            "raw": json.dumps({"refresh_token": "transient-refresh-token"}),
        },
        {
            "curl_code": 0,
            "http_status": 200,
            "attempts": 1,
            "raw": json.dumps(
                {
                    "extensions": {
                        "sdk": {
                            "session": {
                                "location": {"countryCode": "US"},
                                "inSupportedLocation": True,
                            }
                        }
                    }
                }
            ),
        },
        {
            "curl_code": 0,
            "http_status": 200,
            "attempts": 1,
            "raw": "ignored body",
            "effective_url": "https://www.disneyplus.com/home",
        },
    ]

    with patch.object(DISNEY, "curl_request", side_effect=responses):
        outcome = DISNEY.run_chain(17890)

    assert outcome["result"] == "PASS_SUPPORTED_REGION"
    DISNEY.validate_safe_report({"nodes": [outcome]})
    serialized = json.dumps(outcome)
    assert "transient-assertion" not in serialized
    assert "transient-refresh-token" not in serialized


@pytest.mark.parametrize("forbidden", ["token", "assertion", "refresh_token", "body", "raw"])
def test_disney_safe_report_still_rejects_sensitive_payload_fields(forbidden: str) -> None:
    with pytest.raises(RuntimeError, match="DISNEY_REPORT_SENSITIVE_FIELD"):
        DISNEY.validate_safe_report(
            {
                "nodes": [
                    {
                        "stages": {
                            "devices": {
                                "curl_code": 0,
                                "http_status": 200,
                                "attempts": 1,
                            }
                        },
                        forbidden: "secret",
                    }
                ]
            }
        )


def test_disney_safe_report_rejects_payload_hidden_in_token_stage() -> None:
    with pytest.raises(RuntimeError, match="DISNEY_REPORT_STAGE_SCHEMA"):
        DISNEY.validate_safe_report(
            {
                "nodes": [
                    {
                        "stages": {
                            "token": {
                                "curl_code": 0,
                                "http_status": 200,
                                "attempts": 1,
                                "raw": "secret",
                            }
                        }
                    }
                ]
            }
        )


def test_disney_import_reuses_only_recent_definitive_identity_matches() -> None:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(hours=1)).isoformat()
    manifest = {
        "source_snapshot_id": "snapshot-new",
        "source_hash": "b" * 64,
        "nodes": [
            {"exact_node_id": "node-pass", "exact_node_name": "renamed-pass"},
            {"exact_node_id": "node-transport", "exact_node_name": "retry-me"},
        ],
    }
    previous = {
        "schema_version": DISNEY.SCHEMA_VERSION,
        "service": "disney",
        "probe_method_version": DISNEY.METHOD_VERSION,
        "source_snapshot_id": "snapshot-old",
        "source_hash": "a" * 64,
        "production_fingerprint_preserved": True,
        "nodes": [
            {
                "exact_node_id": "node-pass",
                "exact_node_name": "old-pass",
                "source_snapshot_id": "snapshot-old",
                "source_hash": "a" * 64,
                "tested_at": recent,
                "result": "PASS_SUPPORTED_REGION",
                "failure_stage": None,
                "country_code": "US",
                "in_supported_location": True,
                "final_redirect_class": "SUPPORTED_ROUTE",
                "stages": {},
            },
            {
                "exact_node_id": "node-transport",
                "exact_node_name": "retry-me",
                "source_snapshot_id": "snapshot-old",
                "source_hash": "a" * 64,
                "tested_at": recent,
                "result": "FAIL_TRANSPORT",
                "failure_stage": "devices",
                "stages": {},
            },
        ],
    }

    nodes, reusable = DISNEY.import_reusable_nodes(
        previous,
        manifest=manifest,
        evidence_ttl_seconds=12 * 60 * 60,
        now=now,
    )

    assert reusable == {"node-pass"}
    assert nodes[0]["exact_node_name"] == "renamed-pass"
    assert nodes[0]["source_snapshot_id"] == "snapshot-new"
    assert nodes[0]["evidence_reused"] is True


def test_auto_calibration_requires_two_distinct_attributed_exits() -> None:
    attempts = [
        {
            "exact_node_name": "node-a",
            "status": "ATTRIBUTION_MATCH",
            "output_complete": True,
            "result_count": len(REGIONCHECK.SERVICE_LABELS),
            "control_exit_ip_hmac": "exit-1",
        },
        {
            "exact_node_name": "node-b-same-exit",
            "status": "ATTRIBUTION_MATCH",
            "output_complete": True,
            "result_count": len(REGIONCHECK.SERVICE_LABELS),
            "control_exit_ip_hmac": "exit-1",
        },
        {
            "exact_node_name": "node-c-unavailable",
            "status": "ATTRIBUTION_UNAVAILABLE",
            "output_complete": False,
            "result_count": 0,
            "control_exit_ip_hmac": None,
        },
        {
            "exact_node_name": "node-d",
            "status": "ATTRIBUTION_MATCH",
            "output_complete": True,
            "result_count": len(REGIONCHECK.SERVICE_LABELS),
            "control_exit_ip_hmac": "exit-2",
        },
    ]

    assert REGIONCHECK.auto_calibration_sentinels(attempts) == ["node-a", "node-d"]


def test_auto_calibration_ignores_incomplete_results() -> None:
    attempts = [
        {
            "exact_node_name": "node-a",
            "status": "ATTRIBUTION_MATCH",
            "output_complete": False,
            "result_count": 0,
            "control_exit_ip_hmac": "exit-1",
        }
    ]

    assert REGIONCHECK.auto_calibration_sentinels(attempts) == []


def test_formal_update_runs_rrc_disney_then_candidate_preparation(tmp_path: Path) -> None:
    manifest_path = tmp_path / "snapshot_current.json"
    source_path = tmp_path / "snapshot_current.private.yaml"
    manifest_path.write_text("{}\n")
    source_path.write_text("proxies: []\n")
    manifest = {
        "source_snapshot_id": "snapshot_current",
        "source_hash": "a" * 64,
        "node_count": 3,
    }
    commands: list[list[str]] = []

    def fake_probe(command: list[str]) -> None:
        commands.append(command)
        output = Path(command[command.index("--output") + 1])
        if command[1].endswith("regioncheck_service_probe.py"):
            payload = {
                "status": "COMPLETE",
                "source_snapshot_id": "snapshot_current",
                "source_hash": "a" * 64,
                "production_fingerprint_preserved": True,
                "auto_calibration_status": (
                    "PASS_RRC_PROXY_ATTRIBUTION_TWO_NODE_AUTO_CALIBRATION"
                ),
                "identity_coverage": {
                    "exact_id_set_equal": True,
                    "expected_node_count": 3,
                },
            }
        else:
            payload = {
                "source_snapshot_id": "snapshot_current",
                "source_hash": "a" * 64,
                "production_fingerprint_preserved": True,
                "nodes": [{}, {}, {}],
            }
        output.write_text(json.dumps(payload))

    prepared: list[argparse.Namespace] = []

    def fake_prepare(args: argparse.Namespace):
        prepared.append(args)
        return {
            "status": "READY_FOR_EXPLICIT_ACTIVATE_APPROVAL",
            "source_snapshot_id": "snapshot_current",
            "candidate_path": str(tmp_path / "candidate.yaml"),
            "candidate_sha256": "b" * 64,
            "remote_candidate_path": "/candidate",
            "journal_path": str(tmp_path / "journal.json"),
            "identity_audit_path": str(tmp_path / "identity.json"),
            "manual_migration_audit_path": str(tmp_path / "manual.json"),
            "probe_report_path": str(tmp_path / "probe.json"),
            "state_output_path": str(tmp_path / "state.json"),
            "activated": False,
        }

    args = argparse.Namespace(
        source=None,
        workdir=tmp_path,
        refresh_adapter=None,
        no_refresh_source=False,
        source_snapshot=None,
        source_identity_key=tmp_path / "identity.key",
        refresh_timeout=30,
        min_node_retention_ratio=0.5,
        state_path=tmp_path / "lkg.json",
        manual_results=None,
        previous_source_snapshot=None,
        previous_manual_results=None,
        functional_results=[],
        upload=True,
        host="router",
        remote_name=None,
        core_path="/core",
        rrc_timeout=20,
        rrc_node_interval=0.0,
        probe_evidence_ttl=12 * 60 * 60,
        probe_cache_dir=tmp_path / "probe-cache",
    )
    args.probe_cache_dir.mkdir()
    (args.probe_cache_dir / "latest-regioncheck.json").write_text("{}\n")
    (args.probe_cache_dir / "latest-disney.json").write_text("{}\n")

    with (
        patch.object(
            CONVERTER,
            "prepare_source_snapshot",
            return_value=(
                manifest,
                source_path,
                {"manifest_path": str(manifest_path)},
            ),
        ),
        patch.object(CONVERTER, "run_probe_command", side_effect=fake_probe),
        patch.object(
            CONVERTER,
            "prepare_candidate_from_frozen_artifacts",
            side_effect=fake_prepare,
        ),
    ):
        result = CONVERTER.orchestrate_formal_candidate_update(args)

    assert result["status"] == "READY_FOR_EXPLICIT_ACTIVATE_APPROVAL"
    assert len(commands) == 2
    assert commands[0][1].endswith("regioncheck_service_probe.py")
    assert "--auto-calibrate" in commands[0]
    assert "--import-report" in commands[0]
    assert commands[0][commands[0].index("--evidence-ttl") + 1] == str(12 * 60 * 60)
    assert commands[1][1].endswith("disney_service_probe.py")
    assert "--import-report" in commands[1]
    assert commands[1][commands[1].index("--evidence-ttl") + 1] == str(12 * 60 * 60)
    assert len(prepared) == 1
    assert prepared[0].rrc_results.name == "regioncheck-full.json"
    assert [path.name for path in prepared[0].functional_results] == [
        "disney-full-chain.json"
    ]
    assert prepared[0].upload is True

    commands.clear()
    with (
        patch.object(
            CONVERTER,
            "prepare_source_snapshot",
            return_value=(
                manifest,
                source_path,
                {"manifest_path": str(manifest_path)},
            ),
        ),
        patch.object(CONVERTER, "run_probe_command", side_effect=fake_probe),
        patch.object(
            CONVERTER,
            "prepare_candidate_from_frozen_artifacts",
            side_effect=fake_prepare,
        ),
    ):
        CONVERTER.orchestrate_formal_candidate_update(args)

    assert commands == []
