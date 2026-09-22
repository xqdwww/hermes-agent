import importlib.util
from pathlib import Path

import yaml


SCRIPT = Path(__file__).parents[1] / "scripts" / "clash_verge_source_refresh_adapter.py"
SPEC = importlib.util.spec_from_file_location("source_refresh_adapter", SCRIPT)
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(adapter)


def test_disable_helper_network_side_effects(tmp_path):
    path = tmp_path / "verge.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "enable_system_proxy": True,
                "enable_tun_mode": True,
                "theme": "system",
            }
        )
    )

    adapter.disable_helper_network_side_effects(tmp_path)

    result = yaml.safe_load(path.read_text())
    assert result == {
        "enable_system_proxy": False,
        "enable_tun_mode": False,
        "theme": "system",
    }
    assert path.stat().st_mode & 0o077 == 0


def test_disable_helper_network_side_effects_allows_missing_file(tmp_path):
    adapter.disable_helper_network_side_effects(tmp_path)
