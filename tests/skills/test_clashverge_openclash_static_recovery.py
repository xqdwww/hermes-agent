from __future__ import annotations

import importlib.util
import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).parents[2]
    / "skills"
    / "clashverge-openclash-static"
    / "scripts"
    / "clashverge_to_openclash.py"
)
SPEC = importlib.util.spec_from_file_location("clashverge_to_openclash_recovery", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def completed(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr=stderr)


def manifest(snapshot_id: str, nodes: list[tuple[str, str]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_snapshot_id": snapshot_id,
        "source_hash": "a" * 64,
        "node_count": len(nodes),
        "nodes": [
            {"exact_node_name": name, "exact_node_id": node_id, "protocol": "anytls"}
            for name, node_id in nodes
        ],
    }


def test_snapshot_manifest_passed_as_source_is_an_argument_error(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot-current.json"
    snapshot.write_text(json.dumps(manifest("snapshot-current", [])), encoding="utf-8")

    with pytest.raises(MODULE.ConfigError, match="STOP_SOURCE_ARGUMENT_ERROR"):
        MODULE.validate_live_source_contract(
            MODULE.clash_verge_paths(snapshot), explicit_source=True
        )


def test_live_source_without_profiles_metadata_is_not_identity_drift(
    tmp_path: Path,
) -> None:
    source = tmp_path / "effective.yaml"
    source.write_text("proxies: []\n", encoding="utf-8")

    with pytest.raises(MODULE.ConfigError, match="STOP_SOURCE_ARGUMENT_ERROR"):
        MODULE.validate_live_source_contract(
            MODULE.clash_verge_paths(source), explicit_source=True
        )


def test_identity_coverage_is_exact_id_based_and_count_closed() -> None:
    previous = manifest(
        "snapshot-old",
        [("renamed-old", "node-a"), ("same-name-changed", "node-b")],
    )
    current = manifest(
        "snapshot-current",
        [
            ("renamed-new", "node-a"),
            ("same-name-changed", "node-c"),
            ("new-node", "node-d"),
        ],
    )

    audit = MODULE.audit_snapshot_identity_coverage(previous, current)

    assert audit["identity_match_count"] == 1
    assert audit["renamed_identity_match"] == [
        {
            "exact_node_id": "node-a",
            "previous_name": "renamed-old",
            "current_name": "renamed-new",
        }
    ]
    assert audit["identity_changed"] == [
        {
            "exact_node_name": "same-name-changed",
            "previous_node_id": "node-b",
            "current_node_id": "node-c",
        }
    ]
    assert audit["added_node_ids"] == ["node-c", "node-d"]
    assert audit["deleted_node_ids"] == ["node-b"]
    assert audit["current_count_closed"] is True
    assert audit["previous_count_closed"] is True


def test_rrc_report_is_adapted_without_manual_wrapper() -> None:
    source_manifest = manifest(
        "snapshot-current", [("node-a", "id-a"), ("node-b", "id-b")]
    )
    rrc = {
        "schema_version": 3,
        "probe_method_version": "regionrestrictioncheck-sidecar-v8",
        "source_snapshot_id": "snapshot-current",
        "source_hash": "a" * 64,
        "snapshot_node_count": 2,
        "selected_node_count": 2,
        "nodes_completed": 2,
        "attribution_mismatch": 0,
        "status": "COMPLETE",
        "production_fingerprint_preserved": True,
        "started_at": "2026-08-10T10:00:00+08:00",
        "completed_at": "2026-08-10T10:05:00+08:00",
        "node_attempts": [
            {
                "exact_node_name": "node-a",
                "exact_node_id": "id-a",
                "selector_readback": "node-a",
                "status": "ATTRIBUTION_MATCH",
                "attribution_valid": True,
                "output_complete": True,
                "transport_unknown": False,
                "exit_country": "JP",
            },
            {
                "exact_node_name": "node-b",
                "exact_node_id": "id-b",
                "selector_readback": "node-b",
                "status": "ATTRIBUTION_UNAVAILABLE",
                "attribution_valid": False,
                "output_complete": False,
                "transport_unknown": True,
                "exit_country": "UNKNOWN",
            },
        ],
        "results": [],
    }

    report = MODULE.build_probe_report_from_rrc(rrc, source_manifest)

    assert report["run_timestamp"] == "2026-08-10T10:05:00+08:00"
    assert [item["name"] for item in report["nodes"]] == ["node-a", "node-b"]
    assert report["nodes"][0]["base_result"] == "BASE_PASS"
    assert report["nodes"][1]["base_result"] == "ATTRIBUTION_UNAVAILABLE"
    assert report["identity_coverage"]["missing_node_ids"] == []


def test_candidate_journal_rejects_changed_artifact_binding(tmp_path: Path) -> None:
    path = tmp_path / "prepare-state.json"
    binding = {
        "source_snapshot_id": "snapshot-current",
        "source_hash": "a" * 64,
        "rrc_sha256": "b" * 64,
    }
    created = MODULE.load_or_initialize_preparation_journal(path, binding)
    assert created["status"] == "RUNNING"

    with pytest.raises(MODULE.ConfigError, match="STOP_PREPARE_RESUME_BINDING_MISMATCH"):
        MODULE.load_or_initialize_preparation_journal(
            path, {**binding, "rrc_sha256": "c" * 64}
        )


def test_subprocess_diagnostic_has_stage_tail_and_redacts_secrets() -> None:
    exc = subprocess.CalledProcessError(
        75,
        ["ssh", "router", "CANDIDATE_SIDECAR_SETUP=1"],
        output="setup started\n",
        stderr=(
            "lock is active\n"
            "Proxy-Authorization: Basic fixture-basic-value\n"
            "token=fixture-token-value\n"
        ),
    )

    diagnostic = MODULE.subprocess_failure_diagnostic(exc)

    assert "exit_code=75" in diagnostic
    assert "lock is active" in diagnostic
    assert "fixture-basic-value" not in diagnostic
    assert "fixture-token-value" not in diagnostic
    assert "REDACTED" in diagnostic


def test_stale_sidecar_recovery_is_exact_and_lease_aware(monkeypatch) -> None:
    commands: list[str] = []

    def fake_ssh(_host: str, command: str, **_kwargs):
        commands.append(command)
        return completed("STALE_CLEANED\n")

    monkeypatch.setattr(MODULE, "ssh_command", fake_ssh)
    result = MODULE.recover_stale_remote_sidecar_lock(
        "router", "/etc/openclash/core/clash_meta"
    )

    assert result == "STALE_CLEANED"
    command = commands[0]
    assert "heartbeat" in command
    assert "owner" in command
    assert "/proc/[0-9]*" in command
    assert "readlink" in command
    assert "ACTIVE" in command
    assert subprocess.run(
        ["sh", "-n"], input=command, text=True, capture_output=True, check=False
    ).returncode == 0

    guard = MODULE._remote_sidecar_guard_command(
        "/tmp/clashverge-openclash-sidecar.token",
        "/tmp/clashverge-openclash-sidecar.lock",
        "a" * 32,
        "/core",
    )
    assert "heartbeat" in guard
    assert "trap cleanup" in guard
    assert subprocess.run(
        ["sh", "-n"], input=guard, text=True, capture_output=True, check=False
    ).returncode == 0


def test_active_sidecar_lease_is_never_reaped(monkeypatch) -> None:
    monkeypatch.setattr(
        MODULE,
        "ssh_command",
        lambda *_args, **_kwargs: completed("ACTIVE\n"),
    )
    with pytest.raises(MODULE.ConfigError, match="CANDIDATE_SIDECAR_LOCK_ACTIVE"):
        MODULE.recover_stale_remote_sidecar_lock("router", "/core")


def test_manual_evidence_survives_display_name_change_when_identity_matches() -> None:
    key = b"k" * 32
    old_proxy = {
        "name": "old-name",
        "type": "hysteria2",
        "server": "edge.example",
        "port": 443,
        "password": "sensitive",
    }
    current_proxy = {**old_proxy, "name": "new-name"}
    current_id = MODULE.stable_node_identity(current_proxy, key)
    manual = [
        {
            "service": "gemini",
            "node": "old-name",
            "result": "FAIL",
            "tested_at": "2026-08-10T12:00:00+08:00",
            "method": "logged_in_browser_actual_generation",
        }
    ]
    current_manifest = manifest("snapshot-current", [("new-name", current_id)])

    migrated, retest = MODULE.migrate_manual_evidence_by_connection_identity(
        manual, [old_proxy], [current_proxy], current_manifest, key
    )

    assert retest == []
    assert migrated[0]["node"] == "new-name"
    assert migrated[0]["exact_node_id"] == current_id


def test_lkg_rebind_uses_exact_id_not_display_name() -> None:
    state = {
        "schema_version": 1,
        "updated_at": "2026-08-10T12:00:00+08:00",
        "nodes": {
            "old-name": {
                service: {"exact_node_id": "id-a", "lkg": True}
                for service in MODULE.SERVICE_KEYS
            },
            "same-name": {
                service: {"exact_node_id": "old-id", "lkg": True}
                for service in MODULE.SERVICE_KEYS
            },
        },
    }
    current = manifest(
        "snapshot-current", [("new-name", "id-a"), ("same-name", "new-id")]
    )

    rebound, audit = MODULE.rebind_lkg_state_by_exact_identity(state, current)

    assert "old-name" not in rebound["nodes"]
    assert rebound["nodes"]["new-name"]["gpt"]["exact_node_id"] == "id-a"
    assert rebound["nodes"]["same-name"]["gpt"]["exact_node_id"] == "old-id"
    assert audit["rebound_count"] == 1


def test_prepare_candidate_cli_cannot_activate() -> None:
    args = MODULE.build_parser().parse_args(
        [
            "prepare-candidate",
            "--source-snapshot",
            "snapshot.json",
            "--rrc-results",
            "rrc.json",
            "--workdir",
            "out",
            "--upload",
        ]
    )

    assert args.command == "prepare-candidate"
    assert args.upload is True
    assert not hasattr(args, "activate")


def frozen_candidate_inputs(tmp_path: Path) -> tuple[Path, Path]:
    names = ["🇨🇳台湾-住宅", "🇯🇵日本aws高速02", "🇺🇸美国-住宅"]
    proxies = [
        {
            "name": name,
            "type": "anytls",
            "server": f"node-{index}.example.invalid",
            "port": 443,
            "password": f"credential-{index}",
        }
        for index, name in enumerate(names)
    ]
    payload = tmp_path / "snapshot-current.private.yaml"
    MODULE.dump_yaml({"proxies": proxies, "rules": []}, payload)
    node_ids = [f"id-{index}" for index in range(len(names))]
    snapshot = tmp_path / "snapshot-current.json"
    source_manifest = {
        **manifest("snapshot-current", list(zip(names, node_ids))),
        "source_payload": payload.name,
        "source_hash": MODULE.sha256_file(payload),
    }
    snapshot.write_text(json.dumps(source_manifest), encoding="utf-8")
    results = []
    attempts = []
    for name, node_id in zip(names, node_ids):
        attempts.append(
            {
                "exact_node_name": name,
                "exact_node_id": node_id,
                "selector_readback": name,
                "status": "ATTRIBUTION_MATCH",
                "attribution_valid": True,
                "output_complete": True,
                "transport_unknown": False,
                "exit_country": "JP",
                "completed_at": "2026-08-10T10:05:00+08:00",
            }
        )
        for service in MODULE.SERVICE_KEYS:
            results.append(
                {
                    "service": service,
                    "exact_node_name": name,
                    "exact_node_id": node_id,
                    "source_snapshot_id": "snapshot-current",
                    "source_hash": source_manifest["source_hash"],
                    "tested_at": "2026-08-10T10:05:00+08:00",
                    "probe_method_version": "regionrestrictioncheck-sidecar-v8",
                    "result": "SCREEN_PASS",
                    "attribution_status": "ATTRIBUTION_MATCH",
                    "control_exit_ip_hmac": "same-hmac",
                    "regioncheck_exit_ip_hmac": "same-hmac",
                    "exit_country": "JP",
                }
            )
    rrc = tmp_path / "rrc.json"
    rrc.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "probe_method_version": "regionrestrictioncheck-sidecar-v8",
                "source_snapshot_id": "snapshot-current",
                "source_hash": source_manifest["source_hash"],
                "snapshot_node_count": len(names),
                "selected_node_count": len(names),
                "nodes_completed": len(names),
                "attribution_mismatch": 0,
                "status": "COMPLETE",
                "production_fingerprint_preserved": True,
                "started_at": "2026-08-10T10:00:00+08:00",
                "completed_at": "2026-08-10T10:05:00+08:00",
                "node_attempts": attempts,
                "results": results,
            }
        ),
        encoding="utf-8",
    )
    return snapshot, rrc


