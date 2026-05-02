import pytest

from sigil.core.config import (
    AGENT_NAMES,
    Config,
    DEFAULT_MODEL,
    DEFAULT_STAGE_TIMEOUTS,
    SIGIL_DIR,
    STAGE_NAMES,
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


@pytest.mark.parametrize("stage", sorted(STAGE_NAMES))
def test_stage_timeout_returns_defaults(stage):
    config = Config()
    assert config.stage_timeout(stage) == DEFAULT_STAGE_TIMEOUTS[stage]


def test_stage_timeout_user_override():
    config = Config(stage_timeouts={"analysis": 1200})
    assert config.stage_timeout("analysis") == 1200


@pytest.mark.parametrize("zero_val", [0, -1, -5])
def test_stage_timeout_zero_or_negative_returns_none(zero_val):
    config = Config(stage_timeouts={"analysis": zero_val})
    assert config.stage_timeout("analysis") is None


def test_stage_timeout_unknown_stage_raises():
    config = Config()
    with pytest.raises(ValueError, match="Unknown stage"):
        config.stage_timeout("nonexistent")


def test_load_stage_timeouts_valid(config_path, tmp_path):
    config_path.write_text("version: 1\nstage_timeouts:\n  analysis: 1200\n  execution: 1800\n")
    loaded = Config.load(tmp_path)
    assert loaded.stage_timeouts == {"analysis": 1200, "execution": 1800}
    assert loaded.stage_timeout("analysis") == 1200
    assert loaded.stage_timeout("execution") == 1800
    assert loaded.stage_timeout("ideation") == DEFAULT_STAGE_TIMEOUTS["ideation"]


def test_load_stage_timeouts_invalid_name_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nstage_timeouts:\n  bogus_stage: 100\n")
    with pytest.raises(ValueError, match="Unknown stage.*bogus_stage"):
        Config.load(tmp_path)


def test_load_stage_timeouts_non_integer_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nstage_timeouts:\n  analysis: abc\n")
    with pytest.raises(ValueError, match="must be an integer"):
        Config.load(tmp_path)


def test_load_stage_timeouts_negative_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nstage_timeouts:\n  analysis: -10\n")
    with pytest.raises(ValueError, match="must be a non-negative integer"):
        Config.load(tmp_path)


def test_to_yaml_includes_stage_timeouts():
    yaml_str = Config().to_yaml()
    assert "stage_timeouts" in yaml_str
    for stage in STAGE_NAMES:
        assert stage in yaml_str
