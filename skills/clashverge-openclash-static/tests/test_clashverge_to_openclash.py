from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "clashverge_to_openclash.py"
spec = importlib.util.spec_from_file_location("converter", SCRIPT)
converter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(converter)


def sample():
    return {
        "proxies": [
            {"name": "普通节点", "type": "ss", "server": "example.invalid", "port": 1},
            {"name": "日本-流媒体01", "type": "ss", "server": "example.invalid", "port": 2},
            {"name": "新加坡-媒体流01", "type": "ss", "server": "example.invalid", "port": 3},
        ],
        "proxy-groups": [
            {"name": "GPT专用", "type": "select", "proxies": ["普通节点"]},
            {"name": "Gemini专用", "type": "select", "proxies": ["普通节点"]},
            {"name": "迪士尼", "type": "select", "proxies": ["普通节点"]},
        ],
        "rules": ["DOMAIN-SUFFIX,openai.com,GPT专用", "MATCH,DIRECT"],
    }


def test_transform_contract():
    data = converter.transform(
        sample(),
        manual_group="手动选择",
        auto_group="自动选择",
        disney_group="迪士尼",
        media_keywords=["流媒体", "媒体流"],
        test_url="https://www.gstatic.com/generate_204",
        interval=300,
        tolerance=50,
    )
    groups = {g["name"]: g for g in data["proxy-groups"]}
    assert data["proxy-groups"][0]["name"] == "手动选择"
    assert data["proxy-groups"][1]["name"] == "自动选择"
    assert groups["手动选择"]["proxies"] == [
        "自动选择",
        "普通节点",
        "日本-流媒体01",
        "新加坡-媒体流01",
    ]
    assert groups["自动选择"]["type"] == "url-test"
    assert "日本-流媒体01" in groups["迪士尼"]["proxies"]
    assert "新加坡-媒体流01" in groups["迪士尼"]["proxies"]
    assert data["rules"][-1] == "MATCH,手动选择"
    assert sum(1 for r in data["rules"] if isinstance(r, str) and r.startswith("MATCH,")) == 1


def test_idempotent():
    first = converter.transform(
        sample(),
        manual_group="手动选择",
        auto_group="自动选择",
        disney_group="迪士尼",
        media_keywords=["流媒体", "媒体流"],
        test_url="https://www.gstatic.com/generate_204",
        interval=300,
        tolerance=50,
    )
    second = converter.transform(
        first,
        manual_group="手动选择",
        auto_group="自动选择",
        disney_group="迪士尼",
        media_keywords=["流媒体", "媒体流"],
        test_url="https://www.gstatic.com/generate_204",
        interval=300,
        tolerance=50,
    )
    names = [g["name"] for g in second["proxy-groups"]]
    assert names.count("手动选择") == 1
    assert names.count("自动选择") == 1
    disney = next(g for g in second["proxy-groups"] if g["name"] == "迪士尼")
    assert disney["proxies"].count("日本-流媒体01") == 1
