import pytest

from sigil.core.config import (
    AGENT_NAMES,
    CONFIG_FILE,
    Config,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MODEL,
    SIGIL_DIR,
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
    config = Config(agents={"auditor": [{"model": "openai/gpt-4o"}]})
    assert config.model_for("auditor") == "openai/gpt-4o"


def test_model_for_unknown_agent_raises():
    config = Config()
    with pytest.raises(ValueError, match="Unknown agent"):
        config.model_for("nonexistent")


def test_instances_for_default_returns_single_using_global_model():
    config = Config(model="custom/model")
    instances = config.instances_for("ideator")
    assert len(instances) == 1
    assert instances[0].model == "custom/model"
    assert instances[0].max_iterations == DEFAULT_MAX_ITERATIONS["ideator"]
    assert instances[0].max_tokens is None
    assert instances[0].reasoning_effort is None


def test_instances_for_with_entries():
    config = Config(
        model="default/model",
        agents={
            "ideator": [
                {"model": "m1"},
                {"model": "m2", "reasoning_effort": "high", "max_tokens": 8000},
            ]
        },
    )
    instances = config.instances_for("ideator")
    assert [i.model for i in instances] == ["m1", "m2"]
    assert instances[1].reasoning_effort == "high"
    assert instances[1].max_tokens == 8000


def test_instances_for_falls_back_to_global_model_per_entry():
    config = Config(
        model="global/model",
        agents={"ideator": [{}, {"max_iterations": 20}]},
    )
    instances = config.instances_for("ideator")
    assert instances[0].model == "global/model"
    assert instances[1].model == "global/model"
    assert instances[1].max_iterations == 20


def test_instances_for_unknown_agent_raises():
    config = Config()
    with pytest.raises(ValueError, match="Unknown agent"):
        config.instances_for("nonexistent")


def test_load_agent_not_list_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nagents:\n  ideator: not-a-list\n")
    with pytest.raises(ValueError, match="agents.ideator must be a list"):
        Config.load(tmp_path)


def test_load_agent_empty_list_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nagents:\n  ideator: []\n")
    with pytest.raises(ValueError, match="agents.ideator must have at least one entry"):
        Config.load(tmp_path)


def test_load_agent_entry_not_mapping_raises(config_path, tmp_path):
    config_path.write_text('version: 1\nagents:\n  ideator:\n    - "model-a"\n')
    with pytest.raises(ValueError, match=r"agents\.ideator\[0\] must be a mapping"):
        Config.load(tmp_path)


def test_load_agent_unknown_key_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nagents:\n  ideator:\n    - model: m\n      bogus: 1\n")
    with pytest.raises(ValueError, match=r"Unknown key.*bogus"):
        Config.load(tmp_path)


def test_load_agent_invalid_reasoning_effort_raises(config_path, tmp_path):
    config_path.write_text(
        "version: 1\nagents:\n  ideator:\n    - model: m\n      reasoning_effort: extreme\n"
    )
    with pytest.raises(ValueError, match="Invalid reasoning_effort"):
        Config.load(tmp_path)


def test_load_agent_validates_every_entry_in_list(config_path, tmp_path):
    config_path.write_text(
        "version: 1\nagents:\n"
        "  ideator:\n"
        "    - model: good\n"
        "    - model: bad\n"
        "      reasoning_effort: extreme\n"
    )
    with pytest.raises(ValueError, match=r"Invalid reasoning_effort.*agents\.ideator\[1\]"):
        Config.load(tmp_path)


def test_load_top_level_ideators_field_is_unknown(config_path, tmp_path):
    config_path.write_text("version: 1\nideators:\n  - model: m\n")
    with pytest.raises(ValueError, match="Unknown field.*ideators"):
        Config.load(tmp_path)


def test_load_arbiter_field_raises(config_path, tmp_path):
    config_path.write_text("version: 1\narbiter: true\n")
    with pytest.raises(ValueError, match="Unknown field.*arbiter"):
        Config.load(tmp_path)


def test_load_unknown_agent_arbiter_raises(config_path, tmp_path):
    config_path.write_text("version: 1\nagents:\n  arbiter:\n    - model: m\n")
    with pytest.raises(ValueError, match="Unknown agent.*arbiter"):
        Config.load(tmp_path)


def test_check_staleness_defaults_to_true():
    config = Config()
    assert config.check_staleness is True


def test_check_staleness_loadable_from_yaml(config_path, tmp_path):
    config_path.write_text("version: 1\ncheck_staleness: false\n")
    loaded = Config.load(tmp_path)
    assert loaded.check_staleness is False


def test_check_staleness_in_to_yaml():
    yaml_str = Config().to_yaml()
    assert "check_staleness" in yaml_str
