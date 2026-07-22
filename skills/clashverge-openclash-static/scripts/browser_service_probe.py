#!/usr/bin/env python3
"""Definitive ChatGPT/Gemini Web probes through one fixed sidecar proxy.

The persistent browser profile owns its authentication state. This program
never reads profile storage, cookies, authentication headers, prompts, or
answers and persists only HMAC correlations and structured outcomes.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import select
import socket
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
METHOD_VERSION = "browser-sidecar-functional-v1"
EXIT_URL = "https://api.ipify.org?format=json"
DEFAULT_NODE_INTERVAL_SECONDS = 8.0
DEFAULT_RESPONSE_TIMEOUT_SECONDS = 90.0
DEFAULT_LOGIN_WAIT_SECONDS = 30.0
SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "localstorage",
    "sessionstorage",
    "prompt",
    "response",
    "answer",
    "body",
    "token",
}


class ProbeError(RuntimeError):
    """A safe terminal browser-probe condition."""


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("openclash_skill", path)
    if spec is None or spec.loader is None:
        raise ProbeError("BROWSER_BRIDGE_SKILL_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def hmac_prefix(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:20]


def build_chrome_command(
    executable: Path,
    profile_dir: Path,
    proxy_port: int,
    debug_port: int,
) -> list[str]:
    return [
        str(executable),
        f"--user-data-dir={profile_dir}",
        f"--proxy-server=http://127.0.0.1:{proxy_port}",
        "--proxy-bypass-list=<-loopback>",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={debug_port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "about:blank",
    ]


@contextmanager
def exclusive_profile_lock(profile_dir: Path) -> Iterator[None]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(profile_dir, 0o700)
    lock_path = profile_dir.parent / f".{profile_dir.name}.probe.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProbeError("BROWSER_PROFILE_ALREADY_IN_USE") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            lock_path.unlink(missing_ok=True)


def http_json(url: str, *, method: str = "GET", timeout: float = 2.0) -> Any:
    request = urllib.request.Request(url, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_debug_port(port: int, process: subprocess.Popen[Any]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ProbeError("BROWSER_PROCESS_EXITED_BEFORE_READY")
        try:
            payload = http_json(f"http://127.0.0.1:{port}/json/version", timeout=0.5)
            if isinstance(payload, dict) and payload.get("Browser"):
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.1)
    raise ProbeError("BROWSER_DEBUG_READY_TIMEOUT")


class CDPConnection:
    """Small localhost-only RFC6455 client sufficient for Chrome CDP."""

    def __init__(self, websocket_url: str, timeout: float = 10.0):
        parsed = urllib.parse.urlsplit(websocket_url)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ProbeError("BROWSER_DEBUG_NOT_LOOPBACK")
        self.sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port or 80}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        if not response.startswith(b"HTTP/1.1 101"):
            raise ProbeError("BROWSER_DEBUG_WEBSOCKET_REJECTED")
        self.next_id = 1

    def close(self) -> None:
        try:
            self._send_frame(b"", opcode=8)
        except OSError:
            pass
        self.sock.close()

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        mask = secrets.token_bytes(4)
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend([0x80 | 126])
            header.extend(struct.pack("!H", length))
        else:
            header.extend([0x80 | 127])
            header.extend(struct.pack("!Q", length))
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_exact(self, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self.sock.recv(length - len(chunks))
            if not chunk:
                raise ProbeError("BROWSER_DEBUG_CONNECTION_CLOSED")
            chunks.extend(chunk)
        return bytes(chunks)

    def _recv_frame(self) -> tuple[int, bytes]:
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if second & 0x80 else None
        payload = self._recv_exact(length)
        if mask:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return opcode, payload

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._send_frame(
            json.dumps(
                {"id": request_id, "method": method, "params": params or {}},
                separators=(",", ":"),
            ).encode("utf-8")
        )
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 9:
                self._send_frame(payload, opcode=10)
                continue
            if opcode == 8:
                raise ProbeError("BROWSER_DEBUG_CONNECTION_CLOSED")
            if opcode != 1:
                continue
            message = json.loads(payload.decode("utf-8"))
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise ProbeError("BROWSER_DEBUG_COMMAND_FAILED")
            return message.get("result", {})


class ChromeProbe:
    def __init__(self, executable: Path, profile_dir: Path, proxy_port: int):
        self.executable = executable
        self.profile_dir = profile_dir
        self.proxy_port = proxy_port
        self.debug_port = reserve_loopback_port()
        self.process: subprocess.Popen[Any] | None = None
        self.cdp: CDPConnection | None = None

    def __enter__(self) -> "ChromeProbe":
        command = build_chrome_command(
            self.executable, self.profile_dir, self.proxy_port, self.debug_port
        )
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            wait_for_debug_port(self.debug_port, self.process)
            targets = http_json(f"http://127.0.0.1:{self.debug_port}/json/list")
            pages = [item for item in targets if item.get("type") == "page"]
            if not pages:
                raise ProbeError("BROWSER_PAGE_TARGET_MISSING")
            self.cdp = CDPConnection(str(pages[0]["webSocketDebuggerUrl"]))
            self.cdp.call("Page.enable")
            self.cdp.call("Runtime.enable")
            return self
        except Exception:
            self.__exit__()
            raise

    def __exit__(self, *_: Any) -> None:
        if self.cdp is not None:
            self.cdp.close()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def evaluate(self, expression: str) -> Any:
        if self.cdp is None:
            raise ProbeError("BROWSER_NOT_CONNECTED")
        result = self.cdp.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        return result.get("result", {}).get("value")

    def navigate(self, url: str, timeout: float = 30.0) -> None:
        if self.cdp is None:
            raise ProbeError("BROWSER_NOT_CONNECTED")
        self.cdp.call("Page.navigate", {"url": url})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.evaluate("document.readyState")
            if state in {"interactive", "complete"}:
                return
            time.sleep(0.2)
        raise ProbeError("BROWSER_NAVIGATION_TIMEOUT")

    def focus_selector(self, selectors: list[str]) -> bool:
        expression = """
