import json
import logging
from pathlib import Path
import pytest
from sigil.core.json_utils import load_json_safe


def test_load_json_safe_success(tmp_path):
    data = {"key": "value", "list": [1, 2, 3]}
    json_file = tmp_path / "test.json"
    json_file.write_text(json.dumps(data))

    result = load_json_safe(json_file)
    assert result == data


def test_load_json_safe_file_not_found(caplog):
    non_existent = Path("non_existent_file.json")
    default = {"default": "value"}

    with caplog.at_level(logging.WARNING):
        result = load_json_safe(non_existent, default=default)

    assert result == default
    assert "JSON file not found" in caplog.text


def test_load_json_safe_invalid_json(tmp_path, caplog):
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{invalid: json}")
    default = []

    with caplog.at_level(logging.WARNING):
        result = load_json_safe(invalid_json, default=default)

    assert result == default
    assert "Failed to decode JSON" in caplog.text


@pytest.mark.parametrize("default_val", [None, {}, [], "fallback"])
def test_load_json_safe_various_defaults(tmp_path, default_val):
    non_existent = tmp_path / "missing.json"
    result = load_json_safe(non_existent, default=default_val)
    assert result == default_val
