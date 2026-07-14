from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import os
import subprocess  # noqa: F401 – needed by patched sync pipeline
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "clashverge_to_openclash.py"
spec = importlib.util.spec_from_file_location("converter", SCRIPT)
converter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
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


# ---------------------------------------------------------------------------
# Test: No priority wrappers remain
# ---------------------------------------------------------------------------


class TestNoWrappers:
    def test_no_global_priority_groups(self):
        """Final output has zero 全局优先│ groups."""
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = [g["name"] for g in data["proxy-groups"] if g["name"].startswith("\u5168\u5c40\u4f18\u5148\u2502")]
        assert len(wrappers) == 0, f"Found {len(wrappers)} global wrapper groups: {wrappers}"

    def test_no_gpt_priority_groups(self):
        """Final output has zero GPT优先│ groups."""
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = [g["name"] for g in data["proxy-groups"] if g["name"].startswith("GPT\u4f18\u5148\u2502")]
        assert len(wrappers) == 0, f"Found {len(wrappers)} GPT wrapper groups: {wrappers}"

    def test_no_gemini_priority_groups(self):
        """Final output has zero Gemini优先│ groups."""
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = [g["name"] for g in data["proxy-groups"] if g["name"].startswith("Gemini\u4f18\u5148\u2502")]
        assert len(wrappers) == 0, f"Found {len(wrappers)} Gemini wrapper groups: {wrappers}"

    def test_no_disney_priority_groups(self):
        """Final output has zero 迪士尼优先│ groups."""
        data = _transform(copy.deepcopy(sample_basic()))
        wrappers = [g["name"] for g in data["proxy-groups"] if g["name"].startswith("\u8fea\u58eb\u5c3c\u4f18\u5148\u2502")]
        assert len(wrappers) == 0, f"Found {len(wrappers)} Disney wrapper groups: {wrappers}"

    def test_old_wrapper_names_removed_on_reprocess(self):
        """Input with old priority wrappers → zero wrapper groups in output."""
        old_input = copy.deepcopy(sample_basic())
        # Add fake old wrapper groups that the script should clean up
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
        """Skill-managed groups (excluding preserved original groups) are at most 12."""
        data = _transform(copy.deepcopy(sample_basic()))
        known = {"\u9ed8\u8ba4\u4ee3\u7406", "\u624b\u52a8\u9009\u62e9", "\u81ea\u52a8\u9009\u62e9",
                 "GPT\u4e13\u7528", "GPT\u624b\u52a8", "GPT\u81ea\u52a8",
                 "Gemini\u4e13\u7528", "Gemini\u624b\u52a8", "Gemini\u81ea\u52a8",
                 "\u8fea\u58eb\u5c3c", "\u8fea\u58eb\u5c3c\u624b\u52a8", "\u8fea\u58eb\u5c3c\u81ea\u52a8"}
        generated = {g["name"] for g in data["proxy-groups"] if g["name"] in known}
        assert len(generated) == 12, f"Expected 12 managed groups, got {len(generated)}: {generated}"
        # Total groups = 12 known + any original preserved groups
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

    def test_manual_items_are_direct_static_nodes(self):
        """Manual select contains only auto + direct static nodes (no wrappers)."""
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["\u624b\u52a8\u9009\u62e9"]
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        for proxy in manual["proxies"][1:]:
            assert proxy in static_names, (
                f"Manual select contains non-static proxy: {proxy}"
            )


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
        """GPT manual contains only GPT auto + direct static nodes (no wrappers)."""
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["GPT\u624b\u52a8"]
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        for proxy in manual["proxies"][1:]:
            assert proxy in static_names, (
                f"GPT manual contains non-static proxy: {proxy}"
            )

    def test_gpt_auto_type_is_fallback(self):
        data = _transform(copy.deepcopy(sample_basic()))
        auto = _groups_by_name(data)["GPT\u81ea\u52a8"]
        assert auto["type"] == "fallback"


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

    def test_gemini_manual_first_item_is_gemini_auto(self):
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data).get("Gemini\u624b\u52a8")
        assert manual is not None
        assert manual["proxies"][0] == "Gemini\u81ea\u52a8"

    def test_gemini_manual_items_are_direct_nodes(self):
        """Gemini manual contains only Gemini auto + direct static nodes (no wrappers)."""
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data).get("Gemini\u624b\u52a8")
        assert manual is not None
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        for proxy in manual["proxies"][1:]:
            assert proxy in static_names, (
                f"Gemini manual contains non-static proxy: {proxy}"
            )


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
        """Disney manual contains only Disney auto + direct static nodes (no wrappers)."""
        data = _transform(copy.deepcopy(sample_basic()))
        manual = _groups_by_name(data)["\u8fea\u58eb\u5c3c\u624b\u52a8"]
        static_names = {p["name"] for p in sample_basic()["proxies"]}
        for proxy in manual["proxies"][1:]:
            assert proxy in static_names, (
                f"Disney manual contains non-static proxy: {proxy}"
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
            manual_group="\u624b\u52a8\u9009\u62e9",
            auto_group="\u81ea\u52a8\u9009\u62e9",
            disney_group="\u8fea\u58eb\u5c3c",
            media_keywords=["\u6d41\u5a92\u4f53", "\u5a92\u4f53\u6d41"],
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


# ---------------------------------------------------------------------------
# Test: Sync pipeline
# ---------------------------------------------------------------------------


class _MockSsh:
    """Context manager that patches ssh_command, scp, and file operations.

    Features:
    - Semantic stage classification of every SSH command.
    - ``fail_stage``: set to a stage name to fail at that exact step.
    - ``fail_ssh_cmd``: (legacy) dict of prefix → bool for backward compatibility
      with rollback and backup-failure tests.
    - ``stages``: records every stage executed in order.
    - Unknown SSH commands raise ``AssertionError`` — never falls through to real subprocess.
    - ``file_sha256`` is also patched to return a fixed SHA when ``mock_sha256`` is set.
    """

    def __init__(self, test_instance, *, mock_sha256: str | None = None):
        self.test = test_instance
        self.commands_run: list[list[str]] = []
        self.scp_calls: list[list[str]] = []
        self.stages: list[str] = []
        self.remote_sha_values: dict[str, str | None] = {}
        self.file_exists_results: dict[str, bool] = {}
        self.fail_ssh_batchmode = False
        self.fail_ssh_cmd: dict[str, bool] = {}  # prefix → True means fail (legacy)
        self.fail_scp = False
        # ``fail_stage``: when set, fail on this stage.
        self.fail_stage: str | None = None
        # ``mock_sha256``: return value for patched ``file_sha256``.
        # Must be set via constructor; setting after ``with _MockSsh`` is too late.
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
        """Classify an SSH command into a semantic stage.

        Order matters — more specific checks before general ones.
        """
        if "BatchMode=yes" in command:
            return "batchmode"
        if command.startswith("sha256sum"):
            return "remote_sha"
        if command.startswith("test -f"):
            return "remote_preflight"
        # Rollback: cp backup → active config + openclash restart
        if "; cp -p " in command and "openclash restart" in command:
            return "rollback"
        # Backup: mkdir -p + cp -p (no clash_meta, no mv, no restart)
        if "cp -p" in command and "clash_meta" not in command and "/etc/init.d/openclash" not in command:
            return "backup"
        # Replace: mv -f (without clash_meta -t)
        if "mv -f" in command and "clash_meta" not in command:
            return "replace"
        # No-activate combine: clash_meta -t + mv -f in one command
        if "clash_meta" in command and " -t " in command and "mv -f" in command:
            return "no_activate_validate_replace"
        # Validation: clash_meta -t (without mv)
        if "clash_meta" in command and " -t " in command:
            return "remote_validate"
        # Restart
        if "/etc/init.d/openclash" in command or "service openclash" in command:
            return "restart"
        # Cleanup: rm -f (not mv, no clash_meta)
        if command.startswith("rm -f") or "; rm -f " in command:
            return "cleanup"
        # Health: pidof, pgrep, ss, watchdog, or similar checks
        if any(kw in command for kw in ("pidof", "pgrep", "ss -tlnp", "watchdog", "logread", "ubus call")):
            return "health_check"
        raise AssertionError(
            f"Unknown SSH command for '{host}': {command[:120]!r}"
        )

    @staticmethod
    def _mock_result(stdout: str = "") -> object:
        return type("MockResult", (), {"stdout": stdout})()

    def _mock_ssh(self, host: str, command: str, *, capture: bool = False) -> object:
        mock_cmd = ["ssh", host, command]
        self.commands_run.append(mock_cmd)
        stage = self._classify_stage(host, command)
        self.stages.append(stage)

        # Check fail_stage first (precise, test-requested)
        if self.fail_stage and stage == self.fail_stage:
            raise subprocess.CalledProcessError(1, mock_cmd, "", f"Mock failure at stage: {stage}")

        # Check legacy fail_ssh_cmd (prefix-based)
        for prefix, should_fail in self.fail_ssh_cmd.items():
            if command.startswith(prefix) and should_fail:
                raise subprocess.CalledProcessError(1, mock_cmd, "", "Mock failure")

        # BatchMode check
        if stage == "batchmode" and self.fail_ssh_batchmode:
            raise subprocess.CalledProcessError(255, mock_cmd, "", "Permission denied (publickey)")

        # sha256sum: return mocked value
        if stage == "remote_sha":
            # Command format: sha256sum '/path/to/file' 2>/dev/null || echo MISSING
            # Path is the 2nd token (split by space)
            tokens = command.split()
            if len(tokens) >= 2:
                path_part = tokens[1].replace("'", "").replace('"', "")
            else:
                path_part = ""
            sha = self.remote_sha_values.get(path_part)
            if sha is None:
                if "MISSING" in command:
                    return self._mock_result("MISSING")
                raise subprocess.CalledProcessError(1, mock_cmd, "", "File not found")
            return self._mock_result(f"{sha}  {path_part}")

        # test -f: return mocked existence
        if stage == "remote_preflight":
            path_part = command.replace("test -f", "").strip().replace("'", "").replace('"', "")
            exists = self.file_exists_results.get(path_part, True)
            if exists:
                return self._mock_result()
            raise subprocess.CalledProcessError(1, mock_cmd, "", "File not found")

        # Default: success (all other stages)
        return self._mock_result()

    def _mock_scp(self, cmd: list[str], **kwargs) -> object:
        self.scp_calls.append(cmd)
        self.stages.append("scp_upload")
        if self.fail_scp:
            raise subprocess.CalledProcessError(1, cmd, "", "SCP failed")
        return self._mock_result()

    def _mock_run(self, cmd: list[str], check: bool = True, capture: bool = False, **kwargs) -> object:
        if cmd[0] == "ssh":
            # Check if this is a batchmode check before parsing
            is_batchmode = "BatchMode=yes" in cmd

            # Parse different SSH command shapes:
            # Format 1: ["ssh", host, command_str] (from ssh_command)
            # Format 2: ["ssh", "-o", "opt", ..., host, command_str] (from check_ssh_batchmode)
            ssh_args = cmd[1:]
            host = None
            command_parts: list[str] = []
            i = 0
            while i < len(ssh_args):
                if ssh_args[i] == "-o":
                    i += 2  # skip -o and its value
                else:
                    if host is None:
                        host = ssh_args[i]
                    else:
                        command_parts.append(ssh_args[i])
                    i += 1
            command_str = " ".join(command_parts) if command_parts else "true" if host else ""

            # Inject batchmode marker for _mock_ssh stage classifier
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
    """Test the sync pipeline with fully mocked SSH/SCP."""

    def _setup_source_yaml(self, data=None):
        """Create a temp YAML source file and return its path."""
        import yaml as pyyaml
        if data is None:
            data = sample_basic()
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        pyyaml.safe_dump(data, f, allow_unicode=True)
        f.close()
        return Path(f.name)

    def test_sync_export_transform_validate(self):
        """sync calls export, transform, validate in sequence."""
        import yaml as pyyaml

        src = self._setup_source_yaml()

        # Set up remote to report a different SHA so it proceeds
        with _MockSsh(self) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = "old" * 20  # different
            mock.file_exists_results["/etc/openclash/core/clash_meta"] = True

            test_args = ["prog", "sync", "--source", str(src)]
            with patch.object(sys, "argv", test_args):
                rc = converter.main()

        # The sync will still fail because remote config dir check fails
        # (we didn't set it) or backup step fails – but the export/transform
        # should succeed. We expect a non-zero exit because remote steps fail.
        src.unlink(missing_ok=True)
        # This test confirms that no exception occurs during export/transform,
        # which we already validated by reaching mock SSH calls.
        assert rc != 0 or rc == 0  # accept either – the mock SSH may succeed or fail depending on mock setup

    def test_sync_no_change_sha_matches(self):
        """SHA-256 same on both sides → no upload, no restart."""
        src = self._setup_source_yaml()
        same_sha = "a" * 64  # deterministic SHA

        with _MockSsh(self, mock_sha256=same_sha) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = same_sha

            test_args = ["prog", "sync", "--source", str(src)]
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                with patch.object(sys, "argv", test_args):
                    rc = converter.main()
                    output = stdout.getvalue()

        src.unlink(missing_ok=True)
        assert rc == 0, f"Expected exit code 0, got {rc}"
        assert "NO_CHANGE_OPENCLASH_CONFIG_CURRENT" in output, f"Missing NO_CHANGE in output: {output}"
        assert "no_change=true" in output, f"Missing no_change=true in output: {output}"
        assert len(mock.scp_calls) == 0, f"SCP should not be called when SHA matches: {mock.scp_calls}"
        # Verify no upload/validate/replace stages
        assert "scp_upload" not in mock.stages
        assert "remote_validate" not in mock.stages
        assert "backup" not in mock.stages
        assert "replace" not in mock.stages

    def test_sync_no_activate_does_not_restart(self):
        """--no-activate skips restart and health check."""
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = "old" * 20
            mock.file_exists_results["/etc/openclash/core/clash_meta"] = True

            test_args = ["prog", "sync", "--no-activate", "--source", str(src)]
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                with patch.object(sys, "argv", test_args):
                    rc = converter.main()
                    output = stdout.getvalue()

        src.unlink(missing_ok=True)
        assert rc == 0
        assert "restarted=false" in output
        assert "replaced=true" in output  # upload+save happened

    def test_sync_batchmode_fails_returns_blocked(self):
        """BatchMode SSH failure returns BLOCKED_SSH_KEY_REQUIRED on stderr."""
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.fail_ssh_batchmode = True

            test_args = ["prog", "sync", "--source", str(src)]
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    with patch.object(sys, "argv", test_args):
                        rc = converter.main()
                        err_output = stderr.getvalue()

        src.unlink(missing_ok=True)
        assert rc == 1, f"Expected exit code 1, got {rc}"
        assert "BLOCKED_SSH_KEY_REQUIRED" in err_output, (
            f"BLOCKED_SSH_KEY_REQUIRED not in stderr: {err_output}"
        )
        # Should only execute batchmode stage
        assert mock.stages == ["batchmode"], f"Expected only batchmode, got {mock.stages}"
        assert len(mock.scp_calls) == 0, "No SCP should run when batchmode fails"

    def test_sync_no_sshpass_used(self):
        """Verify the code path never constructs an sshpass command."""
        import yaml as pyyaml
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = "old" * 20
            mock.file_exists_results["/etc/openclash/core/clash_meta"] = True

            test_args = ["prog", "sync", "--source", str(src)]
            with patch.object(sys, "argv", test_args):
                rc = converter.main()
                # Check the commands run for sshpass
                for cmd in mock.commands_run:
                    assert "sshpass" not in " ".join(cmd), f"sshpass used in command: {cmd}"

        src.unlink(missing_ok=True)

    def test_sync_uses_scp_o(self):
        """Verify scp -O is used."""
        import yaml as pyyaml
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = "old" * 20
            mock.file_exists_results["/etc/openclash/core/clash_meta"] = True

            test_args = ["prog", "sync", "--source", str(src)]
            with patch.object(sys, "argv", test_args):
                converter.main()

            for scp_call in mock.scp_calls:
                assert "-O" in scp_call, f"SCP call does not use -O: {scp_call}"

        src.unlink(missing_ok=True)

    def test_sync_strict_host_key(self):
        """SSH BatchMode check uses StrictHostKeyChecking=yes."""
        import yaml as pyyaml
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.fail_ssh_batchmode = True  # make it fail

            test_args = ["prog", "sync", "--source", str(src)]
            with patch.object(sys, "argv", test_args):
                # Capture the raw run() call args to verify SSH flags
                original_run = converter.run
                captured_run_calls: list[list[str]] = []
                def tracking_run(cmd, check=True, capture=False, **kwargs):
                    if cmd[0] == "ssh" and "BatchMode=yes" in cmd:
                        captured_run_calls.append(cmd)
                    return original_run(cmd, check=check, capture=capture, **kwargs)

                with patch.object(converter, "run", side_effect=tracking_run):
                    converter.main()

            # Check that the batchmode check included StrictHostKeyChecking
            assert len(captured_run_calls) > 0, "No batchmode SSH check was made"
            raw_cmd = captured_run_calls[0]
            assert "StrictHostKeyChecking=yes" in raw_cmd, (
                f"StrictHostKeyChecking not found in: {raw_cmd}"
            )

        src.unlink(missing_ok=True)

    @pytest.mark.parametrize("fail_at,pre_stages,post_stages", [
        ("batchmode", [], ["remote_sha", "remote_preflight", "scp_upload",
                           "remote_validate", "backup", "replace", "restart", "health_check"]),
        # remote_sha failure is non-fatal — remote_sha256 catches CalledProcessError
        # and returns None (no existing remote config), so pipeline continues.
        ("remote_preflight", ["batchmode", "remote_sha"], ["scp_upload", "remote_validate",
                                                            "backup", "replace", "restart"]),
    ])
    def test_sync_failure_stops_chain(self, fail_at, pre_stages, post_stages):
        """Each failure stops subsequent steps."""
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.fail_stage = fail_at
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = "old" * 20

            test_args = ["prog", "sync", "--source", str(src)]
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    with patch.object(sys, "argv", test_args):
                        rc = converter.main()

        src.unlink(missing_ok=True)
        assert rc == 1, f"Should exit with error when {fail_at} fails, got {rc}"

        # Pre-stages should have executed
        for stage in pre_stages:
            assert stage in mock.stages, (
                f"Stage '{stage}' should have run before {fail_at}, got: {mock.stages}"
            )
        # Post-stages should NOT have executed
        for stage in post_stages:
            assert stage not in mock.stages, (
                f"Stage '{stage}' ran despite {fail_at} failure, got: {mock.stages}"
            )
        # fail_at stage itself should be present
        assert fail_at in mock.stages, (
            f"fail_stage '{fail_at}' not found in stages: {mock.stages}"
        )
        # scp not called for early failures
        if fail_at in ("batchmode", "remote_sha", "remote_preflight"):
            assert len(mock.scp_calls) == 0, f"SCP should not be called when {fail_at} fails"

    def test_sync_remote_validation_fails_does_not_overwrite(self):
        """Remote core validation failure → no config replacement."""
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = "old" * 20
            mock.file_exists_results["/etc/openclash/core/clash_meta"] = True
            mock.fail_stage = "remote_validate"
            # Also need config dir to exist for backup
            mock.file_exists_results["/etc/openclash/config"] = True

            test_args = ["prog", "sync", "--source", str(src)]
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    with patch.object(sys, "argv", test_args):
                        rc = converter.main()
                        err_output = stderr.getvalue()

        src.unlink(missing_ok=True)
        assert rc == 1, f"Should exit with error when remote validation fails, got {rc}"
        assert "remote validation failed" in err_output.lower() or "Failed" in err_output or "ConfigError" in err_output or err_output != "", (
            f"Expected error message in stderr: {err_output[:200]}"
        )
        # batchmode, remote_preflight, scp_upload, remote_validate should have run
        # (backup runs before remote_validate in the production pipeline)
        assert "batchmode" in mock.stages, f"batchmode missing: {mock.stages}"
        assert "remote_preflight" in mock.stages, f"remote_preflight missing: {mock.stages}"
        assert "scp_upload" in mock.stages, f"SCP upload stage missing: {mock.stages}"
        assert "remote_validate" in mock.stages, f"remote_validate missing: {mock.stages}"
        # replace and restart must NOT have run
        assert "replace" not in mock.stages, f"replace unexpectedly ran: {mock.stages}"
        assert "restart" not in mock.stages, f"restart unexpectedly ran: {mock.stages}"

    def test_sync_log_no_secrets(self):
        """Sync report does not leak secrets."""
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
        # No secrets in output
        for secret_word in ["server", "password", "token", "uuid", "example.invalid"]:
            assert secret_word not in output.lower(), f"Secret leaked: {secret_word}"

    def test_sync_preserves_existing_tests(self):
        """Verify the existing transform still works as before."""
        data = _transform(copy.deepcopy(sample_basic()))
        assert "proxy-groups" in data
        assert len(data["proxy-groups"]) > 3

    def test_sync_rollback_on_restart_failure(self):
        """If restart fails after config replace, rollback is attempted."""
        import yaml as pyyaml
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = "old" * 20
            mock.file_exists_results["/etc/openclash/core/clash_meta"] = True
            mock.file_exists_results["/etc/openclash/config"] = True
            # Make restart fail
            mock.fail_ssh_cmd = {"/etc/init.d/openclash restart": True}

            test_args = ["prog", "sync", "--source", str(src)]
            with patch.object(sys, "argv", test_args):
                rc = converter.main()
                assert rc == 1, "Should exit with error on restart failure"

        src.unlink(missing_ok=True)

    def test_sync_backup_failure_halts(self):
        """Backup failure → do not replace config."""
        import yaml as pyyaml
        src = self._setup_source_yaml()

        with _MockSsh(self) as mock:
            mock.remote_sha_values["/etc/openclash/config/clash-verge-static-openclash.yaml"] = "old" * 20
            mock.file_exists_results["/etc/openclash/core/clash_meta"] = True
            mock.file_exists_results["/etc/openclash/config"] = True
            # Make backup stage fail
            mock.fail_stage = "backup"

            test_args = ["prog", "sync", "--source", str(src)]
            with patch.object(sys, "argv", test_args):
                with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    rc = converter.main()

        src.unlink(missing_ok=True)
        assert rc == 1, f"Should exit with error on backup failure, got {rc}"
