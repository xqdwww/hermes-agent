from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


probe = _load("antigravity_actual_probe", SCRIPT_DIR / "antigravity_actual_probe.py")
converter = _load("actual_probe_converter", SCRIPT_DIR / "clashverge_to_openclash.py")


def test_parser_requires_calibration_and_exposes_actual_probe_options():
    parser = converter.build_parser()
    args = parser.parse_args(
        [
            "probe-gemini-actual",
            "--source-snapshot",
            "snapshot.json",
            "--output",
            "results.json",
            "--calibration-node",
            "known-good",
            "--workers",
            "2",
            "--node",
            "target",
            "--agy-command",
            "/usr/local/bin/agy --verbose",
            "--model",
            "configured-model",
        ]
    )
    assert args.calibration_node == ["known-good"]
    assert args.node == ["target"]
    assert args.workers == 2
    assert args.model == "configured-model"
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "probe-gemini-actual",
                "--source-snapshot",
                "snapshot.json",
                "--output",
                "results.json",
            ]
        )


def test_agy_command_omits_default_model_and_adds_explicit_model_only():
    without_model = probe.build_agy_command("agy", "MARKER")
    with_model = probe.build_agy_command("agy", "MARKER", model="configured-model")

    assert "--model" not in without_model
    assert "--model" in with_model
    assert with_model[with_model.index("--model") + 1] == "configured-model"


def test_parser_requires_marker_and_route_for_decisive_results():
    assert probe.parse_cli(
        '{"status":"SUCCESS","response":"MARKER"}', "", "MARKER"
    ) == ("PASS", None)
    assert probe.parse_cli("", "FAILED_PRECONDITION", "MARKER") == (
        "REGION_BLOCKED",
        "FAIL_REGION",
    )
    assert probe.parse_cli("", "RESOURCE_EXHAUSTED", "MARKER") == (
        "UNKNOWN",
        "ACCOUNT_OR_RATE_LIMIT",
    )


def test_parser_accepts_current_and_wrapped_agy_json_shapes():
    assert probe.parse_cli(
        '{"type":"result","subtype":"success","is_error":false,"result":"MARKER"}',
        "",
        "MARKER",
    ) == ("PASS", None)
    assert probe.parse_cli(
        '{"result":{"status":"SUCCESS","response":{"text":"MARKER"}}}',
        "",
        "MARKER",
    ) == ("PASS", None)
    assert probe.parse_cli(
        '{"type":"result","subtype":"error","is_error":true,"result":"FAILED_PRECONDITION"}',
        "",
        "MARKER",
    ) == ("REGION_BLOCKED", "FAIL_REGION")


class _FakeProcess:
    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def kill(self):
        self.alive = False

    def wait(self, timeout=None):
        self.alive = False
        return 0


class _FakeSkill:
    ConfigError = ValueError
    REMOTE_SIDECAR_MIXED_PORT = 17890
    REMOTE_SIDECAR_CONTROLLER_PORT = 19090

    def __init__(self, *, pass_probe: bool = True, route: bool = True):
        self.pass_probe = pass_probe
        self.route = route
        self.manifest = {
            "source_snapshot_id": "snapshot-test",
            "source_hash": "hash-test",
            "node_count": 2,
            "nodes": [
                {"exact_node_id": "id-good", "exact_node_name": "good"},
                {"exact_node_id": "id-target", "exact_node_name": "target"},
            ],
        }
        self.saved = None

    def verify_source_snapshot(self, path):
        return self.manifest, Path("snapshot.private.yaml")

    def load_yaml(self, path):
        return {
            "proxies": [
                {"name": "good", "server": "good.example"},
                {"name": "target", "server": "target.example"},
            ]
        }

    def static_proxy_objects(self, data):
        return data["proxies"]

    def build_probe_config(self, proxies, **kwargs):
        return {"proxies": list(proxies), "listeners": []}

    def dump_yaml(self, data, path):
        path.write_text("private")

    def controller_json_request(self, port, path, **kwargs):
        if path == "/proxies":
            return {"proxies": {"good": {}, "target": {}}}
        if path == "/connections" and self.route:
            return {
                "connections": [
                    {
                        "metadata": {"host": "daily-cloudcode-pa.googleapis.com"},
                        "chains": ["good", "target"],
                    }
                ]
            }
        return {"connections": []}

    @contextmanager
    def remote_candidate_sidecar(self, path, *, host, core_path):
        yield SimpleNamespace(controller_port=self.REMOTE_SIDECAR_CONTROLLER_PORT)

    def atomic_write_json(self, payload, path, *, private_parent=False):
        self.saved = payload
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))


def _listener_tunnel(host, remote_ports):
    return _FakeProcess(), [port + 10000 for port in remote_ports]


def _successful_runner(command, **kwargs):
    marker = command[2].split()[-1]
    return SimpleNamespace(
        stdout=json.dumps({"status": "SUCCESS", "response": marker}),
        stderr="",
    )


def test_successful_results_are_loader_compatible_and_reuse_calibration(tmp_path):
    skill = _FakeSkill()
    output = tmp_path / "gemini-results.json"

    report = probe.run_probe(
        source_snapshot=tmp_path / "snapshot.json",
        output=output,
        calibration_nodes=["good"],
        target_nodes=["good", "target"],
        workers=2,
        skill=skill,
        process_runner=_successful_runner,
        listener_tunnel_factory=_listener_tunnel,
    )

    assert report["status"] == "COMPLETE"
    assert report["production_unchanged"] is True
    assert [item["exact_node_name"] for item in report["results"]] == [
        "good",
        "target",
    ]
    assert converter.load_functional_results([output])[0]["result"] == "PASS"
    assert all("isolated_listener" in item for item in report["results"])


def test_calibration_failure_does_not_emit_accepted_result(tmp_path):
    skill = _FakeSkill(pass_probe=False, route=False)
    output = tmp_path / "gemini-results.json"

    def failed_runner(command, **kwargs):
        return SimpleNamespace(stdout="", stderr="RESOURCE_EXHAUSTED")

    with pytest.raises(ValueError, match="STOP_GEMINI_ACTUAL_CALIBRATION_FAILED") as raised:
        probe.run_probe(
            source_snapshot=tmp_path / "snapshot.json",
            output=output,
            calibration_nodes=["good"],
            target_nodes=["target"],
            skill=skill,
            process_runner=failed_runner,
            listener_tunnel_factory=_listener_tunnel,
        )
    details = json.loads(str(raised.value).split(":", 1)[1])
    assert details == {
        "attempts": [
            {
                "error_category": "ACCOUNT_OR_RATE_LIMIT",
                "marker_verified": False,
                "result": "UNKNOWN",
                "route_confirmed": False,
            }
        ]
    }
    assert "stdout" not in str(raised.value)
    assert "response" not in str(raised.value)
    assert not output.exists()


def test_calibration_failure_reason_distinguishes_missing_route(tmp_path):
    skill = _FakeSkill(route=False)
    output = tmp_path / "gemini-results.json"

    with pytest.raises(ValueError) as raised:
        probe.run_probe(
            source_snapshot=tmp_path / "snapshot.json",
            output=output,
            calibration_nodes=["good"],
            target_nodes=["target"],
            skill=skill,
            process_runner=_successful_runner,
            listener_tunnel_factory=_listener_tunnel,
        )

    details = json.loads(str(raised.value).split(":", 1)[1])
    assert details == {
        "attempts": [
            {
                "error_category": "ROUTE_UNCONFIRMED",
                "marker_verified": True,
                "result": "UNKNOWN",
                "route_confirmed": False,
            }
        ]
    }