(() => {
  const selectors = %s;
  for (const selector of selectors) {
    const element = document.querySelector(selector);
    if (element && element.offsetParent !== null) { element.focus(); return true; }
  }
  return false;
})()
""" % json.dumps(selectors)
        return bool(self.evaluate(expression))

    def insert_text(self, text: str) -> None:
        if self.cdp is None:
            raise ProbeError("BROWSER_NOT_CONNECTED")
        self.cdp.call("Input.insertText", {"text": text})

    def press_enter(self) -> None:
        if self.cdp is None:
            raise ProbeError("BROWSER_NOT_CONNECTED")
        for event_type in ("keyDown", "char", "keyUp"):
            self.cdp.call(
                "Input.dispatchKeyEvent",
                {
                    "type": event_type,
                    "key": "Enter",
                    "code": "Enter",
                    "windowsVirtualKeyCode": 13,
                    "nativeVirtualKeyCode": 13,
                    "text": "\r" if event_type == "char" else "",
                },
            )


SERVICE_SPECS = {
    "gpt": {
        "url": "https://chatgpt.com/",
        "inputs": ["#prompt-textarea", "textarea", "div[contenteditable='true']"],
        "answers": "[data-message-author-role='assistant']",
        "stop": "[data-testid='stop-button']",
    },
    "gemini": {
        "url": "https://gemini.google.com/app",
        "inputs": [
            "rich-textarea div[contenteditable='true']",
            ".ql-editor[contenteditable='true']",
            "div[contenteditable='true'][role='textbox']",
            "div[contenteditable='true']",
            "textarea",
        ],
        "answers": "model-response, .model-response-text, [data-test-id='model-response']",
        "stop": "button[aria-label*='Stop'], button[aria-label*='stop']",
    },
}


def safe_page_state(browser: ChromeProbe, service: str) -> str:
    spec = SERVICE_SPECS[service]
    expression = """
(() => {
  const text = (document.body?.innerText || '').toLowerCase();
  const url = location.href.toLowerCase();
  const hasInput = %s.some(selector => {
    const element = document.querySelector(selector);
    return Boolean(element && element.offsetParent !== null);
  });
  if (url.includes('accounts.google.com') || url.includes('/auth') || url.includes('/login') || /(sign in|log in|登录|登入)/.test(text)) return 'LOGIN_REQUIRED';
  if (/captcha|verify you are human|cloudflare|unusual traffic|验证您是真人|异常流量/.test(text)) return 'CHALLENGE';
  if (/too many requests|rate limit|try again later|请求过多|稍后重试/.test(text)) return 'RATE_LIMIT';
  if (/unsupported country|not available in your country|not available in your region|地区目前不支持|所在地区不可用/.test(text)) return 'UNSUPPORTED_REGION';
  return hasInput ? 'READY' : 'AUTOMATION_UNAVAILABLE';
})()
""" % json.dumps(spec["inputs"])
    return str(browser.evaluate(expression))


def wait_for_service_state(
    browser: ChromeProbe, service: str, timeout_seconds: float = 15.0
) -> str:
    """Allow SPA hydration, but never wait through an explicit terminal state."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        state = safe_page_state(browser, service)
        if state != "AUTOMATION_UNAVAILABLE" or time.monotonic() >= deadline:
            return state
        time.sleep(0.25)