def prepare_args(tmp_path: Path, snapshot: Path, rrc: Path, *, upload: bool) -> Namespace:
    return Namespace(
        source_snapshot=snapshot,
        rrc_results=rrc,
        previous_source_snapshot=None,
        manual_results=None,
        previous_manual_results=None,
        functional_results=[],
        state_path=tmp_path / "absent-lkg.json",
        source_identity_key=tmp_path / "identity.key",
        workdir=tmp_path / "prepared",
        output_name="candidate.yaml",
        audit_name="candidate-audit.yaml",
        journal=None,
        upload=upload,
        host="router",
        remote_name=None,
        core_path="/core",
    )


def test_prepare_candidate_resumes_same_frozen_artifacts_without_network(
    tmp_path: Path,
) -> None:
    snapshot, rrc = frozen_candidate_inputs(tmp_path)
    args = prepare_args(tmp_path, snapshot, rrc, upload=False)

    first = MODULE.prepare_candidate_from_frozen_artifacts(args)
    second = MODULE.prepare_candidate_from_frozen_artifacts(args)

    assert first["status"] == "CANDIDATE_GENERATED_NOT_UPLOADED"
    assert second["resumed"] is True
    assert second["candidate_sha256"] == first["candidate_sha256"]
    assert second["activated"] is False
    journal = json.loads(Path(second["journal_path"]).read_text(encoding="utf-8"))
    assert journal["resume_count"] == 1
    assert journal["last_completed_stage"] == "PREPARATION_COMPLETE"


