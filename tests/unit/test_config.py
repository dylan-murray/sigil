import pytest

from sigil.core.config import (
    AGENT_NAMES,
    Config,
    DEFAULT_MODEL,
    DEFAULT_IGNORE,
    SIGIL_DIR,
    CONFIG_FILE,
    LOCAL_CONFIG_FILE,
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


@pytest.fixture()
def local_config_path(tmp_path):
    d = tmp_path / SIGIL_DIR
    d.mkdir(exist_ok=True)
    return d / LOCAL_CONFIG_FILE


def test_local_config_overrides_model(config_path, local_config_path, tmp_path):
    cfg = Config(model="anthropic/claude-sonnet-4-6")
    config_path.write_text(cfg.to_yaml())
    local_config_path.write_text("model: openai/gpt-4o\n")
    loaded = Config.load(tmp_path)
    assert loaded.model == "openai/gpt-4o"


def test_local_config_overrides_boldness(config_path, local_config_path, tmp_path):
    cfg = Config(boldness="bold")
    config_path.write_text(cfg.to_yaml())
    local_config_path.write_text("boldness: conservative\n")
    loaded = Config.load(tmp_path)
    assert loaded.boldness == "conservative"


def test_local_config_deep_merges_agents(config_path, local_config_path, tmp_path):
    config_path.write_text(
        "model: anthropic/claude-sonnet-4-6\nboldness: bold\nagents:\n  architect:\n    model: google/gemini-2.5-pro\n"
    )
    local_config_path.write_text("agents:\n  engineer:\n    model: openai/gpt-4o\n")
    loaded = Config.load(tmp_path)
    assert loaded.model_for("architect") == "google/gemini-2.5-pro"
    assert loaded.model_for("engineer") == "openai/gpt-4o"


def test_local_config_agent_overrides_main_agent(config_path, local_config_path, tmp_path):
    config_path.write_text(
        "model: anthropic/claude-sonnet-4-6\nboldness: bold\nagents:\n  architect:\n    model: google/gemini-2.5-pro\n"
    )
    local_config_path.write_text("agents:\n  architect:\n    model: openai/gpt-4o\n")
    loaded = Config.load(tmp_path)
    assert loaded.model_for("architect") == "openai/gpt-4o"


def test_local_config_unknown_field_raises(config_path, local_config_path, tmp_path):
    cfg = Config()
    config_path.write_text(cfg.to_yaml())
    local_config_path.write_text("bogus_field: 123\n")
    with pytest.raises(ValueError, match="Unknown field.*bogus_field"):
        Config.load(tmp_path)


def test_local_config_invalid_boldness_raises(config_path, local_config_path, tmp_path):
    cfg = Config()
    config_path.write_text(cfg.to_yaml())
    local_config_path.write_text("boldness: yolo\n")
    with pytest.raises(ValueError, match="Invalid boldness.*yolo"):
        Config.load(tmp_path)


def test_local_config_invalid_yaml_raises(config_path, local_config_path, tmp_path):
    cfg = Config()
    config_path.write_text(cfg.to_yaml())
    local_config_path.write_text(":\n  - :\n    bad: [unmatched")
    with pytest.raises(ValueError, match="Invalid YAML"):
        Config.load(tmp_path)


def test_local_config_non_mapping_raises(config_path, local_config_path, tmp_path):
    cfg = Config()
    config_path.write_text(cfg.to_yaml())
    local_config_path.write_text("just a string\n")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        Config.load(tmp_path)


def test_missing_local_config_is_silently_ignored(config_path, tmp_path):
    cfg = Config(model="anthropic/claude-sonnet-4-6")
    config_path.write_text(cfg.to_yaml())
    loaded = Config.load(tmp_path)
    assert loaded.model == "anthropic/claude-sonnet-4-6"


def test_default_ignore_contains_local_config():
    assert ".sigil/config.local.yml" in DEFAULT_IGNORE


def test_local_config_overrides_max_spend(config_path, local_config_path, tmp_path):
    cfg = Config()
    config_path.write_text(cfg.to_yaml())
    local_config_path.write_text("max_spend_usd: 50.0\n")
    loaded = Config.load(tmp_path)
    assert loaded.max_spend_usd == 50.0


def test_local_config_invalid_max_spend_raises(config_path, local_config_path, tmp_path):
    cfg = Config()
    config_path.write_text(cfg.to_yaml())
    local_config_path.write_text("max_spend_usd: -5\n")
    with pytest.raises(ValueError, match="max_spend_usd must be positive"):
        Config.load(tmp_path)


def test_local_config_replaces_list_fields(config_path, local_config_path, tmp_path):
    cfg = Config(focus=["tests", "dead_code"])
    config_path.write_text(cfg.to_yaml())
    local_config_path.write_text("focus:\n  - security\n")
    loaded = Config.load(tmp_path)
    assert loaded.focus == ["security"]


def test_local_config_deep_merges_model_overrides(config_path, local_config_path, tmp_path):
    config_path.write_text(
        "model: anthropic/claude-sonnet-4-6\nboldness: bold\nmodel_overrides:\n  model-a:\n    max_input_tokens: 1000\n    max_output_tokens: 2000\n"
    )
    local_config_path.write_text("model_overrides:\n  model-b:\n    max_input_tokens: 3000\n")
    loaded = Config.load(tmp_path)
    assert "model-a" in loaded.model_overrides
    assert "model-b" in loaded.model_overrides
    assert loaded.model_overrides["model-b"]["max_input_tokens"] == 3000


def test_local_config_unknown_agent_raises(config_path, local_config_path, tmp_path):
    cfg = Config()
    config_path.write_text(cfg.to_yaml())
    local_config_path.write_text("agents:\n  nonexistent:\n    model: x\n")
    with pytest.raises(ValueError, match="Unknown agent"):
        Config.load(tmp_path)
