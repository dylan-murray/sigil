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


def test_builtin_conservative_profile(config_path, tmp_path):
    config_path.write_text("profile: conservative\n")
    loaded = Config.load(tmp_path)
    assert loaded.boldness == "conservative"
    assert loaded.max_prs_per_run == 2
    assert loaded.max_github_issues == 3
    assert loaded.profile == "conservative"


def test_builtin_balanced_profile(config_path, tmp_path):
    config_path.write_text("profile: balanced\n")
    loaded = Config.load(tmp_path)
    defaults = Config()
    assert loaded.boldness == defaults.boldness
    assert loaded.max_prs_per_run == defaults.max_prs_per_run
    assert loaded.max_github_issues == defaults.max_github_issues
    assert loaded.profile == "balanced"


def test_builtin_aggressive_profile(config_path, tmp_path):
    config_path.write_text("profile: aggressive\n")
    loaded = Config.load(tmp_path)
    assert loaded.boldness == "bold"
    assert loaded.max_prs_per_run == 10
    assert loaded.max_github_issues == 10
    assert loaded.profile == "aggressive"


def test_custom_profile_from_yaml_cautious(config_path, tmp_path):
    config_path.write_text(
        "profile: cautious\n"
        "profiles:\n"
        "  cautious:\n"
        "    boldness: conservative\n"
        "    max_prs_per_run: 1\n"
    )
    loaded = Config.load(tmp_path)
    assert loaded.boldness == "conservative"
    assert loaded.max_prs_per_run == 1
    assert loaded.profile == "cautious"


def test_user_value_overrides_profile(config_path, tmp_path):
    config_path.write_text("profile: conservative\nboldness: bold\nmax_prs_per_run: 99\n")
    loaded = Config.load(tmp_path)
    assert loaded.boldness == "bold"
    assert loaded.max_prs_per_run == 99
    assert loaded.profile == "conservative"


def test_cli_profile_overrides_yaml(config_path, tmp_path):
    config_path.write_text("profile: conservative\n")
    loaded = Config.load(tmp_path, profile="aggressive")
    assert loaded.boldness == "bold"
    assert loaded.max_prs_per_run == 10
    assert loaded.profile == "aggressive"


def test_unknown_profile_raises(config_path, tmp_path):
    config_path.write_text("profile: nonexistent\n")
    with pytest.raises(ValueError, match="Unknown profile.*nonexistent"):
        Config.load(tmp_path)


def test_unknown_profile_lists_available(config_path, tmp_path):
    config_path.write_text("profile: nope\n")
    with pytest.raises(ValueError, match="aggressive.*balanced.*conservative"):
        Config.load(tmp_path)


def test_invalid_keys_in_custom_profile_raises(config_path, tmp_path):
    config_path.write_text("profiles:\n  myprofile:\n    bad_key: 42\n")
    with pytest.raises(ValueError, match="Unknown key.*profiles.myprofile.*bad_key"):
        Config.load(tmp_path)


def test_custom_profile_not_dict_raises(config_path, tmp_path):
    config_path.write_text("profiles:\n  myprofile: 42\n")
    with pytest.raises(ValueError, match="profiles.myprofile must be a mapping"):
        Config.load(tmp_path)


def test_profiles_not_dict_raises(config_path, tmp_path):
    config_path.write_text("profiles: 42\n")
    with pytest.raises(ValueError, match="profiles must be a mapping"):
        Config.load(tmp_path)


def test_profile_none_when_no_profile(config_path, tmp_path):
    config_path.write_text("boldness: bold\n")
    loaded = Config.load(tmp_path)
    assert loaded.profile is None


def test_profile_none_on_defaults(tmp_path):
    loaded = Config.load(tmp_path)
    assert loaded.profile is None


def test_custom_profile_from_yaml(config_path, tmp_path):
    config_path.write_text(
        "profile: myprofile\n"
        "profiles:\n"
        "  myprofile:\n"
        "    boldness: conservative\n"
        "    max_prs_per_run: 1\n"
    )
    loaded = Config.load(tmp_path)
    assert loaded.boldness == "conservative"
    assert loaded.max_prs_per_run == 1
    assert loaded.profile == "myprofile"


def test_cli_profile_with_custom_profile(config_path, tmp_path):
    config_path.write_text(
        "profiles:\n  myprofile:\n    boldness: experimental\n    max_prs_per_run: 7\n"
    )
    loaded = Config.load(tmp_path, profile="myprofile")
    assert loaded.boldness == "experimental"
    assert loaded.max_prs_per_run == 7
    assert loaded.profile == "myprofile"


def test_user_value_overrides_custom_profile(config_path, tmp_path):
    config_path.write_text(
        "profile: myprofile\n"
        "boldness: bold\n"
        "profiles:\n"
        "  myprofile:\n"
        "    boldness: conservative\n"
        "    max_prs_per_run: 1\n"
    )
    loaded = Config.load(tmp_path)
    assert loaded.boldness == "bold"
    assert loaded.max_prs_per_run == 1
    assert loaded.profile == "myprofile"


def test_unknown_custom_profile_raises(config_path, tmp_path):
    config_path.write_text("profile: missing\nprofiles:\n  other:\n    boldness: bold\n")
    with pytest.raises(ValueError, match="Unknown profile.*missing"):
        Config.load(tmp_path)
