from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_cli.tools_config import _get_platform_tools
from model_tools import _clear_tool_defs_cache, get_tool_definitions
from tools.registry import discover_builtin_tools, registry
from toolsets import TOOLSETS, get_toolset, resolve_multiple_toolsets, resolve_toolset, validate_toolset


@pytest.fixture(autouse=True)
def clear_definition_cache():
    _clear_tool_defs_cache()
    yield
    _clear_tool_defs_cache()


def names(definitions):
    return [item["function"]["name"] for item in definitions]


def platform_configured(toolsets):
    return {
        "platform_toolsets": {"cli": list(toolsets)},
        "agent": {"disabled_toolsets": []},
        "mcp_servers": {},
    }


def test_hermes_cli_still_resolves():
    assert validate_toolset("hermes-cli") is True
    assert "terminal" in resolve_toolset("hermes-cli")


def test_book_notes_is_declared_builtin_read_only_toolset():
    definition = TOOLSETS["book-notes"]
    assert definition["built_in"] is True
    assert definition["read_only"] is True
    assert definition["tools"] == ["agy_book_dialogue", "book_notes_retrieval"]
    assert definition["includes"] == []


def test_book_notes_resolves_exactly_two_tools():
    assert validate_toolset("book-notes") is True
    assert resolve_toolset("book-notes") == ["agy_book_dialogue", "book_notes_retrieval"]
    assert resolve_toolset("book-notes", include_registry=False) == ["agy_book_dialogue", "book_notes_retrieval"]


def test_combined_toolsets_are_stable_deduplicated_union():
    combined = resolve_multiple_toolsets(["hermes-cli", "book-notes", "book-notes"])
    assert combined == sorted(set(combined))
    assert combined.count("book_notes_retrieval") == 1
    assert combined.count("agy_book_dialogue") == 1
    assert "terminal" in combined


def test_only_book_notes_does_not_expose_hermes_cli_tools():
    discover_builtin_tools()
    definitions = get_tool_definitions(["book-notes"], quiet_mode=True, skip_tool_search_assembly=True)
    assert names(definitions) == ["agy_book_dialogue", "book_notes_retrieval"]


def test_hermes_cli_only_does_not_expose_book_notes():
    discover_builtin_tools()
    definitions = get_tool_definitions(["hermes-cli"], quiet_mode=True, skip_tool_search_assembly=True)
    assert "book_notes_retrieval" not in names(definitions)
    assert "agy_book_dialogue" not in names(definitions)


def test_combined_discovery_exposes_book_tool_once_and_preserves_cli():
    discover_builtin_tools()
    definitions = get_tool_definitions(
        ["hermes-cli", "book-notes"], quiet_mode=True, skip_tool_search_assembly=True
    )
    resolved = names(definitions)
    assert resolved.count("book_notes_retrieval") == 1
    assert resolved.count("agy_book_dialogue") == 1
    assert "terminal" in resolved and "read_file" in resolved


def test_platform_config_preserves_book_notes_alongside_hermes_cli():
    enabled = _get_platform_tools(
        platform_configured(["hermes-cli", "book-notes"]),
        "cli",
        include_default_mcp_servers=False,
    )
    assert "book-notes" in enabled


def test_platform_config_does_not_drop_standalone_book_notes():
    enabled = _get_platform_tools(
        platform_configured(["book-notes"]),
        "cli",
        include_default_mcp_servers=False,
    )
    assert "book-notes" in enabled


def test_empty_enabled_toolsets_retains_existing_empty_contract():
    assert resolve_multiple_toolsets([]) == []


def test_unknown_toolset_is_invalid_and_resolves_empty(capsys):
    assert validate_toolset("definitely-unknown-built-in") is False
    assert resolve_toolset("definitely-unknown-built-in") == []
    get_tool_definitions(["definitely-unknown-built-in"], quiet_mode=False)
    assert "Unknown toolset: definitely-unknown-built-in" in capsys.readouterr().out


