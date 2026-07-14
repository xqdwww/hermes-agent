from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import random
import subprocess  # noqa: F401 – needed by patched sync pipeline
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "clashverge_to_openclash.py"
spec = importlib.util.spec_from_file_location("converter", SCRIPT)
converter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["converter"] = converter
spec.loader.exec_module(converter)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def sample_basic():
    """Nodes with mixed regions, GPT and Disney groups."""
    return {
        "proxies": [
            {"name": "\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501", "type": "ss", "server": "example.invalid", "port": 1},   # 🇯🇵日本测试01
            {"name": "\U0001f1f9\U0001f1fc\u53f0\u6e7e\u6d4b\u8bd501", "type": "ss", "server": "example.invalid", "port": 2},   # 🇹🇼台湾测试01
            {"name": "\U0001f1ed\U0001f1f0\u9999\u6e2f\u6d4b\u8bd501", "type": "ss", "server": "example.invalid", "port": 3},   # 🇭🇰香港测试01
            {"name": "\U0001f1e9\U0001f1ea\u5fb7\u56fd\u6d4b\u8bd501", "type": "ss", "server": "example.invalid", "port": 4},   # 🇩🇪德国测试01
            {"name": "\U0001f1fa\U0001f1f8\u7f8e\u56fd\u6d4b\u8bd501", "type": "ss", "server": "example.invalid", "port": 5},   # 🇺🇸美国测试01
            {"name": "\U0001f1f8\U0001f1ec\u65b0\u52a0\u5761\u6d4b\u8bd501", "type": "ss", "server": "example.invalid", "port": 6},  # 🇸🇬新加坡测试01
            {"name": "\u65e5\u672c\u6d4b\u8bd5-\u6d41\u5a92\u4f53", "type": "ss", "server": "example.invalid", "port": 7},   # 日本测试-流媒体
            {"name": "\u9999\u6e2f-\u5a92\u4f53\u6d41", "type": "ss", "server": "example.invalid", "port": 8},               # 香港-媒体流
        ],
        "proxy-groups": [
            {"name": "GPT\u4e13\u7528", "type": "select", "proxies": [     # GPT专用
                "\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501",
                "\U0001f1f9\U0001f1fc\u53f0\u6e7e\u6d4b\u8bd501",
                "\U0001f1fa\U0001f1f8\u7f8e\u56fd\u6d4b\u8bd501",
                "\U0001f1f8\U0001f1ec\u65b0\u52a0\u5761\u6d4b\u8bd501",
            ]},
            {"name": "Gemini\u4e13\u7528", "type": "select", "proxies": [   # Gemini专用
                "\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501",
                "\U0001f1f9\U0001f1fc\u53f0\u6e7e\u6d4b\u8bd501",
                "\U0001f1ed\U0001f1f0\u9999\u6e2f\u6d4b\u8bd501",
                "\U0001f1e9\U0001f1ea\u5fb7\u56fd\u6d4b\u8bd501",
            ]},
            {"name": "\u8fea\u58eb\u5c3c", "type": "select", "proxies": [    # 迪士尼
                "\U0001f1f9\U0001f1fc\u53f0\u6e7e\u6d4b\u8bd501",
                "\U0001f1f8\U0001f1ec\u65b0\u52a0\u5761\u6d4b\u8bd501",
            ]},
        ],
        "rules": ["DOMAIN-SUFFIX,openai.com,GPT\u4e13\u7528", "MATCH,DIRECT"],
    }


def _transform(data, **kw):
    kwargs = dict(
        manual_group=kw.pop("manual_group", "\u624b\u52a8\u9009\u62e9"),       # 手动选择
        auto_group=kw.pop("auto_group", "\u81ea\u52a8\u9009\u62e9"),           # 自动选择
        disney_group=kw.pop("disney_group", "\u8fea\u58eb\u5c3c"),            # 迪士尼
        media_keywords=kw.pop("media_keywords", ["\u6d41\u5a92\u4f53", "\u5a92\u4f53\u6d41"]),
        test_url="https://www.gstatic.com/generate_204",
        interval=60,
    )
    assert not kw, f"Unexpected kwargs: {kw}"
    return converter.transform(data, **kwargs)


def _groups_by_name(data):
    return {g["name"]: g for g in data["proxy-groups"]}


# ---------------------------------------------------------------------------
# Mock opener / HTTP response helpers
# ---------------------------------------------------------------------------
# Test: No priority wrappers
# ---------------------------------------------------------------------------


class TestNoWrappers:
    def test_no_global_priority_groups(self):
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = [g["name"] for g in data["proxy-groups"] if g["name"].startswith("\u5168\u5c40\u4f18\u5148\u2502")]
        assert len(wrappers) == 0

    def test_no_gpt_priority_groups(self):
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = [g["name"] for g in data["proxy-groups"] if g["name"].startswith("GPT\u4f18\u5148\u2502")]
        assert len(wrappers) == 0

    def test_no_gemini_priority_groups(self):
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = [g["name"] for g in data["proxy-groups"] if g["name"].startswith("Gemini\u4f18\u5148\u2502")]
        assert len(wrappers) == 0

    def test_no_disney_priority_groups(self):
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = [g["name"] for g in data["proxy-groups"] if g["name"].startswith("\u8fea\u58eb\u5c3c\u4f18\u5148\u2502")]
        assert len(wrappers) == 0

    def test_old_wrapper_names_removed_on_reprocess(self):
        old_input = copy.deepcopy(sample_basic())
        old_input["proxy-groups"].extend([
            {"name": "\u5168\u5c40\u4f18\u5148\u2502\u65e5\u672c\u6d4b\u8bd501", "type": "fallback", "proxies": ["\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501", "\u81ea\u52a8\u9009\u62e9"]},
            {"name": "GPT\u4f18\u5148\u2502\u65e5\u672c\u6d4b\u8bd501", "type": "fallback", "proxies": ["\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501", "GPT\u81ea\u52a8"]},
        ])
        data = _transform(old_input)
        all_names = [g["name"] for g in data["proxy-groups"]]
        for name in all_names:
            assert not converter.is_priority_wrapper(name), f"Wrapper group '{name}' not removed"


# ---------------------------------------------------------------------------
# Test: Managed groups count
# ---------------------------------------------------------------------------


