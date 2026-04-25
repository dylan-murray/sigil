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


def test_load_unknown_agent_name_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nagents:\n  robot:\n    model: x\n")
    with pytest.raises(ValueError, match="Unknown agent.*robot"):
        Config.load(tmp_path)


def test_load_unknown_agent_config_key_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nagents:\n  engineer:\n    temperature: 0.5\n")
    with pytest.raises(ValueError, match="Unknown key.*temperature"):
        Config.load(tmp_path)


def test_load_invalid_sandbox_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nsandbox: docker-in-docker\n")
    with pytest.raises(ValueError, match="Invalid sandbox"):
        Config.load(tmp_path)


def test_load_max_spend_zero_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nmax_spend_usd: 0\n")
    with pytest.raises(ValueError, match="max_spend_usd must be positive"):
        Config.load(tmp_path)


def test_load_max_spend_negative_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nmax_spend_usd: -5.0\n")
    with pytest.raises(ValueError, match="max_spend_usd must be positive"):
        Config.load(tmp_path)


def test_load_model_overrides_non_int_raises(config_path, tmp_path):
    config_path.write_text(
        "version: 1\nmodel_overrides:\n  gpt-4o:\n    max_output_tokens: 'lots'\n"
    )
    with pytest.raises(ValueError, match="must be a positive integer"):
        Config.load(tmp_path)


def test_load_model_overrides_unknown_key_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nmodel_overrides:\n  gpt-4o:\n    temperature: 1\n")
    with pytest.raises(ValueError, match="Unknown key.*temperature"):
        Config.load(tmp_path)


def test_load_model_overrides_non_mapping_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nmodel_overrides: just_a_string\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        Config.load(tmp_path)


def test_load_agent_config_non_mapping_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nagents:\n  engineer: not_a_dict\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        Config.load(tmp_path)


def test_max_iterations_for_default(tmp_path):
    config = Config.load(tmp_path)
    assert config.max_iterations_for("engineer") == 50
    assert config.max_iterations_for("auditor") == 15


def test_max_iterations_for_override():
    config = Config(agents={"engineer": {"max_iterations": 20}})
    assert config.max_iterations_for("engineer") == 20


def test_max_iterations_for_unknown_agent_raises():
    config = Config()
    with pytest.raises(ValueError, match="Unknown agent"):
        config.max_iterations_for("ghost")


def test_reasoning_effort_for_invalid_raises():
    config = Config(agents={"engineer": {"reasoning_effort": "turbo"}})
    with pytest.raises(ValueError, match="Invalid reasoning_effort.*turbo"):
        config.reasoning_effort_for("engineer")
