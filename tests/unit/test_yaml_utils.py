import logging
from pathlib import Path
from sigil.utils.yaml import load_yaml_safe, parse_yaml_safe


def test_parse_yaml_safe_success():
    yaml_str = "key: value\nlist: [1, 2, 3]"
    expected = {"key": "value", "list": [1, 2, 3]}
    assert parse_yaml_safe(yaml_str) == expected


def test_parse_yaml_safe_invalid():
    yaml_str = "key: : value"  # Invalid YAML
    default = {"default": "value"}
    assert parse_yaml_safe(yaml_str, default=default) == default


def test_parse_yaml_safe_empty():
    assert parse_yaml_safe("") is None
    assert parse_yaml_safe("   ") is None
    assert parse_yaml_safe("", default="default") == "default"


def test_load_yaml_safe_success(tmp_path):
    yaml_file = tmp_path / "config.yml"
    content = "key: value"
    yaml_file.write_text(content)
    assert load_yaml_safe(yaml_file) == {"key": "value"}


def test_load_yaml_safe_missing(tmp_path):
    yaml_file = tmp_path / "missing.yml"
    default = {"default": "value"}
    assert load_yaml_safe(yaml_file, default=default) == default


def test_load_yaml_safe_invalid(tmp_path):
    yaml_file = tmp_path / "invalid.yml"
    yaml_file.write_text("key: : value")
    default = {"default": "value"}
    assert load_yaml_safe(yaml_file, default=default) == default


def test_load_yaml_safe_empty(tmp_path):
    yaml_file = tmp_path / "empty.yml"
    yaml_file.write_text("")
    assert load_yaml_safe(yaml_file) is None
    assert load_yaml_safe(yaml_file, default="default") == "default"


def test_parse_yaml_safe_logs_warning(caplog):
    with caplog.at_level(logging.WARNING):
        parse_yaml_safe("key: : value")
    assert "Failed to parse YAML content" in caplog.text


def test_load_yaml_safe_logs_warning_missing(caplog):
    with caplog.at_level(logging.WARNING):
        load_yaml_safe(Path("nonexistent.yml"))
    assert "Failed to read YAML file" in caplog.text


def test_load_yaml_safe_logs_warning_invalid(caplog):
    yaml_file = Path("invalid_test.yml")
    yaml_file.write_text("key: : value")
    try:
        with caplog.at_level(logging.WARNING):
            load_yaml_safe(yaml_file)
        assert "Failed to parse YAML content" in caplog.text
    finally:
        yaml_file.unlink(missing_ok=True)