def safe_page_diagnostics(browser: ChromeProbe, service: str) -> dict[str, Any]:
    """Return structural booleans and counts, never DOM text or auth state."""
    spec = SERVICE_SPECS[service]
    expression = """
(() => {
  const text = (document.body?.innerText || '').toLowerCase();
  const selectors = %s;
  const counts = {};
  const visible = {};
  for (const selector of selectors) {
    const nodes = Array.from(document.querySelectorAll(selector));
    counts[selector] = nodes.length;
    visible[selector] = nodes.filter(node => node.offsetParent !== null).length;
  }
  return {
    origin: location.origin,
    path: location.pathname,
    ready_state: document.readyState,
    selector_counts: counts,
    visible_selector_counts: visible,
    iframe_count: document.querySelectorAll('iframe').length,
    has_sign_in_marker: /(sign in|log in|登录|登入)/.test(text),
    has_challenge_marker: /captcha|verify you are human|cloudflare|unusual traffic|验证您是真人|异常流量/.test(text),
    has_unsupported_marker: /unsupported country|not available in your country|not available in your region|地区目前不支持|所在地区不可用/.test(text)
  };
})()
""" % json.dumps(spec["inputs"])
    value = browser.evaluate(expression)
    return value if isinstance(value, dict) else {"diagnostic": "UNAVAILABLE"}


def browser_exit_ip(browser: ChromeProbe) -> str:
    browser.navigate(EXIT_URL)
    value = browser.evaluate(
        """
(() => {
  try { return JSON.parse(document.body?.innerText || '{}').ip || ''; }
  catch (_) { return ''; }
})()
"""
    )
    try:
        socket.inet_pton(socket.AF_INET, str(value))
    except OSError:
        try:
            socket.inet_pton(socket.AF_INET6, str(value))
        except OSError as exc:
            raise ProbeError("FAIL_BROWSER_PROXY_ATTRIBUTION") from exc
    return str(value)


