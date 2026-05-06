import pytest

from sigil.core.config import (
    AGENT_NAMES,
    Config,
    DEFAULT_MODEL,
    SIGIL_DIR,
    CONFIG_FILE,
)


@pytest.fixture()
def config_path(tmp_path):
    d = tmp_path / SIGIL_DIR
    d.mkdir()
    return d / CONFIG_FILE


def test_load_missing_file_returns_defaults(tmp_path):
    config = Config.load(tmp_path)
    assert config == Config()


def test_load_valid_config(config_path, tmp_path):
    cfg = Config(model="openai/gpt-4o", boldness="conservative", max_prs_per_run=5)
    config_path.write_text(cfg.to_yaml())
    loaded = Config.load(tmp_path)
    assert loaded.model == "openai/gpt-4o"
    assert loaded.boldness == "conservative"
    assert loaded.max_prs_per_run == 5


def test_load_unknown_fields_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nfoo: bar\nbaz: 42\n")
    with pytest.raises(ValueError, match="Unknown field.*baz.*foo"):
        Config.load(tmp_path)


def test_load_invalid_boldness_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nboldness: yolo\n")
    with pytest.raises(ValueError, match="Invalid boldness.*yolo"):
        Config.load(tmp_path)


def test_load_schedule_field_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nschedule: '0 3 * * *'\nboldness: bold\n")
    with pytest.raises(ValueError, match="Unknown field.*schedule"):
        Config.load(tmp_path)


def test_load_invalid_yaml_raises(config_path, tmp_path):
    config_path.write_text(":\n  - :\n    bad: [unmatched")
    with pytest.raises(ValueError, match="Invalid YAML"):
        Config.load(tmp_path)


def test_load_non_mapping_raises(config_path, tmp_path):
    config_path.write_text("just a string\n")
    with pytest.raises(ValueError, match="must be a YAML mapping.*str"):
        Config.load(tmp_path)


def test_to_yaml_no_schedule():
    yaml_str = Config().to_yaml()
    assert "schedule" not in yaml_str


@pytest.mark.parametrize("agent", sorted(AGENT_NAMES))
def test_model_for_all_agents_default_to_global_model(agent):
    config = Config()
    assert config.model_for(agent) == DEFAULT_MODEL


def test_model_for_user_override_wins():
    config = Config(agents={"ideator": {"model": "openai/gpt-4o"}})
    assert config.model_for("ideator") == "openai/gpt-4o"


def test_model_for_unknown_agent_raises():
    config = Config()
    with pytest.raises(ValueError, match="Unknown agent"):
        config.model_for("nonexistent")


def test_auto_merge_defaults_empty():
    config = Config()
    assert config.auto_merge == {}


def test_auto_merge_valid_config(config_path, tmp_path):
    config_path.write_text(
        "version: 1\n"
        "auto_merge:\n"
        "  enabled: true\n"
        "  categories:\n"
        "    - dead_code\n"
        "    - types\n"
        "  max_files: 5\n"
        "  max_lines: 200\n"
        "  required_checks:\n"
        "    - ci/lint\n"
        "  merge_method: squash\n"
    )
    loaded = Config.load(tmp_path)
    assert loaded.auto_merge["enabled"] is True
    assert loaded.auto_merge["categories"] == ["dead_code", "types"]
    assert loaded.auto_merge["max_files"] == 5
    assert loaded.auto_merge["max_lines"] == 200
    assert loaded.auto_merge["required_checks"] == ["ci/lint"]
    assert loaded.auto_merge["merge_method"] == "squash"


def test_auto_merge_unknown_keys_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nauto_merge:\n  enabled: true\n  bogus: 42\n")
    with pytest.raises(ValueError, match="Unknown key.*bogus"):
        Config.load(tmp_path)


@pytest.mark.parametrize(
    "key, bad_value, expected_msg",
    [
        ("enabled", "yes", "auto_merge.enabled must be a boolean"),
        ("categories", "dead_code", "auto_merge.categories must be a list"),
        ("categories", [42], "auto_merge.categories must be a list of strings"),
        ("max_files", -1, "auto_merge.max_files must be a positive integer"),
        ("max_files", "five", "auto_merge.max_files must be a positive integer"),
        ("max_lines", 0, "auto_merge.max_lines must be a positive integer"),
        ("required_checks", "ci", "auto_merge.required_checks must be a list"),
        ("required_checks", [42], "auto_merge.required_checks must be a list of strings"),
        ("merge_method", "fast-forward", "auto_merge.merge_method must be one of"),
    ],
)
def test_auto_merge_invalid_types_raises(config_path, tmp_path, key, bad_value, expected_msg):
    import yaml

    raw = {"version": 1, "auto_merge": {key: bad_value}}
    config_path.write_text(yaml.dump(raw))
    with pytest.raises(ValueError, match=expected_msg):
        Config.load(tmp_path)


def test_auto_merge_disabled_loads(config_path, tmp_path):
    config_path.write_text("version: 1\nauto_merge:\n  enabled: false\n")
    loaded = Config.load(tmp_path)
    assert loaded.auto_merge["enabled"] is False


def test_auto_merge_empty_dict_is_default(config_path, tmp_path):
    config_path.write_text("version: 1\n")
    loaded = Config.load(tmp_path)
    assert loaded.auto_merge == {}
