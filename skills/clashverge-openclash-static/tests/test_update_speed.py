from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest


SKILL_ROOT = Path(__file__).parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CONVERTER = load_module(
    "speed_update_converter",
    SKILL_ROOT / "scripts" / "clashverge_to_openclash.py",
)
REGIONCHECK = load_module(
    "speed_regioncheck_probe",
    SKILL_ROOT / "scripts" / "regioncheck_service_probe.py",
)


@pytest.mark.parametrize("command", ["all", "update-candidate"])
def test_converter_rrc_node_interval_defaults_to_zero_and_keeps_override(command: str) -> None:
    parser = CONVERTER.build_parser()

    default_args = parser.parse_args([command])
    override_args = parser.parse_args([command, "--rrc-node-interval", "2.75"])

    assert default_args.rrc_node_interval == 0.0
    assert override_args.rrc_node_interval == 2.75


class _ParserCaptured(Exception):
    pass


@pytest.mark.parametrize(
    "argv, expected",
    [
        (
            [
                "--skill-script",
                "skill.py",
                "--source-snapshot",
                "source.json",
                "--output",
                "report.json",
            ],
            0.0,
        ),
        (
            [
                "--skill-script",
                "skill.py",
                "--source-snapshot",
                "source.json",
                "--output",
                "report.json",
                "--node-interval",
                "1.5",
            ],
            1.5,
        ),
    ],
)
def test_regioncheck_node_interval_default_and_override(
    monkeypatch,
    argv: list[str],
    expected: float,
) -> None:
    real_parse_args = REGIONCHECK.argparse.ArgumentParser.parse_args
    captured: dict[str, Any] = {}

    def capture_parse_args(parser, args=None, namespace=None):
        captured["parsed"] = real_parse_args(parser, argv, namespace)
        raise _ParserCaptured

    monkeypatch.setattr(
        REGIONCHECK.argparse.ArgumentParser,
        "parse_args",
        capture_parse_args,
    )
    with pytest.raises(_ParserCaptured):
        REGIONCHECK.main()

    assert captured["parsed"].node_interval == expected


@pytest.mark.parametrize(
    "configured_interval, outcome, expected",
    [
        (
            0.0,
            {
                "status": "ATTRIBUTION_MATCH",
                "output_complete": True,
                "transport_unknown": False,
            },
            0.0,
        ),
        (
            0.0,
            {
                "status": "ATTRIBUTION_UNAVAILABLE",
                "output_complete": False,
                "transport_unknown": True,
            },
            3.0,
        ),
        (
            0.0,
            {
                "status": "ATTRIBUTION_MATCH",
                "output_complete": False,
                "transport_unknown": False,
            },
            3.0,
        ),
        (
            0.0,
            {
                "status": "ATTRIBUTION_MATCH",
                "output_complete": True,
                "transport_unknown": True,
            },
            3.0,
        ),
        (
            5.0,
            {
                "status": "ATTRIBUTION_MATCH",
                "output_complete": True,
                "transport_unknown": False,
            },
            5.0,
        ),
        (
            5.0,
            {
                "status": "ATTRIBUTION_UNAVAILABLE",
                "output_complete": False,
                "transport_unknown": True,
            },
            5.0,
        ),
    ],
)
def test_post_probe_interval_preserves_uncertainty_floor(
    configured_interval: float,
    outcome: dict[str, Any],
    expected: float,
) -> None:
    assert REGIONCHECK.post_probe_interval(configured_interval, outcome) == expected


class _ProbeSkill:
    PROBE_SWITCH_WAIT_SECONDS = 0.75

    def __init__(self, events: list[tuple[Any, ...]], readback: str) -> None:
        self.events = events
        self.readback = readback

    def select_probe_node(self, controller_port: int, node_name: str) -> bool:
        self.events.append(("select", controller_port, node_name))
        return True

    def controller_json_request(
        self,
        controller_port: int,
        path: str,
        **kwargs: Any,
    ) -> dict[str, str]:
        self.events.append(
            ("controller", controller_port, path, kwargs.get("method", "GET"))
        )
        if path.startswith("/proxies/"):
            return {"now": self.readback}
        return {}


def _proxy_context() -> Any:
    return REGIONCHECK.resolve_sidecar_proxy_context(
        runner_scope="remote",
        local_proxy_host="127.0.0.1",
        local_proxy_port=17890,
        remote_proxy_host="127.0.0.1",
        remote_proxy_port=17890,
        controller_url="http://127.0.0.1:19090",
    )


def test_probe_resets_connections_and_stabilizes_before_transport_preflight(monkeypatch) -> None:
    events: list[tuple[Any, ...]] = []
    skill = _ProbeSkill(events, "node-a")

    def fake_sleep(seconds: float) -> None:
        events.append(("sleep", seconds))

    def fake_preflight(**kwargs: Any) -> bool:
        events.append(("preflight", kwargs["proxy_url"]))
        return False

    monkeypatch.setattr(REGIONCHECK, "quick_transport_available", fake_preflight)

    outcome = REGIONCHECK.probe_node_with_attribution(
        skill=skill,
        host="router.invalid",
        controller_port=19090,
        proxy_context=_proxy_context(),
        node_name="node-a",
        timeout_seconds=8,
        run_key=b"k" * 32,
        stabilization_seconds=1.25,
        sleep_fn=fake_sleep,
    )

    assert outcome["status"] == "ATTRIBUTION_UNAVAILABLE"
    assert outcome["failure_stage"] == "TRANSPORT_PREFLIGHT"
    assert [event[0] for event in events] == [
        "select",
        "controller",
        "controller",
        "sleep",
        "preflight",
    ]
    assert events[1] == ("controller", 19090, "/proxies/PROBE", "GET")
    assert events[2] == ("controller", 19090, "/connections", "DELETE")
    assert events[3] == ("sleep", 1.25)


def test_probe_selector_mismatch_fails_closed_before_reset_or_preflight(monkeypatch) -> None:
    events: list[tuple[Any, ...]] = []
    skill = _ProbeSkill(events, "different-node")
    monkeypatch.setattr(
        REGIONCHECK,
        "quick_transport_available",
        lambda **_kwargs: pytest.fail("preflight must not run after selector mismatch"),
    )

    with pytest.raises(
        REGIONCHECK.ProbeError,
        match="STOP_RRC_PROXY_ATTRIBUTION_MISMATCH",
    ):
        REGIONCHECK.probe_node_with_attribution(
            skill=skill,
            host="router.invalid",
            controller_port=19090,
            proxy_context=_proxy_context(),
            node_name="node-a",
            timeout_seconds=8,
            run_key=b"k" * 32,
            stabilization_seconds=1.25,
            sleep_fn=lambda _seconds: pytest.fail("reset must not run after mismatch"),
        )

    assert [event[0] for event in events] == ["select", "controller"]
    assert events[1] == ("controller", 19090, "/proxies/PROBE", "GET")