def control_exit_ip(proxy_port: int) -> str:
    completed = subprocess.run(
        [
            "curl",
            "--proxy",
            f"http://127.0.0.1:{proxy_port}",
            "--connect-timeout",
            "3",
            "--max-time",
            "8",
            "--silent",
            "--show-error",
            EXIT_URL,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise ProbeError("FAIL_BROWSER_PROXY_ATTRIBUTION")
    try:
        value = str(json.loads(completed.stdout)["ip"])
        socket.inet_pton(socket.AF_INET, value)
    except (KeyError, json.JSONDecodeError, OSError):
        try:
            socket.inet_pton(socket.AF_INET6, value)
        except (OSError, UnboundLocalError) as exc:
            raise ProbeError("FAIL_BROWSER_PROXY_ATTRIBUTION") from exc
    return value


def verify_proxy_attribution(
    browser: ChromeProbe, proxy_port: int, run_key: bytes
) -> str:
    control_ip = control_exit_ip(proxy_port)
    browser_ip = browser_exit_ip(browser)
    control_hash = hmac_prefix(run_key, control_ip)
    browser_hash = hmac_prefix(run_key, browser_ip)
    if not hmac.compare_digest(control_hash, browser_hash):
        raise ProbeError("FAIL_BROWSER_PROXY_ATTRIBUTION")
    return browser_hash


def wait_for_answer(
    browser: ChromeProbe,
    service: str,
    nonce: str,
    baseline_count: int,
    timeout_seconds: float,
) -> str:
    spec = SERVICE_SPECS[service]
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = safe_page_state(browser, service)
        if state in {"LOGIN_REQUIRED", "CHALLENGE", "RATE_LIMIT", "UNSUPPORTED_REGION"}:
            return state
        expression = """
(() => {
  const nodes = Array.from(document.querySelectorAll(%s));
  const fresh = nodes.slice(%d);
  const matched = fresh.some(node => (node.innerText || '').includes(%s));
  const generating = Boolean(document.querySelector(%s));
  return {count: nodes.length, matched, generating};
})()
""" % (
            json.dumps(spec["answers"]),
            baseline_count,
            json.dumps(nonce),
            json.dumps(spec["stop"]),
        )
        observation = browser.evaluate(expression) or {}
        if observation.get("matched") and not observation.get("generating"):
            return "PASS"
        time.sleep(0.5)
    return "NO_NEW_ANSWER"


def run_generation(
    browser: ChromeProbe,
    service: str,
    nonce: str,
    timeout_seconds: float,
) -> str:
    spec = SERVICE_SPECS[service]
    browser.navigate(str(spec["url"]))
    state = safe_page_state(browser, service)
    if state != "READY":
        return state
    baseline = int(
        browser.evaluate(
            "document.querySelectorAll(%s).length" % json.dumps(spec["answers"])
        )
        or 0
    )
    if not browser.focus_selector(list(spec["inputs"])):
        return "AUTOMATION_UNAVAILABLE"
    browser.insert_text(f"只回复：{nonce}")
    browser.press_enter()
    return wait_for_answer(browser, service, nonce, baseline, timeout_seconds)


def map_outcome(outcome: str) -> tuple[str, str | None]:
    if outcome == "PASS":
        return "PASS", None
    mapping = {
        "LOGIN_REQUIRED": "UNKNOWN_LOGIN_REQUIRED",
        "CHALLENGE": "UNKNOWN_CHALLENGE",
        "RATE_LIMIT": "UNKNOWN_ACCOUNT_RATE_LIMIT",
        "AUTOMATION_UNAVAILABLE": "UNKNOWN_AUTOMATION_UNAVAILABLE",
        "NO_NEW_ANSWER": "FAIL_NO_NEW_ANSWER",
        "UNSUPPORTED_REGION": "FAIL_UNSUPPORTED_REGION",
    }
    return "FAIL" if outcome in {"NO_NEW_ANSWER", "UNSUPPORTED_REGION"} else "UNKNOWN", mapping.get(outcome, "UNKNOWN_AUTOMATION_UNAVAILABLE")


def validate_safe_report(report: dict[str, Any]) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in SENSITIVE_KEYS:
                    raise ProbeError("BROWSER_REPORT_SENSITIVE_FIELD")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str) and (
            "GPT_NODE_TEST_" in value or "GEMINI_NODE_TEST_" in value
        ):
            raise ProbeError("BROWSER_REPORT_RAW_NONCE")

    walk(report)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    validate_safe_report(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-script", type=Path, required=True)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--browser-executable", type=Path, required=True)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", default="root@192.168.10.1")
    parser.add_argument("--core-path", default="/etc/openclash/core/clash_meta")
    parser.add_argument("--node-interval", type=float, default=DEFAULT_NODE_INTERVAL_SECONDS)
    parser.add_argument("--response-timeout", type=float, default=DEFAULT_RESPONSE_TIMEOUT_SECONDS)
    parser.add_argument("--login-wait", type=float, default=DEFAULT_LOGIN_WAIT_SECONDS)
    parser.add_argument("--skip-gemini-node", action="append", default=[])
    args = parser.parse_args()

    skill = load_module(args.skill_script.resolve())
    manifest, payload_path = skill.verify_source_snapshot(args.source_snapshot.resolve())
    data = skill.load_yaml(payload_path)
    proxies = skill.static_proxy_objects(data)
    identities = {
        str(item["exact_node_name"]): str(item["exact_node_id"])
        for item in manifest["nodes"]
    }
    unknown_skips = set(args.skip_gemini_node) - set(identities)
    if unknown_skips:
        raise ProbeError("GEMINI_SKIP_NODE_NOT_IN_SNAPSHOT")
    config = skill.build_probe_config(
        proxies,
        mixed_port=skill.REMOTE_SIDECAR_MIXED_PORT,
        controller_port=skill.REMOTE_SIDECAR_CONTROLLER_PORT,
        interface_name=None,
    )
    run_key = secrets.token_bytes(32)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "probe_method_version": METHOD_VERSION,
        "source_snapshot_id": manifest["source_snapshot_id"],
        "source_hash": manifest["source_hash"],
        "started_at": iso_now(),
        "browser_profile": "DEDICATED_PERSISTENT_PROFILE_REDACTED",
        "cookies_exported": False,
        "system_proxy_changed": False,
        "tun_changed": False,
        "production_fingerprint_preserved": False,
        "browser_proxy_attribution": "PENDING",
        "status": "RUNNING",
        "results": [],
    }
    with tempfile.TemporaryDirectory(prefix="browser-service-sidecar-") as temporary:
        config_path = Path(temporary) / "probe.yaml"
        skill.dump_yaml(config, config_path)
        os.chmod(config_path, 0o600)
        with skill.remote_candidate_sidecar(
            config_path, host=args.host, core_path=args.core_path
        ) as sidecar, exclusive_profile_lock(args.profile_dir.resolve()), ChromeProbe(
            args.browser_executable.resolve(),
            args.profile_dir.resolve(),
            sidecar.mixed_port,
        ) as browser:
            skill.validate_probe_runtime(sidecar.controller_port)
            first_name = str(proxies[0]["name"])
            if not skill.select_probe_node(sidecar.controller_port, first_name):
                raise ProbeError("NODE_SWITCH_UNCONFIRMED")
            time.sleep(skill.PROBE_SWITCH_WAIT_SECONDS)
            verify_proxy_attribution(browser, sidecar.mixed_port, run_key)
            report["browser_proxy_attribution"] = "CONTROL_AND_BROWSER_EGRESS_HMAC_MATCH"
            preflight_states: dict[str, str] = {}
            preflight_diagnostics: dict[str, dict[str, Any]] = {}
            for service in ("gpt", "gemini"):
                browser.navigate(str(SERVICE_SPECS[service]["url"]))
                preflight_states[service] = wait_for_service_state(browser, service)
                preflight_diagnostics[service] = safe_page_diagnostics(browser, service)
            missing_login = [
                service for service, state in preflight_states.items()
                if state == "LOGIN_REQUIRED"
            ]
            if missing_login:
                browser.navigate(str(SERVICE_SPECS[missing_login[0]]["url"]))
                report["status"] = "STOP_BROWSER_LOGIN_REQUIRED"
                report["login_required_services"] = missing_login
                report["preflight_diagnostics"] = preflight_diagnostics
                time.sleep(max(0.0, args.login_wait))
            elif any(
                state in {"CHALLENGE", "RATE_LIMIT", "AUTOMATION_UNAVAILABLE"}
                for state in preflight_states.values()
            ):
                report["status"] = "STOP_BROWSER_PREFLIGHT_UNAVAILABLE"
                report["preflight_states"] = preflight_states
                report["preflight_diagnostics"] = preflight_diagnostics
                unavailable = next(
                    service for service, state in preflight_states.items()
                    if state in {"CHALLENGE", "RATE_LIMIT", "AUTOMATION_UNAVAILABLE"}
                )
                browser.navigate(str(SERVICE_SPECS[unavailable]["url"]))
                time.sleep(max(0.0, args.login_wait))
            else:
                stop_service: set[str] = set()
                for proxy in proxies:
                    name = str(proxy["name"])
                    node_id = identities[name]
                    if not skill.select_probe_node(sidecar.controller_port, name):
                        raise ProbeError("NODE_SWITCH_UNCONFIRMED")
                    time.sleep(skill.PROBE_SWITCH_WAIT_SECONDS)
                    egress_hash = verify_proxy_attribution(
                        browser, sidecar.mixed_port, run_key
                    )
                    for service in ("gpt", "gemini"):
                        if service in stop_service:
                            continue
                        if service == "gemini" and name in set(args.skip_gemini_node):
                            continue
                        nonce = f"{service.upper()}_NODE_TEST_{secrets.token_hex(8)}"
                        outcome = run_generation(
                            browser, service, nonce, args.response_timeout
                        )
                        result, error = map_outcome(outcome)
                        report["results"].append(
                            {
                                "service": service,
                                "exact_node_id": node_id,
                                "exact_node_name": name,
                                "source_snapshot_id": manifest["source_snapshot_id"],
                                "source_hash": manifest["source_hash"],
                                "tested_at": iso_now(),
                                "probe_method_version": METHOD_VERSION,
                                "nonce_hmac": hmac_prefix(run_key, nonce),
                                "egress_hmac": egress_hash,
                                "result": result,
                                "error_category": error,
                            }
                        )
                        if error in {
                            "UNKNOWN_ACCOUNT_RATE_LIMIT",
                            "UNKNOWN_LOGIN_REQUIRED",
                            "UNKNOWN_CHALLENGE",
                            "UNKNOWN_AUTOMATION_UNAVAILABLE",
                        }:
                            stop_service.add(service)
                    time.sleep(max(0.0, args.node_interval))
                report["status"] = "COMPLETE"
    report["production_fingerprint_preserved"] = True
    report["completed_at"] = iso_now()
    atomic_json(args.output.resolve(), report)
    print(report["status"])
    return 0 if report["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
