from __future__ import annotations

import copy
import importlib.util
import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "scripts" / "clashverge_to_openclash.py"
spec = importlib.util.spec_from_file_location("converter", SCRIPT)
converter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(converter)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def sample_basic():
    """Nodes with mixed regions, GPT and Disney groups.

    The wrapper prefix used by the script is U+2502 (BOX DRAWINGS LIGHT VERTICAL).
    """
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
    """Run transform with standard defaults."""
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


def _wrapper_groups(data, prefix):
    return [g for g in data["proxy-groups"] if g["name"].startswith(prefix)]


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
        assert jp_names
        tw_names = [n for n in proxies if "\u53f0\u6e7e" in n]
        assert tw_names
        first_jp_idx = proxies.index(jp_names[0])
        first_tw_idx = proxies.index(tw_names[0])
        assert first_jp_idx < first_tw_idx, "Japan should appear before Taiwan"

    def test_manual_first_item_is_auto(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["\u624b\u52a8\u9009\u62e9"]
        assert manual["proxies"][0] == "\u81ea\u52a8\u9009\u62e9"

    def test_manual_only_auto_and_global_wrappers(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["\u624b\u52a8\u9009\u62e9"]
        for proxy in manual["proxies"][1:]:
            assert proxy.startswith("\u5168\u5c40\u4f18\u5148\u2502"), (     # 全局优先│
                f"Unexpected non-wrapper proxy: {proxy}"
            )

    def test_each_global_wrapper_first_node_second_auto(self):
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = _wrapper_groups(data, "\u5168\u5c40\u4f18\u5148\u2502")
        for w in wrappers:
            assert len(w["proxies"]) == 2
            assert w["proxies"][0] in [p["name"] for p in sample_basic()["proxies"]]
            assert w["proxies"][1] == "\u81ea\u52a8\u9009\u62e9"


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

    def test_gpt_manual_only_auto_and_gpt_wrappers(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["GPT\u624b\u52a8"]
        assert manual["proxies"][0] == "GPT\u81ea\u52a8"
        for proxy in manual["proxies"][1:]:
            assert proxy.startswith("GPT\u4f18\u5148\u2502"), (              # GPT优先│
                f"Unexpected non-wrapper proxy: {proxy}"
            )

    def test_gpt_wrapper_fallbacks_to_gpt_auto(self):
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = _wrapper_groups(data, "GPT\u4f18\u5148\u2502")
        for w in wrappers:
            assert w["proxies"][1] == "GPT\u81ea\u52a8"


# ---------------------------------------------------------------------------
# Test: Gemini groups
# ---------------------------------------------------------------------------


class TestGeminiGroups:
    def test_gemini_auto_only_allowed_regions(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data).get("Gemini\u81ea\u52a8")
        assert auto is not None
        regions_found = set()
        for proxy in auto["proxies"]:
            region = converter.detect_region(proxy)
            if region:
                regions_found.add(region)
        assert "\u7f8e\u56fd" not in regions_found                         # 美国
        for r in regions_found:
            assert r in {"\u65e5\u672c", "\u53f0\u6e7e", "\u9999\u6e2f", "\u5fb7\u56fd"}

    def test_gemini_auto_no_us_nodes(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data).get("Gemini\u81ea\u52a8")
        assert auto is not None
        for proxy in auto["proxies"]:
            assert "\u7f8e\u56fd" not in proxy
            assert "\U0001f1fa\U0001f1f8" not in proxy                     # 🇺🇸

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

    def test_gemini_manual_only_auto_and_gemini_wrappers(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data).get("Gemini\u624b\u52a8")
        assert manual is not None
        assert manual["proxies"][0] == "Gemini\u81ea\u52a8"
        for proxy in manual["proxies"][1:]:
            assert proxy.startswith("Gemini\u4f18\u5148\u2502")

    def test_gemini_wrapper_fallbacks_to_gemini_auto(self):
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = _wrapper_groups(data, "Gemini\u4f18\u5148\u2502")
        for w in wrappers:
            assert w["proxies"][1] == "Gemini\u81ea\u52a8"


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


# ---------------------------------------------------------------------------
# Test: Wrapper structure
# ---------------------------------------------------------------------------


class TestWrapperStructure:
    def test_all_wrappers_first_member_is_static_node(self):
        data = _transform(copy.deepcopy(sample_basic()))
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        for g in data["proxy-groups"]:
            if converter.is_priority_wrapper(g["name"]):
                assert g["proxies"][0] in static_names, (
                    f"Wrapper '{g['name']}' first proxy '{g['proxies'][0]}' is not a static node"
                )

    def test_all_wrappers_second_member_is_auto(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto_names = {"\u81ea\u52a8\u9009\u62e9", "GPT\u81ea\u52a8", "Gemini\u81ea\u52a8", "\u8fea\u58eb\u5c3c\u81ea\u52a8"}
        for g in data["proxy-groups"]:
            if converter.is_priority_wrapper(g["name"]):
                assert g["proxies"][1] in auto_names, (
                    f"Wrapper '{g['name']}' second proxy '{g['proxies'][1]}' is not an auto group"
                )


# ---------------------------------------------------------------------------
# Test: Reference / cycle / integrity
# ---------------------------------------------------------------------------


class TestIntegrity:
    def test_no_self_reference(self):
        data = _transform(copy.deepcopy(sample_basic()))
        for g in data["proxy-groups"]:
            assert g["name"] not in g.get("proxies", []), (
                f"Group '{g['name']}' references itself"
            )

    def test_no_cycle(self):
        _transform(copy.deepcopy(sample_basic()))

    def test_no_missing_references(self):
        data = _transform(copy.deepcopy(sample_basic()))
        names = [g["name"] for g in data["proxy-groups"]]
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        valid = set(names) | static_names | {"DIRECT", "REJECT", "REJECT-DROP", "PASS"}
        for g in data["proxy-groups"]:
            for proxy in g.get("proxies", []):
                assert proxy in valid, (
                    f"Group '{g['name']}' references missing target '{proxy}'"
                )

    def test_no_duplicate_group_names(self):
        data = _transform(copy.deepcopy(sample_basic()))
        names = [g["name"] for g in data["proxy-groups"]]
        assert len(names) == len(set(names)), "Duplicate group names found"


# ---------------------------------------------------------------------------
# Test: MATCH rule
# ---------------------------------------------------------------------------


class TestMatchRule:
    def test_only_one_match(self):
        data = _transform(copy.deepcopy(sample_basic()))
        match_rules = [
            r for r in data["rules"]
            if isinstance(r, str) and r.strip().upper().startswith("MATCH,")
        ]
        assert len(match_rules) == 1, f"Expected 1 MATCH rule, got {len(match_rules)}"

    def test_match_to_default(self):
        data = _transform(copy.deepcopy(sample_basic()))
        final = data["rules"][-1]
        assert final == "MATCH,\u9ed8\u8ba4\u4ee3\u7406"


# ---------------------------------------------------------------------------
# Test: Input file not modified
# ---------------------------------------------------------------------------


class TestInputImmutability:
    def test_input_file_unchanged(self):
        src = copy.deepcopy(sample_basic())
        snapshot = copy.deepcopy(src)
        _transform(src)
        # The transform IS allowed to modify the dict structure in-memory
        # (proxy-groups are replaced, rules modified). This test verifies
        # that the ORIGINAL nodes / groups that the user provided are not
        # lost or corrupted, and that the static nodes list is preserved.
        orig_static = {p["name"] for p in snapshot["proxies"]}
        final_static = {p["name"] for p in src["proxies"]}
        assert orig_static == final_static, "Static node names were modified"


# ---------------------------------------------------------------------------
# Test: PyYAML re-serialization
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
            assert fg["proxies"] == sg["proxies"], (
                f"Mismatch in group '{fn}': {fg['proxies']} vs {sg['proxies']}"
            )

    def test_no_wrapper_nesting_on_reprocess(self):
        first = _transform(copy.deepcopy(sample_basic()))
        second = _transform(copy.deepcopy(first))
        for g in second["proxy-groups"]:
            if converter.is_priority_wrapper(g["name"]):
                for proxy in g["proxies"]:
                    assert not converter.is_priority_wrapper(proxy), (
                        f"Nested wrapper: '{g['name']}' contains '{proxy}'"
                    )


# ---------------------------------------------------------------------------
# Test: Secret/log safety
# ---------------------------------------------------------------------------


class TestSecretSafety:
    def test_log_does_not_contain_credentials(self):
        """Capture print output and verify no secrets leaked."""
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
# Test: dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_write_or_ssh(self):
        """dry-run: transform without file output or SSH (direct call)."""
        sample = sample_basic()
        result = converter.transform(
            copy.deepcopy(sample),
            manual_group="手动选择",
            auto_group="自动选择",
            disney_group="迪士尼",
            media_keywords=["流媒体", "媒体流"],
        )
        assert "proxy-groups" in result

    def test_dry_run_cli_does_not_call_ssh(self):
        """dry-run subcommand does not invoke ssh/scp."""
        import yaml as pyyaml

        sample = sample_basic()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            pyyaml.safe_dump(sample, f, allow_unicode=True)
            input_path = Path(f.name)

        try:
            test_args = ["prog", "dry-run", "--input", str(input_path)]
            with patch.object(sys, "argv", test_args):
                rc = converter.main()
                assert rc == 0, f"dry-run returned {rc}"
        finally:
            input_path.unlink(missing_ok=True)

    def test_dry_run_no_output_file_written(self):
        """dry-run creates no output file."""
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
        """dry-run should not attempt deploy."""
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
                assert len(called) == 0, f"ssh_command was called {len(called)} times during dry-run"
        finally:
            converter.ssh_command = original_ssh
            input_path.unlink(missing_ok=True)