def test_prepare_candidate_resumes_after_sidecar_failure(
    tmp_path: Path, monkeypatch
) -> None:
    snapshot, rrc = frozen_candidate_inputs(tmp_path)
    args = prepare_args(tmp_path, snapshot, rrc, upload=True)
    uploaded = MODULE.UploadedCandidate(
        "/etc/openclash/config/.clashverge-candidates/candidate.immutable",
        "/etc/openclash/config/candidate.yaml",
    )
    monkeypatch.setattr(MODULE, "upload_candidate", lambda *_a, **_k: uploaded)
    probes = iter([MODULE.ConfigError("injected sidecar failure"), None])

    def probe(*_args, **_kwargs):
        failure = next(probes)
        if failure:
            raise failure

    monkeypatch.setattr(MODULE, "probe_uploaded_candidate", probe)
    with pytest.raises(MODULE.ConfigError, match="injected sidecar failure"):
        MODULE.prepare_candidate_from_frozen_artifacts(args)
    failed = json.loads(
        (args.workdir / "candidate-preparation-state.json").read_text(encoding="utf-8")
    )
    assert failed["status"] == "FAILED_RECOVERABLE"
    assert failed["last_completed_stage"] == "CANDIDATE_UPLOADED"

    resumed = MODULE.prepare_candidate_from_frozen_artifacts(args)

    assert resumed["status"] == "READY_FOR_EXPLICIT_ACTIVATE_APPROVAL"
    assert resumed["resumed"] is True
    assert resumed["activated"] is False
