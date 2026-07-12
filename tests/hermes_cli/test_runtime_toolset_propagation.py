from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from hermes_cli.config import validate_config_structure
from hermes_cli.tools_config import _get_platform_tools
from hermes_cli.toolset_validation import normalize_runtime_toolsets
from toolsets import validate_toolset


def normalize(config, platform="cli"):
    return normalize_runtime_toolsets(config, platform, validate_toolset)


def test_canonical_global_toolsets_preserve_stable_order():
    assert normalize({"toolsets": ["hermes-cli", "book-notes"]}) == (
        "hermes-cli",
        "book-notes",
    )


def test_canonical_global_toolsets_deduplicate_without_reordering():
    assert normalize({"toolsets": ["book-notes", "hermes-cli", "book-notes"]}) == (
        "book-notes",
        "hermes-cli",
    )


def test_explicit_empty_global_selection_stays_empty():
    assert normalize({"toolsets": []}) == ()


def test_null_or_missing_global_selection_uses_caller_default():
    assert normalize({"toolsets": None}) is None
    assert normalize({}) is None


@pytest.mark.parametrize("value", [["hermes-cli", 7], "hermes-cli", {"hermes-cli": True}])
def test_invalid_global_selection_types_are_rejected(value):
    with pytest.raises(ValueError, match="toolsets"):
        normalize({"toolsets": value})


def test_unknown_global_toolset_is_not_silently_ignored():
    with pytest.raises(ValueError, match="unknown toolset.*not-a-toolset"):
        normalize({"toolsets": ["not-a-toolset"]})


def test_conflicting_nondefault_global_and_platform_selection_fails():
    config = {
        "toolsets": ["hermes-cli", "book-notes"],
        "platform_toolsets": {"cli": ["hermes-cli"]},
    }
    with pytest.raises(ValueError, match="conflicts with platform_toolsets.cli"):
        normalize(config)


def test_matching_global_and_platform_selection_is_allowed():
    selection = ["hermes-cli", "book-notes"]
    assert normalize({"toolsets": selection, "platform_toolsets": {"cli": selection}}) == tuple(selection)


def test_default_global_baseline_keeps_existing_platform_override_compatible():
    assert normalize({
        "toolsets": ["hermes-cli"],
        "platform_toolsets": {"cli": ["terminal", "file"]},
    }) == ("terminal", "file")


def test_normalization_does_not_mutate_other_config_fields():
    config = {
        "toolsets": ["hermes-cli", "book-notes"],
        "agent": {"max_turns": 11},
        "providers": {"synthetic": {"enabled": True}},
    }
    before = deepcopy(config)
    normalize(config)
    assert config == before


def test_config_structure_reports_toolset_contract_errors():
    unknown = validate_config_structure({"toolsets": ["not-a-toolset"]})
    conflict = validate_config_structure({
        "toolsets": ["hermes-cli", "book-notes"],
        "platform_toolsets": {"cli": ["hermes-cli"]},
    })
    assert any(issue.severity == "error" and "unknown toolset" in issue.message for issue in unknown)
    assert any(issue.severity == "error" and "conflicts" in issue.message for issue in conflict)


def test_active_config_shape_reaches_bridge_platform_payload():
    enabled = _get_platform_tools(
        {"toolsets": ["hermes-cli", "book-notes"], "mcp_servers": {}},
        "cli",
        include_default_mcp_servers=False,
    )
    assert "book-notes" in enabled
    assert "terminal" in enabled


def test_book_notes_is_not_propagated_when_not_configured():
    enabled = _get_platform_tools(
        {"toolsets": ["hermes-cli"], "mcp_servers": {}},
        "cli",
        include_default_mcp_servers=False,
    )
    assert "book-notes" not in enabled


def test_cold_start_and_restart_payloads_are_identical():
    config = {"toolsets": ["hermes-cli", "book-notes"], "mcp_servers": {}}
    cold_start = sorted(_get_platform_tools(config, "cli"))
    restarted_worker = sorted(_get_platform_tools(deepcopy(config), "cli"))
    assert restarted_worker == cold_start
    assert restarted_worker.count("book-notes") == 1


def test_normalization_import_has_no_book_notes_model_or_db_side_effect(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    code = r'''
import json, sys
from hermes_cli.toolset_validation import normalize_runtime_toolsets
result = normalize_runtime_toolsets(
    {"toolsets": ["hermes-cli", "book-notes"]},
    "cli",
    lambda name: name in {"hermes-cli", "book-notes"},
)
print(json.dumps({
    "result": result,
    "handler_loaded": "tools.book_notes_retrieval_tool" in sys.modules,
    "model_loaded": "sentence_transformers" in sys.modules,
    "db_loaded": "lancedb" in sys.modules,
}, sort_keys=True))
'''
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(proc.stdout) == {
        "db_loaded": False,
        "handler_loaded": False,
        "model_loaded": False,
        "result": ["hermes-cli", "book-notes"],
    }


def test_fresh_process_config_to_discovery_source_chain_is_lazy_and_complete():
    repo = Path(__file__).resolve().parents[2]
    code = r'''
import json, sys
from hermes_cli.tools_config import _get_platform_tools
from model_tools import get_tool_definitions
from tools.registry import discover_builtin_tools

config = {"toolsets": ["hermes-cli", "book-notes"], "mcp_servers": {}}
worker_payload = sorted(_get_platform_tools(config, "cli", include_default_mcp_servers=False))
discover_builtin_tools()
definitions = get_tool_definitions(
    worker_payload, quiet_mode=True, skip_tool_search_assembly=True
)
names = [item["function"]["name"] for item in definitions]
target = next(item["function"] for item in definitions if item["function"]["name"] == "book_notes_retrieval")
print(json.dumps({
    "payload_has_cli": "terminal" in worker_payload,
    "payload_has_book_notes": "book-notes" in worker_payload,
    "count": names.count("book_notes_retrieval"),
    "terminal": "terminal" in names,
    "actions": target["parameters"]["properties"]["action"]["enum"],
    "model_loaded": "sentence_transformers" in sys.modules,
    "db_loaded": "lancedb" in sys.modules,
}, sort_keys=True))
'''
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(proc.stdout) == {
        "actions": ["resolve_book", "current_book", "other_books"],
        "count": 1,
        "db_loaded": False,
        "model_loaded": False,
        "payload_has_book_notes": True,
        "payload_has_cli": True,
        "terminal": True,
    }