def test_catalog_tool_exists_in_registry_after_discovery():
    discover_builtin_tools()
    assert registry.get_entry("book_notes_retrieval") is not None
    assert registry.get_all_tool_names().count("book_notes_retrieval") == 1
    assert registry.get_entry("agy_book_dialogue") is not None
    assert registry.get_all_tool_names().count("agy_book_dialogue") == 1


def test_registry_presence_does_not_bypass_enabled_filter():
    discover_builtin_tools()
    assert registry.get_entry("book_notes_retrieval") is not None
    assert registry.get_entry("agy_book_dialogue") is not None
    assert "book_notes_retrieval" not in names(
        get_tool_definitions(["terminal"], quiet_mode=True, skip_tool_search_assembly=True)
    )


def test_builtin_catalog_pattern_is_generic(monkeypatch):
    TOOLSETS["synthetic-builtin"] = {
        "description": "Synthetic built-in declaration",
        "tools": ["synthetic_builtin_tool"],
        "includes": [],
        "built_in": True,
        "read_only": True,
    }
    try:
        assert validate_toolset("synthetic-builtin") is True
        assert resolve_toolset("synthetic-builtin", include_registry=False) == ["synthetic_builtin_tool"]
    finally:
        del TOOLSETS["synthetic-builtin"]


def test_book_notes_schema_actions_paths_and_readonly_contract():
    discover_builtin_tools()
    definition = next(
        item["function"] for item in get_tool_definitions(
            ["book-notes"], quiet_mode=True, skip_tool_search_assembly=True
        ) if item["function"]["name"] == "book_notes_retrieval"
    )
    properties = definition["parameters"]["properties"]
    assert properties["action"]["enum"] == ["resolve_book", "current_book", "other_books"]
    assert not {"db_path", "source_root", "model_path", "metadata_dir", "table_name"} & set(properties)
    assert "read-only" in definition["description"].lower()
    assert "does not imply endorsement" in definition["description"].lower()


def test_repeated_discovery_does_not_duplicate_registration():
    discover_builtin_tools()
    discover_builtin_tools()
    assert registry.get_all_tool_names().count("book_notes_retrieval") == 1
    assert registry.get_all_tool_names().count("agy_book_dialogue") == 1


def test_fresh_process_source_discovery_is_lazy_and_stable(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    code = r'''
import json, sys
from tools.registry import discover_builtin_tools
from model_tools import get_tool_definitions
discover_builtin_tools()
defs = get_tool_definitions(
    ["hermes-cli", "book-notes"], quiet_mode=True, skip_tool_search_assembly=True
)
names = [item["function"]["name"] for item in defs]
target = next(item["function"] for item in defs if item["function"]["name"] == "book_notes_retrieval")
print(json.dumps({
    "count": names.count("book_notes_retrieval"),
    "agy_count": names.count("agy_book_dialogue"),
    "terminal": "terminal" in names,
    "actions": target["parameters"]["properties"]["action"]["enum"],
    "sentence_transformers_loaded": "sentence_transformers" in sys.modules,
    "lancedb_loaded": "lancedb" in sys.modules,
}, sort_keys=True))
'''
    first = subprocess.run([sys.executable, "-c", code], cwd=repo, text=True, capture_output=True, check=True)
    second = subprocess.run([sys.executable, "-c", code], cwd=repo, text=True, capture_output=True, check=True)
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload == {
        "agy_count": 1,
        "actions": ["resolve_book", "current_book", "other_books"],
        "count": 1,
        "lancedb_loaded": False,
        "sentence_transformers_loaded": False,
        "terminal": True,
    }


def test_discovery_does_not_create_files(tmp_path, monkeypatch):
    before = list(tmp_path.iterdir())
    discover_builtin_tools()
    get_tool_definitions(["book-notes"], quiet_mode=True, skip_tool_search_assembly=True)
    assert list(tmp_path.iterdir()) == before