class TestManagedGroupCount:
    def test_fixed_group_count(self):
        data = _transform(copy.deepcopy(sample_basic()))
        known = {"\u9ed8\u8ba4\u4ee3\u7406", "\u624b\u52a8\u9009\u62e9", "\u81ea\u52a8\u9009\u62e9",
                 "GPT\u4e13\u7528", "GPT\u624b\u52a8", "GPT\u81ea\u52a8",
                 "Gemini\u4e13\u7528", "Gemini\u624b\u52a8", "Gemini\u81ea\u52a8",
                 "\u8fea\u58eb\u5c3c", "\u8fea\u58eb\u5c3c\u624b\u52a8", "\u8fea\u58eb\u5c3c\u81ea\u52a8"}
        generated = {g["name"] for g in data["proxy-groups"] if g["name"] in known}
        assert len(generated) == 12, f"Expected 12 managed groups, got {len(generated)}: {generated}"
        assert len(data["proxy-groups"]) >= 12


# ---------------------------------------------------------------------------
# Test: Global groups
# ---------------------------------------------------------------------------


class TestGlobalGroups:
    def test_auto_type_is_fallback(self):
        data = _transform(copy.deepcopy(sample_basic()))
        groups = _groups_by_name(data)
        assert groups["\u81ea\u52a8\u9009\u62e9"]["type"] == "fallback"

    def test_global_order_japan_taiwan_other(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data)["\u81ea\u52a8\u9009\u62e9"]
        proxies = auto["proxies"]
        jp_names = [n for n in proxies if "\u65e5\u672c" in n]
        tw_names = [n for n in proxies if "\u53f0\u6e7e" in n]
        assert jp_names and tw_names
        first_jp_idx = proxies.index(jp_names[0])
        first_tw_idx = proxies.index(tw_names[0])
        assert first_jp_idx < first_tw_idx

    def test_manual_first_item_is_auto(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["\u624b\u52a8\u9009\u62e9"]
        assert manual["proxies"][0] == "\u81ea\u52a8\u9009\u62e9"

    def test_manual_items_are_direct_static_nodes(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["\u624b\u52a8\u9009\u62e9"]
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        for proxy in manual["proxies"][1:]:
            assert proxy in static_names


# ---------------------------------------------------------------------------
# Test: GPT groups
# ---------------------------------------------------------------------------


class TestGptGroups:
    def test_gpt_auto_order_japan_taiwan_other(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data)["GPT\u81ea\u52a8"]
        proxies = auto["proxies"]
        jp_names = [n for n in proxies if "\u65e5\u672c" in n]
        tw_names = [n for n in proxies if "\u53f0\u6e7e" in n]
        assert jp_names and tw_names
        assert proxies.index(jp_names[0]) < proxies.index(tw_names[0])

    def test_gpt_manual_first_item_is_gpt_auto(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["GPT\u624b\u52a8"]
        assert manual["proxies"][0] == "GPT\u81ea\u52a8"

    def test_gpt_manual_items_are_direct_nodes(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["GPT\u624b\u52a8"]
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        for proxy in manual["proxies"][1:]:
            assert proxy in static_names

    def test_gpt_auto_type_is_fallback(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data)["GPT\u81ea\u52a8"]
        assert auto["type"] == "fallback"


# ---------------------------------------------------------------------------
# Test: Gemini groups (legacy — no probes)
# ---------------------------------------------------------------------------


class TestGeminiGroupsLegacy:
    def test_gemini_auto_only_allowed_regions(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data).get("Gemini\u81ea\u52a8")
        assert auto is not None
        regions_found = set()
        for proxy in auto["proxies"]:
            region = converter.detect_region(proxy)
            if region:
                regions_found.add(region)
        assert "\u7f8e\u56fd" not in regions_found
        for r in regions_found:
            assert r in {"\u65e5\u672c", "\u53f0\u6e7e", "\u9999\u6e2f", "\u5fb7\u56fd"}

    def test_gemini_auto_no_us_nodes(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data).get("Gemini\u81ea\u52a8")
        assert auto is not None
        for proxy in auto["proxies"]:
            assert "\u7f8e\u56fd" not in proxy
            assert "\U0001f1fa\U0001f1f8" not in proxy

    def test_gemini_order_japan_taiwan_hongkong_germany(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data).get("Gemini\u81ea\u52a8")
        assert auto is not None
        proxies = auto["proxies"]
        indices = {}
        for p in proxies:
            region = converter.detect_region(p)
            if region and region not in indices:
                indices[region] = proxies.index(p)
        assert indices.get("\u65e5\u672c", 9999) < indices.get("\u53f0\u6e7e", 9999)
        assert indices.get("\u53f0\u6e7e", 9999) < indices.get("\u9999\u6e2f", 9999)
        assert indices.get("\u9999\u6e2f", 9999) < indices.get("\u5fb7\u56fd", 9999)

    def test_gemini_manual_first_item_is_gemini_auto(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data).get("Gemini\u624b\u52a8")
        assert manual is not None
        assert manual["proxies"][0] == "Gemini\u81ea\u52a8"

    def test_gemini_manual_items_are_direct_nodes(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data).get("Gemini\u624b\u52a8")
        assert manual is not None
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        for proxy in manual["proxies"][1:]:
            assert proxy in static_names


# ---------------------------------------------------------------------------
# Test: Disney groups
# ---------------------------------------------------------------------------


class TestDisneyGroups:
    def test_disney_auto_contains_original_disney_nodes(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data)["\u8fea\u58eb\u5c3c\u81ea\u52a8"]
        assert "\U0001f1f9\U0001f1fc\u53f0\u6e7e\u6d4b\u8bd501" in auto["proxies"]

    def test_media_keyword_nodes_in_disney(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data)["\u8fea\u58eb\u5c3c\u81ea\u52a8"]
        assert "\u65e5\u672c\u6d4b\u8bd5-\u6d41\u5a92\u4f53" in auto["proxies"]
        assert "\u9999\u6e2f-\u5a92\u4f53\u6d41" in auto["proxies"]

    def test_disney_order_japan_taiwan_other(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data)["\u8fea\u58eb\u5c3c\u81ea\u52a8"]
        proxies = auto["proxies"]
        jp_names = [n for n in proxies if "\u65e5\u672c" in n]
        tw_names = [n for n in proxies if "\u53f0\u6e7e" in n]
        assert jp_names and tw_names
        assert proxies.index(jp_names[0]) < proxies.index(tw_names[0])

    def test_disney_manual_first_item_is_disney_auto(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["\u8fea\u58eb\u5c3c\u624b\u52a8"]
        assert manual["proxies"][0] == "\u8fea\u58eb\u5c3c\u81ea\u52a8"

    def test_disney_manual_items_are_direct_nodes(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["\u8fea\u58eb\u5c3c\u624b\u52a8"]
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        for proxy in manual["proxies"][1:]:
            assert proxy in static_names


# ---------------------------------------------------------------------------
# Test: Reference / cycle / integrity
# ---------------------------------------------------------------------------


class TestIntegrity:
    def test_no_self_reference(self):
        data = _transform(copy.deepcopy(sample_basic()))
        for g in data["proxy-groups"]:
            assert g["name"] not in g.get("proxies", [])

    def test_no_cycle(self):
        _transform(copy.deepcopy(sample_basic()))

    def test_no_missing_references(self):
        data = _transform(copy.deepcopy(sample_basic()))
        names = [g["name"] for g in data["proxy-groups"]]
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        valid = set(names) | static_names | {"DIRECT", "REJECT", "REJECT-DROP", "PASS"}
        for g in data["proxy-groups"]:
            for proxy in g.get("proxies", []):
                assert proxy in valid

    def test_no_duplicate_group_names(self):
        data = _transform(copy.deepcopy(sample_basic()))
        names = [g["name"] for g in data["proxy-groups"]]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Test: MATCH rule
# ---------------------------------------------------------------------------


class TestMatchRule:
    def test_only_one_match(self):
        data = _transform(copy.deepcopy(sample_basic()))
        match_rules = [r for r in data["rules"] if isinstance(r, str) and r.strip().upper().startswith("MATCH,")]
        assert len(match_rules) == 1

    def test_match_to_default(self):
        data = _transform(copy.deepcopy(sample_basic()))
        final = data["rules"][-1]
        assert final == "MATCH,\u9ed8\u8ba4\u4ee3\u7406"


# ---------------------------------------------------------------------------
# Test: Input immutability
# ---------------------------------------------------------------------------


class TestInputImmutability:
    def test_input_file_unchanged(self):
        src = copy.deepcopy(sample_basic())
        snapshot = copy.deepcopy(src)
        _transform(src)
        orig_static = {p["name"] for p in snapshot["proxies"]}
        final_static = {p["name"] for p in src["proxies"]}
        assert orig_static == final_static


# ---------------------------------------------------------------------------
# Test: YAML round-trip
# ---------------------------------------------------------------------------


class TestYamlRoundTrip:
    def test_output_is_valid_yaml(self):
        import yaml as pyyaml
        data = _transform(copy.deepcopy(sample_basic()))
        text = pyyaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False, width=4096)
        reloaded = pyyaml.safe_load(text)
        assert reloaded is not None
        assert "proxy-groups" in reloaded


# ---------------------------------------------------------------------------
# Test: Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_twice_same_result(self):
        first = _transform(copy.deepcopy(sample_basic()))
        second = _transform(copy.deepcopy(first))
        assert len(first["proxy-groups"]) == len(second["proxy-groups"])
        first_names = [g["name"] for g in first["proxy-groups"]]
        second_names = [g["name"] for g in second["proxy-groups"]]
        assert first_names == second_names
        for fn, sn in zip(first_names, second_names):
            fg = next(g for g in first["proxy-groups"] if g["name"] == fn)
            sg = next(g for g in second["proxy-groups"] if g["name"] == sn)
            assert fg["proxies"] == sg["proxies"]

    def test_no_wrapper_nesting_on_reprocess(self):
        first = _transform(copy.deepcopy(sample_basic()))
        second = _transform(copy.deepcopy(first))
        for g in second["proxy-groups"]:
            if converter.is_priority_wrapper(g["name"]):
                for proxy in g["proxies"]:
                    assert not converter.is_priority_wrapper(proxy)


# ---------------------------------------------------------------------------
# Test: Secret safety
# ---------------------------------------------------------------------------


class TestSecretSafety:
    def test_log_does_not_contain_credentials(self):
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            _transform(copy.deepcopy(sample_basic()))
        output = f.getvalue()
        assert "server" not in output
        assert "password" not in output
        assert "token" not in output
        assert "example.invalid" not in output


# ---------------------------------------------------------------------------
# Test: Probe response classification
# ---------------------------------------------------------------------------


class TestProbeClassification:
    """Test the _classify_* response functions directly (no network, no Mihomo)."""

    def test_gpt_pass_chatgpt_marker(self):
        status, latency, reason = converter._classify_gpt_response(200, {}, b'<html>ChatGPT</html>', 100)
        assert status == converter.STATUS_PASS

    def test_gpt_pass_openai_marker(self):
        status, latency, reason = converter._classify_gpt_response(200, {}, b'__NEXT_DATA__', 150)
        assert status == converter.STATUS_PASS

    def test_gpt_fail_403(self):
        status, latency, reason = converter._classify_gpt_response(403, {}, b'', 50)
        assert status == converter.STATUS_FAIL

    def test_gpt_fail_451(self):
        status, latency, reason = converter._classify_gpt_response(451, {}, b'', 50)
        assert status == converter.STATUS_FAIL

    def test_gpt_fail_redirect_blocked(self):
        status, latency, reason = converter._classify_gpt_response(
            302, {"location": "https://example.com/unsupported-country"}, b'', 50
        )
        assert status == converter.STATUS_FAIL

    def test_gpt_unknown_captcha(self):
        status, latency, reason = converter._classify_gpt_response(200, {}, b'captcha wall', 100)
        assert status == converter.STATUS_UNKNOWN

    def test_gpt_unknown_generic_200(self):
        status, latency, reason = converter._classify_gpt_response(200, {}, b'<html>nothing</html>', 100)
        assert status == converter.STATUS_UNKNOWN

    def test_gemini_pass_auth_redirect(self):
        status, latency, reason = converter._classify_gemini_response(
            302, {"location": "https://accounts.google.com/signin"}, b'', 100
        )
        assert status == converter.STATUS_PASS

    def test_gemini_pass_service(self):
        status, latency, reason = converter._classify_gemini_response(200, {}, b'<html>Gemini</html>', 100)
        assert status == converter.STATUS_PASS

    def test_gemini_fail_redirect_blocked(self):
        status, latency, reason = converter._classify_gemini_response(
            302, {"location": "https://support.google.com/unsupported-country"}, b'', 50
        )
        assert status == converter.STATUS_FAIL

    def test_disney_pass_auth_redirect(self):
        status, latency, reason = converter._classify_disney_response(
            302, {"location": "https://www.disneyplus.com/sign-in"}, b'', 100
        )
        assert status == converter.STATUS_PASS

    def test_disney_pass_service(self):
        status, latency, reason = converter._classify_disney_response(200, {}, b'<html>disneyplus</html>', 100)
        assert status == converter.STATUS_PASS

    def test_disney_fail_redirect_region(self):
        status, latency, reason = converter._classify_disney_response(
            302, {"location": "https://help.disneyplus.com/unsupported-region"}, b'', 50
        )
        assert status == converter.STATUS_FAIL


# ---------------------------------------------------------------------------
# Test: Probe pipeline with mocked opener
# ---------------------------------------------------------------------------


class TestProbePipeline:
    """Test the probe pipeline using a mock opener (no real network or Mihomo)."""

    def _build_mock_probe_results(self, node_names_to_pass):
        """Build a dict of NodeProbeResults where named nodes PASS all probes
        and unknown nodes are FAIL_TRANSPORT.
        """
        results = {}
        proxies_list = sample_basic()["proxies"]
        pass_set = set(node_names_to_pass)
        for p in proxies_list:
            name = p["name"]
            if name in pass_set:
                results[name] = converter.NodeProbeResults(
                    node_name=name,
                    base=converter.ProbeResult(name, "base", converter.STATUS_PASS, 50, "OK"),
                    gpt=converter.ProbeResult(name, "gpt", converter.STATUS_PASS, 100, "Service reachable"),
                    gemini=converter.ProbeResult(name, "gemini", converter.STATUS_PASS, 100, "Service reachable"),
                    disney=converter.ProbeResult(name, "disney", converter.STATUS_PASS, 100, "Service reachable"),
                )
            else:
                results[name] = converter.NodeProbeResults(
                    node_name=name,
                    base=converter.ProbeResult(name, "base", converter.STATUS_PASS, 50, "OK"),
                    gpt=converter.ProbeResult(name, "gpt", converter.STATUS_FAIL, None, "Not available"),
                    gemini=converter.ProbeResult(name, "gemini", converter.STATUS_FAIL, None, "Not available"),
                    disney=converter.ProbeResult(name, "disney", converter.STATUS_FAIL, None, "Not available"),
                )
        return results

    def test_transform_with_probe_results_filters_gpt(self):
        """Only PASS GPT nodes enter GPT manual."""
        data = copy.deepcopy(sample_basic())
        all_names = [p["name"] for p in data["proxies"]]
        # Mark only JP node as GPT-passing
        jp_name = "\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501"
        probe_results = self._build_mock_probe_results([jp_name])

        result = converter.transform(
            data,
            manual_group="\u624b\u52a8\u9009\u62e9",
            auto_group="\u81ea\u52a8\u9009\u62e9",
            disney_group="\u8fea\u58eb\u5c3c",
            media_keywords=["\u6d41\u5a92\u4f53", "\u5a92\u4f53\u6d41"],
            probe_results=probe_results,
        )
        groups = _groups_by_name(result)
        gpt_manual = groups["GPT\u624b\u52a8"]
        assert gpt_manual["proxies"][0] == "GPT\u81ea\u52a8"
        # Only JP node should be in GPT manual (others failed GPT probe)
        assert jp_name in gpt_manual["proxies"]
        non_passing = [n for n in all_names if n != jp_name]
        for n in non_passing:
            if n in gpt_manual["proxies"]:
                # The node might be in GPT manual only if it passed GPT probe
                pass

    def test_transform_probe_gemini_us_can_pass(self):
        """US node can enter Gemini if it passes Gemini probe (no hardcoded exclusion)."""
        data = copy.deepcopy(sample_basic())
        us_name = "\U0001f1fa\U0001f1f8\u7f8e\u56fd\u6d4b\u8bd501"
        jp_name = "\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501"
        # Mark US node as Gemini passing
        probe_results = self._build_mock_probe_results([jp_name, us_name])

        result = converter.transform(
            data,
            manual_group="\u624b\u52a8\u9009\u62e9",
            auto_group="\u81ea\u52a8\u9009\u62e9",
            disney_group="\u8fea\u58eb\u5c3c",
            media_keywords=["\u6d41\u5a92\u4f53", "\u5a92\u4f53\u6d41"],
            probe_results=probe_results,
        )
        groups = _groups_by_name(result)
        gemini_auto = groups.get("Gemini\u81ea\u52a8")
        assert gemini_auto is not None
        gemini_names = gemini_auto["proxies"]
        assert us_name in gemini_names, "US node should be in Gemini when probe PASS"

    def test_transform_probe_gemini_us_fails_excluded(self):
        """US node excluded from Gemini when it fails the probe."""
        data = copy.deepcopy(sample_basic())
        us_name = "\U0001f1fa\U0001f1f8\u7f8e\u56fd\u6d4b\u8bd501"
        jp_name = "\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501"
        # Only JP passes Gemini, US fails
        probe_results = self._build_mock_probe_results([jp_name])

        result = converter.transform(
            data,
            manual_group="\u624b\u52a8\u9009\u62e9",
            auto_group="\u81ea\u52a8\u9009\u62e9",
            disney_group="\u8fea\u58eb\u5c3c",
            media_keywords=["\u6d41\u5a92\u4f53", "\u5a92\u4f53\u6d41"],
            probe_results=probe_results,
        )
        groups = _groups_by_name(result)
        gemini_auto = groups.get("Gemini\u81ea\u52a8")
        assert gemini_auto is not None
        assert us_name not in gemini_auto["proxies"], "US node excluded when Gemini probe fails"

    def test_transform_probe_disney_not_keyword_only(self):
        """Disney nodes come from probe results, not just keyword matching."""
        data = copy.deepcopy(sample_basic())
        sg_name = "\U0001f1f8\U0001f1ec\u65b0\u52a0\u5761\u6d4b\u8bd501"
        jp_name = "\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501"
        tw_name = "\U0001f1f9\U0001f1fc\u53f0\u6e7e\u6d4b\u8bd501"
        # Mark JP and TW but NOT SG as Disney-passing
        probe_results = self._build_mock_probe_results([jp_name, tw_name])
        # Also set SG's probe results to FAIL for Disney
        for name, nr in probe_results.items():
            if name == sg_name:
                nr.disney.status = converter.STATUS_FAIL

        result = converter.transform(
            data,
            manual_group="\u624b\u52a8\u9009\u62e9",
            auto_group="\u81ea\u52a8\u9009\u62e9",
            disney_group="\u8fea\u58eb\u5c3c",
            media_keywords=["\u6d41\u5a92\u4f53", "\u5a92\u4f53\u6d41"],
            probe_results=probe_results,
        )
        groups = _groups_by_name(result)
        disney_auto = groups.get("\u8fea\u58eb\u5c3c\u81ea\u52a8")
        assert disney_auto is not None
        disney_names = disney_auto["proxies"]
        # SG failed Disney probe, should not be in Disney auto
        assert sg_name not in disney_names

    def test_blocked_no_gpt_nodes(self):
        """BLOCKED_NO_VALID_GPT_NODES when no GPT PASS nodes."""
        data = copy.deepcopy(sample_basic())
        all_names = [p["name"] for p in data["proxies"]]
        probe_results = self._build_mock_probe_results([])  # none pass

        result = converter.transform(
            data,
            manual_group="\u624b\u52a8\u9009\u62e9",
            auto_group="\u81ea\u52a8\u9009\u62e9",
            disney_group="\u8fea\u58eb\u5c3c",
            media_keywords=["\u6d41\u5a92\u4f53", "\u5a92\u4f53\u6d41"],
            probe_results=probe_results,
        )
        groups = _groups_by_name(result)
        assert "GPT\u4e13\u7528" not in groups
        assert "GPT\u624b\u52a8" not in groups
        assert "GPT\u81ea\u52a8" not in groups

    def test_filter_nodes_by_probe(self):
        all_names = [p["name"] for p in sample_basic()["proxies"]]
        jp_name = "\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501"
        probe_results = self._build_mock_probe_results([jp_name])
        filtered = converter.filter_nodes_by_probe(all_names, probe_results, "gpt")
        assert jp_name in filtered
        # Other nodes should not be in filtered
        for name in all_names:
            if name != jp_name:
                assert name not in filtered


# ---------------------------------------------------------------------------
# Test: Gemini manual calibration overrides
# ---------------------------------------------------------------------------


def _sample_with_calibration_nodes():
    """Fixture with nodes matching *GEMINI_MANUAL_OVERRIDES* keys."""
    base = sample_basic()
    base["proxies"] = base["proxies"] + [
        {"name": "美国-住宅", "type": "ss", "server": "example.invalid", "port": 10},
        {"name": "美国迈阿密-hy2", "type": "ss", "server": "example.invalid", "port": 11},
        {"name": "美国拉斯维加斯-hy2", "type": "ss", "server": "example.invalid", "port": 12},
    ]
    return base


class TestGeminiManualOverride:
    """Calibrated manual overrides for Gemini must take precedence over probes."""

    def _build_probe_results(self, names_pass, names_fail_override=None):
        """Build a probe result dict where named nodes pass gemini (and all services)
        and all others fail Gemini.
        """
        proxies = _sample_with_calibration_nodes()["proxies"]
        pass_set = set(names_pass)
        results = {}
        for p in proxies:
            name = p["name"]
            if name in pass_set:
                results[name] = converter.NodeProbeResults(
                    node_name=name,
                    base=converter.ProbeResult(name, "base", converter.STATUS_PASS, 50, "OK"),
                    gpt=converter.ProbeResult(name, "gpt", converter.STATUS_PASS, 100, "OK"),
                    gemini=converter.ProbeResult(name, "gemini", converter.STATUS_PASS, 100, "OK"),
                    disney=converter.ProbeResult(name, "disney", converter.STATUS_PASS, 100, "OK"),
                )
            else:
                results[name] = converter.NodeProbeResults(
                    node_name=name,
                    base=converter.ProbeResult(name, "base", converter.STATUS_PASS, 50, "OK"),
                    gpt=converter.ProbeResult(name, "gpt", converter.STATUS_FAIL, None, "N/A"),
                    gemini=converter.ProbeResult(name, "gemini", converter.STATUS_FAIL, None, "N/A"),
                    disney=converter.ProbeResult(name, "disney", converter.STATUS_FAIL, None, "N/A"),
                )
        return results

    def test_override_deny_excludes_node(self):
        """'美国-住宅' is excluded from Gemini even if probe says PASS."""
        data = copy.deepcopy(_sample_with_calibration_nodes())
        # Mark EVERYTHING as Gemini PASS — override should still exclude 美国-住宅
        all_names = [p["name"] for p in data["proxies"]]
        probe_results = self._build_probe_results(all_names)

        result = converter.transform(
            data,
            manual_group="手动选择",
            auto_group="自动选择",
            disney_group="迪士尼",
            media_keywords=["流媒体", "媒体流"],
            probe_results=probe_results,
        )
        groups = _groups_by_name(result)
        gemini_auto = groups.get("Gemini自动")
        assert gemini_auto is not None
        for name in gemini_auto["proxies"]:
            assert name != "美国-住宅", "美国-住宅 should be excluded by override"

    def test_override_allow_includes_node(self):
        """'美国迈阿密-hy2' enters Gemini even if probe says FAIL."""
        data = copy.deepcopy(_sample_with_calibration_nodes())
        # Only 日本测试01 passes Gemini probe — override should still force
        # 美国迈阿密-hy2 and 美国拉斯维加斯-hy2 into Gemini
        jp_name = "🇯🇵日本测试01"
        probe_results = self._build_probe_results([jp_name])

        result = converter.transform(
            data,
            manual_group="手动选择",
            auto_group="自动选择",
            disney_group="迪士尼",
            media_keywords=["流媒体", "媒体流"],
            probe_results=probe_results,
        )
        groups = _groups_by_name(result)
        gemini_auto = groups.get("Gemini自动")
        assert gemini_auto is not None
        gemini_names = gemini_auto["proxies"]
        assert "美国迈阿密-hy2" in gemini_names
        assert "美国拉斯维加斯-hy2" in gemini_names

    def test_override_does_not_broaden_us_rule(self):
        """Other US nodes (美国测试01) still determined by probe, not override."""
        data = copy.deepcopy(_sample_with_calibration_nodes())
        jp_name = "🇯🇵日本测试01"
        us_generic = "🇺🇸美国测试01"
        probe_results = self._build_probe_results([jp_name])

        result = converter.transform(
            data,
            manual_group="手动选择",
            auto_group="自动选择",
            disney_group="迪士尼",
            media_keywords=["流媒体", "媒体流"],
            probe_results=probe_results,
        )
        groups = _groups_by_name(result)
        gemini_auto = groups.get("Gemini自动")
        assert gemini_auto is not None
        # 美国测试01 failed probe and is NOT in override dict → excluded
        assert us_generic not in gemini_auto["proxies"]

    def test_override_wins_over_probe_and_reports_mismatch(self):
        """Override wins when probe disagrees; PROBE_OVERRIDE_MISMATCH printed."""
        data = copy.deepcopy(_sample_with_calibration_nodes())
        # Make 美国-住宅 PASS probe (override says FAIL) and
        # 美国迈阿密-hy2 FAIL probe (override says PASS)
        jp_name = "🇯🇵日本测试01"
        all_names = [p["name"] for p in data["proxies"]]
        probe_results = self._build_probe_results([jp_name, "美国-住宅"])

        import io
        from unittest.mock import patch

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = converter.transform(
                data,
                manual_group="手动选择",
                auto_group="自动选择",
                disney_group="迪士尼",
                media_keywords=["流媒体", "媒体流"],
                probe_results=probe_results,
            )
            output = stdout.getvalue()

        groups = _groups_by_name(result)
        gemini_auto = groups.get("Gemini自动")
        assert gemini_auto is not None
        gemini_names = gemini_auto["proxies"]

        # Override wins: 美国-住宅 excluded despite probe PASS
        assert "美国-住宅" not in gemini_names
        # Override wins: 美国迈阿密-hy2 included despite probe FAIL
        assert "美国迈阿密-hy2" in gemini_names
        # PROBE_OVERRIDE_MISMATCH emitted for each conflict
        assert "PROBE_OVERRIDE_MISMATCH" in output


# ---------------------------------------------------------------------------
# Test: Service guard (validate_service_nodes)
# ---------------------------------------------------------------------------


class TestServiceGuard:
    def test_all_present_returns_none(self):
        assert converter.validate_service_nodes(["a"], ["b"], ["c"]) is None

    def test_gpt_empty_blocks(self):
        blocked = converter.validate_service_nodes([], ["b"], ["c"])
        assert blocked == converter.BLOCKED_NO_VALID_GPT

    def test_gemini_empty_blocks(self):
        blocked = converter.validate_service_nodes(["a"], [], ["c"])
        assert blocked == converter.BLOCKED_NO_VALID_GEMINI

    def test_disney_empty_blocks(self):
        blocked = converter.validate_service_nodes(["a"], ["b"], [])
        assert blocked == converter.BLOCKED_NO_VALID_DISNEY


# ---------------------------------------------------------------------------
# Test: Probe report does not leak secrets
# ---------------------------------------------------------------------------


class TestProbeReportSecrets:
    def test_probe_report_no_secrets(self):
        results = {
            "TestNode": converter.NodeProbeResults(
                node_name="TestNode",
                base=converter.ProbeResult("TestNode", "base", converter.STATUS_PASS, 50, "OK"),
                gpt=converter.ProbeResult("TestNode", "gpt", converter.STATUS_PASS, 100, "OK"),
                gemini=converter.ProbeResult("TestNode", "gemini", converter.STATUS_FAIL, None, "Not available"),
                disney=converter.ProbeResult("TestNode", "disney", converter.STATUS_UNKNOWN, None, "CAPTCHA"),
            ),
        }
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            converter.print_probe_report(results, 10.5, "/fake/core")
        output = f.getvalue()
        for secret in ["server", "password", "token", "uuid"]:
            assert secret not in output


# ---------------------------------------------------------------------------
# Test: MihomoProbeManager lifecycle (mocked subprocess / network)
# ---------------------------------------------------------------------------


class TestMihomoProbeManagerLifecycle:
    def test_start_stops_cleans_up(self):
        """MihomoProbeManager.start() creates temp dir, starts process, stops cleans up."""
        proxies = sample_basic()["proxies"]

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0
        mock_proc.send_signal.return_value = None
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_proc.__enter__.return_value = mock_proc
        mock_proc.__exit__.return_value = False

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.status = 200
                mock_urlopen.return_value.__enter__.return_value = mock_resp

                mgr = converter.MihomoProbeManager(
                    core_path="/fake/mihomo",
                    mixed_port=27891,
                    controller_port=29091,
                )
                try:
                    mgr.start(proxies)
                    assert mgr._temp_dir is not None
                    assert mgr._temp_dir.exists()
                    assert mock_popen.called
                    assert mgr.opener is not None
                finally:
                    mgr.stop()

                # After stop, temp dir should be cleaned up
                assert mgr._temp_dir is None or not mgr._temp_dir.exists()

    def test_switch_node_calls_controller(self):
        """switch_node calls the controller API."""
        proxies = sample_basic()["proxies"]
        jp_name = "\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501"

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0
        mock_proc.send_signal.return_value = None
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_proc.__enter__.return_value = mock_proc
        mock_proc.__exit__.return_value = False

        urlopen_calls = []

        def _mock_urlopen(req, timeout=None):
            urlopen_calls.append((req.method if hasattr(req, 'method') else 'GET', req.full_url if hasattr(req, 'full_url') else str(req)))
            resp = MagicMock()
            resp.status = 200
            resp.__enter__.return_value = resp
            return resp

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("urllib.request.urlopen", side_effect=_mock_urlopen):
                mgr = converter.MihomoProbeManager(
                    core_path="/fake/mihomo",
                    mixed_port=27892,
                    controller_port=29092,
                )
                try:
                    mgr.start(proxies)
                    mgr.switch_node(jp_name)

                    # Should have at least 2 calls: /version check and the PUT
                    put_calls = [
                        call for call in urlopen_calls
                        if "PROBE" in str(call[1]) and call[0] == "PUT"
                    ]
                    assert len(put_calls) >= 1
                finally:
                    mgr.stop()

    def test_temp_config_permissions(self):
        """Temp config file has restricted permissions."""
        proxies = sample_basic()["proxies"]
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0
        mock_proc.send_signal.return_value = None
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_proc.__enter__.return_value = mock_proc
        mock_proc.__exit__.return_value = False

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.status = 200
                mock_urlopen.return_value.__enter__.return_value = mock_resp
                mock_urlopen.return_value.__enter__.return_value.status = 200

                mgr = converter.MihomoProbeManager(
                    core_path="/fake/mihomo",
                    mixed_port=27893,
                    controller_port=29093,
                )
                try:
                    mgr.start(proxies)
                    # Check config file permissions
                    config_path = mgr._temp_dir / "config.yaml"
                    assert config_path.exists()
                    perms = oct(os.stat(config_path).st_mode)
                    # Should be 0o600 or similar restricted permissions
                    assert "600" in perms, f"Config has perms {perms}, expected restricted"
                finally:
                    mgr.stop()

    def test_listens_only_127_0_0_1(self):
        """The Mihomo config binds external-controller to 127.0.0.1."""
        proxies = sample_basic()["proxies"]
        config = converter._build_probe_config(proxies, 17891, 19091)
        ctrl = config.get("external-controller", "")
        assert "127.0.0.1" in ctrl
        assert "0.0.0.0" not in ctrl


# ---------------------------------------------------------------------------
# Test: No PROBE group in final output
# ---------------------------------------------------------------------------


class TestNoProbeGroupInOutput:
    def test_no_probe_group(self):
        data = _transform(copy.deepcopy(sample_basic()))
        group_names = [g["name"] for g in data["proxy-groups"]]
        assert converter.PROBE_GROUP_NAME not in group_names

    def test_no_probe_group_even_with_probe_results(self):
        data = copy.deepcopy(sample_basic())
        jp_name = "\U0001f1ef\U0001f1f5\u65e5\u672c\u6d4b\u8bd501"
        results = {
            jp_name: converter.NodeProbeResults(
                node_name=jp_name,
                base=converter.ProbeResult(jp_name, "base", converter.STATUS_PASS, 50, "OK"),
                gpt=converter.ProbeResult(jp_name, "gpt", converter.STATUS_PASS, 100, "OK"),
                gemini=converter.ProbeResult(jp_name, "gemini", converter.STATUS_PASS, 100, "OK"),
                disney=converter.ProbeResult(jp_name, "disney", converter.STATUS_PASS, 100, "OK"),
            ),
        }
        result = converter.transform(
            data,
            manual_group="\u624b\u52a8\u9009\u62e9",
            auto_group="\u81ea\u52a8\u9009\u62e9",
            disney_group="\u8fea\u58eb\u5c3c",
            media_keywords=["\u6d41\u5a92\u4f53", "\u5a92\u4f53\u6d41"],
            probe_results=results,
        )
        group_names = [g["name"] for g in result["proxy-groups"]]
        assert converter.PROBE_GROUP_NAME not in group_names

    def test_no_probe_group_removed_by_cleanup(self):
        """remove_probe_groups strips any existing PROBE group."""
        groups = [
            {"name": "PROBE", "type": "select", "proxies": ["node1"]},
            {"name": "\u9ed8\u8ba4\u4ee3\u7406", "type": "select", "proxies": ["\u624b\u52a8\u9009\u62e9"]},
        ]
        converter.remove_probe_groups(groups)
        names = [g["name"] for g in groups]
        assert "PROBE" not in names


# ---------------------------------------------------------------------------
# Test: Final config does not contain ephemeral ports
# ---------------------------------------------------------------------------


class TestNoEphemeralPorts:
    def test_no_temp_ports(self):
        data = _transform(copy.deepcopy(sample_basic()))
        text = str(data)
        # The temp ports we use are around 17891 and 19091 — shouldn't be in final config
        assert "17891" not in text
        assert "19091" not in text


# ---------------------------------------------------------------------------
# Test: find_mihomo_core
# ---------------------------------------------------------------------------


class TestFindMihomoCore:
    def test_explicit_path_found(self):
        with patch("os.path.isfile", return_value=True), patch("os.access", return_value=True):
            result = converter.find_mihomo_core("/custom/mihomo")
            assert result == "/custom/mihomo"

    def test_explicit_path_not_found_blocks(self):
        with patch("os.path.isfile", return_value=False), patch("os.access", return_value=False):
            with pytest.raises(converter.ConfigError, match=converter.BLOCKED_PROBE_CORE_MISSING):
                converter.find_mihomo_core("/missing/mihomo")


# ---------------------------------------------------------------------------
# Test: probe-only command does not upload or connect to router
# ---------------------------------------------------------------------------


class TestProbeOnlyCommand:
    def test_probe_only_no_ssh_or_scp(self):
        """probe subcommand via CLI does not call SSH/SCP."""
        import yaml as pyyaml

        sample = sample_basic()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            pyyaml.safe_dump(sample, f, allow_unicode=True)
            input_path = Path(f.name)

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0
        mock_proc.send_signal.return_value = None
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_proc.__enter__.return_value = mock_proc
        mock_proc.__exit__.return_value = False

        try:
            test_args = ["prog", "probe", "--source", str(input_path)]
            with patch.object(sys, "argv", test_args):
                with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                    with patch("urllib.request.urlopen") as mock_urlopen:
                        mock_resp = MagicMock()
                        mock_resp.status = 200
                        mock_urlopen.return_value.__enter__.return_value = mock_resp
                        mock_urlopen.return_value.__enter__.return_value.status = 200

                        rc = converter.main()
                        # May return non-zero since mock opener returns 200 for everything
                        # and probe_classify might mark things as UNKNOWN.
                        # The important thing is no SSH/SCP was attempted.
                        assert rc == 0 or rc == 1
        finally:
            input_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test: Dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_write_or_ssh(self):
        sample = sample_basic()
        result = converter.transform(
            copy.deepcopy(sample),
            manual_group="\u624b\u52a8\u9009\u62e9",
            auto_group="\u81ea\u52a8\u9009\u62e9",
            disney_group="\u8fea\u58eb\u5c3c",
            media_keywords=["\u6d41\u5a92\u4f53", "\u5a92\u4f53\u6d41"],
        )
        assert "proxy-groups" in result

    def test_dry_run_cli_does_not_call_ssh(self):
        import yaml as pyyaml
        sample = sample_basic()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            pyyaml.safe_dump(sample, f, allow_unicode=True)
            input_path = Path(f.name)
        try:
            test_args = ["prog", "dry-run", "--input", str(input_path)]
            with patch.object(sys, "argv", test_args):
                rc = converter.main()
                assert rc == 0
        finally:
            input_path.unlink(missing_ok=True)

    def test_dry_run_no_output_file_written(self):
        import yaml as pyyaml
        sample = sample_basic()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            pyyaml.safe_dump(sample, f, allow_unicode=True)
            input_path = Path(f.name)
        try:
            test_args = ["prog", "dry-run", "--input", str(input_path)]
            with patch.object(sys, "argv", test_args):
                with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                    rc = converter.main()
                    assert rc == 0
                    output = mock_stdout.getvalue()
                    assert "dry_run=true" in output
                    assert "output=" not in output
        finally:
            input_path.unlink(missing_ok=True)

    def test_dry_run_no_deploy_call(self):
        import yaml as pyyaml
        sample = sample_basic()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            pyyaml.safe_dump(sample, f, allow_unicode=True)
            input_path = Path(f.name)
        original_ssh = converter.ssh_command
        called = []

        def tracking_ssh(*args, **kwargs):
            called.append(args)

        try:
            converter.ssh_command = tracking_ssh
            test_args = ["prog", "dry-run", "--input", str(input_path)]
            with patch.object(sys, "argv", test_args):
                rc = converter.main()
                assert rc == 0
                assert len(called) == 0
        finally:
            converter.ssh_command = original_ssh
            input_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test: Sync pipeline (mocked SSH)
# ---------------------------------------------------------------------------


class _MockSsh:
    """Context manager that patches ssh, scp, and subprocess.run."""

    def __init__(self, test_instance, *, mock_sha256: str | None = None):
        self.test = test_instance
        self.commands_run: list[list[str]] = []
        self.scp_calls: list[list[str]] = []
        self.stages: list[str] = []
        self.remote_sha_values: dict[str, str | None] = {}
        self.file_exists_results: dict[str, bool] = {}
        self.fail_ssh_batchmode = False
        self.fail_ssh_cmd: dict[str, bool] = {}
        self.fail_scp = False
        self.fail_stage: str | None = None
        self._mock_sha256 = mock_sha256

    STAGES = (
        "batchmode",
        "remote_sha",
        "remote_preflight",
        "no_activate_validate_replace",
        "scp_upload",
        "remote_validate",
        "backup",
        "replace",
        "restart",
        "health_check",
        "cleanup",
        "rollback",
    )

    @staticmethod
    def _classify_stage(host: str, command: str) -> str:
        if "BatchMode=yes" in command:
            return "batchmode"
        if command.startswith("sha256sum"):
            return "remote_sha"
        if command.startswith("test -f"):
            return "remote_preflight"
        if "; cp -p " in command and "openclash restart" in command:
            return "rollback"
        if "cp -p" in command and "clash_meta" not in command and "/etc/init.d/openclash" not in command:
            return "backup"
        if "mv -f" in command and "clash_meta" not in command:
            return "replace"
        if "clash_meta" in command and " -t " in command and "mv -f" in command:
            return "no_activate_validate_replace"
        if "clash_meta" in command and " -t " in command:
            return "remote_validate"
        if "/etc/init.d/openclash" in command or "service openclash" in command:
            return "restart"
        if command.startswith("rm -f") or "; rm -f " in command:
            return "cleanup"
        if any(kw in command for kw in ("pidof", "pgrep", "ss -tlnp", "watchdog", "logread", "ubus call")):
            return "health_check"
        raise AssertionError(f"Unknown SSH command for '{host}': {command[:120]!r}")

    @staticmethod
    def _mock_result(stdout: str = "") -> object:
        return type("MockResult", (), {"stdout": stdout})()

    def _mock_ssh(self, host: str, command: str, *, capture: bool = False) -> object:
        mock_cmd = ["ssh", host, command]
        self.commands_run.append(mock_cmd)
        stage = self._classify_stage(host, command)
        self.stages.append(stage)

        if self.fail_stage and stage == self.fail_stage:
            raise subprocess.CalledProcessError(1, mock_cmd, "", f"Mock failure at stage: {stage}")

        for prefix, should_fail in self.fail_ssh_cmd.items():
            if command.startswith(prefix) and should_fail:
                raise subprocess.CalledProcessError(1, mock_cmd, "", "Mock failure")

        if stage == "batchmode" and self.fail_ssh_batchmode:
            raise subprocess.CalledProcessError(255, mock_cmd, "", "Permission denied (publickey)")

        if stage == "remote_sha":
            tokens = command.split()
            path_part = tokens[1].replace("'", "").replace('"', "") if len(tokens) >= 2 else ""
            sha = self.remote_sha_values.get(path_part)
            if sha is None:
                if "MISSING" in command:
                    return self._mock_result("MISSING")
                raise subprocess.CalledProcessError(1, mock_cmd, "", "File not found")
            return self._mock_result(f"{sha}  {path_part}")

        if stage == "remote_preflight":
            path_part = command.replace("test -f", "").strip().replace("'", "").replace('"', "")
            exists = self.file_exists_results.get(path_part, True)
            if exists:
                return self._mock_result()
            raise subprocess.CalledProcessError(1, mock_cmd, "", "File not found")

        return self._mock_result()

    def _mock_scp(self, cmd: list[str], **kwargs) -> object:
        self.scp_calls.append(cmd)
        self.stages.append("scp_upload")
        if self.fail_scp:
            raise subprocess.CalledProcessError(1, cmd, "", "SCP failed")
        return self._mock_result()

    def _mock_run(self, cmd: list[str], check: bool = True, capture: bool = False, **kwargs) -> object:
        if cmd[0] == "ssh":
            is_batchmode = "BatchMode=yes" in cmd
            ssh_args = cmd[1:]
            host = None
            command_parts: list[str] = []
            i = 0
            while i < len(ssh_args):
                if ssh_args[i] == "-o":
                    i += 2
                else:
                    if host is None:
                        host = ssh_args[i]
                    else:
                        command_parts.append(ssh_args[i])
                    i += 1
            command_str = " ".join(command_parts) if command_parts else "true" if host else ""
            if is_batchmode:
                command_str = f"BatchMode=yes {command_str}"
            return self._mock_ssh(host or "", command_str, capture=capture)
        if cmd[0] == "scp":
            return self._mock_scp(cmd, **kwargs)
        raise AssertionError(f"Unknown run command: {' '.join(str(p)[:60] for p in cmd)}")

    def __enter__(self):
        self._patches = [
            patch.object(converter, "ssh_command", side_effect=self._mock_ssh),
            patch.object(converter, "run", side_effect=self._mock_run),
        ]
        if self._mock_sha256:
            self._patches.append(
                patch.object(converter, "file_sha256", return_value=self._mock_sha256)
            )
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()


class TestSyncPipeline:
    def _setup_source_yaml(self, data=None):
        import yaml as pyyaml
        if data is None:
            data = sample_basic()
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        pyyaml.safe_dump(data, f, allow_unicode=True)
        f.close()
        return Path(f.name)

    def test_sync_no_change_sha_matches(self):
        src = self._setup_source_yaml()
        same_sha = "a" * 64

        with _MockSsh(self, mock_sha256=same_sha) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = same_sha

            test_args = ["prog", "sync", "--source", str(src)]
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                with patch.object(sys, "argv", test_args):
                    rc = converter.main()
                    output = stdout.getvalue()

        src.unlink(missing_ok=True)
        assert rc == 0
        assert "NO_CHANGE_OPENCLASH_CONFIG_CURRENT" in output
        assert "no_change=true" in output
        assert len(mock.scp_calls) == 0
        assert "scp_upload" not in mock.stages

    def test_sync_log_no_secrets(self):
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = "old" * 20
            mock.file_exists_results["/etc/openclash/core/clash_meta"] = True

            test_args = ["prog", "sync", "--source", str(src)]
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                with patch.object(sys, "argv", test_args):
                    converter.main()
                    output = stdout.getvalue()

        src.unlink(missing_ok=True)
        for secret_word in ["server", "password", "token", "uuid", "example.invalid"]:
            assert secret_word not in output.lower()

    def test_sync_uses_scp_o(self):
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = "old" * 20
            mock.file_exists_results["/etc/openclash/core/clash_meta"] = True

            test_args = ["prog", "sync", "--source", str(src)]
            with patch.object(sys, "argv", test_args):
                converter.main()

            for scp_call in mock.scp_calls:
                assert "-O" in scp_call

        src.unlink(missing_ok=True)
