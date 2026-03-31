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


def test_shadow_mode_defaults_false():
    config = Config()
    assert config.shadow_mode is False


def test_shadow_mode_in_yaml_output():
    yaml_str = Config().to_yaml()
    assert "shadow_mode" in yaml_str


def test_shadow_mode_loads_from_yaml(config_path, tmp_path):
    config_path.write_text("shadow_mode: true\n")
    config = Config.load(tmp_path)
    assert config.shadow_mode is True


def test_shadow_mode_roundtrip(config_path, tmp_path):
    config_path.write_text("shadow_mode: true\n")
    loaded = Config.load(tmp_path)
    assert loaded.shadow_mode is True
