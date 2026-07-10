import json

from agent import observation_reducer


def test_observation_reducer_can_be_disabled(monkeypatch, tmp_path):
    raw = json.dumps({"stdout": "one\ntwo", "exit_code": 0, "command": "echo ok"})
    monkeypatch.setattr(observation_reducer, "_OBS_DIR", tmp_path / "disabled")
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"observation_reducer": {"enabled": False}},
    )
    observation_reducer._reset_observation_reducer_config_cache()

    card, raw_ref = observation_reducer.reduce_observation(
        "terminal",
        raw,
        exit_code=0,
        command="echo ok",
    )

    assert card == raw
    assert raw_ref is None
    assert not (tmp_path / "disabled").exists()


def test_terminal_observation_reducer_writes_raw_output(monkeypatch, tmp_path):
    raw = json.dumps(
        {
            "stdout": "\n".join(f"line {idx}" for idx in range(40)),
            "stderr": "ERROR failed setup",
            "exit_code": 1,
            "command": "npm test",
        }
    )
    monkeypatch.setattr(observation_reducer, "_OBS_DIR", tmp_path / "run_test")
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"observation_reducer": {"enabled": True}},
    )
    observation_reducer._reset_observation_reducer_config_cache()

    card, raw_ref = observation_reducer.reduce_observation(
        "terminal",
        raw,
        exit_code=1,
        command="npm test",
    )

    assert card.startswith("[OBSERVATION:terminal] exit=1 | cmd: npm test")
    assert "summary: ERROR failed setup" in card
    assert "stdout_tail:" in card
    assert "line 39" in card
    assert raw_ref == str(tmp_path / "run_test")
    assert list((tmp_path / "run_test").glob("*.stdout.log"))
    assert list((tmp_path / "run_test").glob("*.stderr.log"))


def test_read_file_source_code_is_not_reduced(monkeypatch, tmp_path):
    content = "\n".join(
        [
            "def example(value):",
            "    if value:",
            "        return value + 1",
            "    return 0",
        ]
        * 60
    )
    raw = json.dumps(
        {
            "path": "/repo/app.py",
            "content": content,
            "offset": 1,
            "total_lines": 240,
        }
    )
    monkeypatch.setattr(observation_reducer, "_OBS_DIR", tmp_path / "run_code")
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"observation_reducer": {"enabled": True}},
    )
    observation_reducer._reset_observation_reducer_config_cache()

    card, raw_ref = observation_reducer.reduce_observation("read_file", raw)

    assert card == raw
    assert raw_ref is None
    assert not (tmp_path / "run_code").exists()


def test_read_file_high_fidelity_text_is_not_reduced(monkeypatch, tmp_path):
    content = "\n".join(
        ["本合同条款应逐字校对，不得摘要或压缩。甲方与乙方确认如下内容。"] * 240
    )
    raw = json.dumps(
        {
            "path": "/repo/contract.txt",
            "content": content,
            "offset": 1,
            "total_lines": 240,
        }
    )
    monkeypatch.setattr(observation_reducer, "_OBS_DIR", tmp_path / "run_contract")
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"observation_reducer": {"enabled": True}},
    )
    observation_reducer._reset_observation_reducer_config_cache()

    card, raw_ref = observation_reducer.reduce_observation("read_file", raw)

    assert card == raw
    assert raw_ref is None
    assert not (tmp_path / "run_contract").exists()
