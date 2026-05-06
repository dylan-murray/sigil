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


class TestConfigHash:
    def test_config_hash_stability(self):
        config = Config(model="anthropic/claude-sonnet-4-6", boldness="balanced")
        h1 = config.config_hash()
        h2 = config.config_hash()
        assert h1 == h2

    def test_config_hash_changes_on_model_change(self):
        c1 = Config(model="anthropic/claude-sonnet-4-6")
        c2 = Config(model="openai/gpt-4o")
        assert c1.config_hash() != c2.config_hash()

    def test_config_hash_changes_on_boldness_change(self):
        c1 = Config(boldness="conservative")
        c2 = Config(boldness="bold")
        assert c1.config_hash() != c2.config_hash()

    def test_config_hash_ignores_non_perf_fields(self):
        c1 = Config(model="m1", max_spend_usd=10.0)
        c2 = Config(model="m1", max_spend_usd=100.0)
        assert c1.config_hash() == c2.config_hash()

    def test_config_hash_focus_order_invariant(self):
        c1 = Config(focus=("security", "tests"))
        c2 = Config(focus=("tests", "security"))
        assert c1.config_hash() == c2.config_hash()
