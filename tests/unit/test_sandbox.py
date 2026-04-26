import pytest

from sigil.core.config import Config
from sigil.pipeline.sandbox import (
    BLOCKED_DOMAINS,
    MODEL_DOMAIN_MAP,
    PACKAGE_MANAGER_DOMAINS,
    _infer_provider,
    _validate_allowlist,
    build_network_allowlist,
)


@pytest.mark.parametrize(
    "model, expected",
    [
        ("anthropic/claude-3-opus", "anthropic"),
        ("openai/gpt-4o", "openai"),
        ("gemini/gemini-1.5-pro", "gemini"),
        ("vertex_ai/gemini-pro", "vertex_ai"),
        ("azure/gpt-4", "azure"),
        ("custom/provider/model", "custom"),
        ("gpt-4o", "openai"),
        ("claude-3-opus", "openai"),
        ("", "openai"),
    ],
    ids=[
        "anthropic",
        "openai_slash",
        "gemini",
        "vertex_ai",
        "azure",
        "nested_slash_takes_first",
        "no_slash_openai_default",
        "no_slash_claude_openai_default",
        "empty_string",
    ],
)
def test_infer_provider(model: str, expected: str) -> None:
    assert _infer_provider(model) == expected


@pytest.mark.parametrize(
    "domains, expected",
    [
        (["api.anthropic.com"], ["api.anthropic.com"]),
        (["  Api.Anthropic.Com  "], ["api.anthropic.com"]),
        (["", "  ", "\t"], []),
        (list(BLOCKED_DOMAINS), []),
        (["*.wildcard.com"], []),
        (["192.168.1.1"], []),
        (["10.0.0.1"], []),
        (["example.com", "169.254.169.254", "another.com"], ["another.com", "example.com"]),
    ],
    ids=[
        "valid_domain",
        "strips_and_lowercases",
        "empty_and_whitespace_only",
        "all_blocked",
        "wildcard_rejected",
        "ip_address_rejected",
        "private_ip_rejected",
        "mixed_filters_valid_kept",
    ],
)
def test_validate_allowlist(domains: list[str], expected: list[str]) -> None:
    result = _validate_allowlist(domains)
    assert sorted(result) == sorted(expected)


def test_validate_allowlist_preserves_port_number_domains() -> None:
    result = _validate_allowlist(["custom-registry.example.com:8080"])
    assert result == ["custom-registry.example.com:8080"]


def test_validate_allowlist_empty_input() -> None:
    assert _validate_allowlist([]) == []


def _make_config(model: str = "anthropic/claude-3-opus", allowlist: tuple[str, ...] = ()) -> Config:
    return Config(model=model, sandbox_allowlist=allowlist)


def test_build_network_allowlist_anthropic() -> None:
    config = _make_config(model="anthropic/claude-opus-4")
    result = build_network_allowlist(config)
    assert "api.anthropic.com" in result
    for domain in PACKAGE_MANAGER_DOMAINS:
        assert domain in result


def test_build_network_allowlist_openai() -> None:
    config = _make_config(model="openai/gpt-4o")
    result = build_network_allowlist(config)
    assert "api.openai.com" in result
    for domain in PACKAGE_MANAGER_DOMAINS:
        assert domain in result


def test_build_network_allowlist_unknown_provider_falls_back_to_openai() -> None:
    config = _make_config(model="unknown/model")
    result = build_network_allowlist(config)
    assert "api.openai.com" in result


def test_build_network_allowlist_no_slash_defaults_to_openai() -> None:
    config = _make_config(model="gpt-4o")
    result = build_network_allowlist(config)
    assert "api.openai.com" in result


def test_build_network_allowlist_is_sorted() -> None:
    config = _make_config(model="anthropic/claude-3-opus")
    result = build_network_allowlist(config)
    assert result == sorted(result)


def test_build_network_allowlist_deduplicates() -> None:
    config = _make_config(
        model="anthropic/claude-3-opus",
        allowlist=("api.anthropic.com",),
    )
    result = build_network_allowlist(config)
    assert result.count("api.anthropic.com") == 1


def test_build_network_allowlist_user_domains_appended() -> None:
    config = _make_config(
        model="anthropic/claude-3-opus",
        allowlist=("registry.example.com", "custom-pkg.io"),
    )
    result = build_network_allowlist(config)
    assert "registry.example.com" in result
    assert "custom-pkg.io" in result


def test_build_network_allowlist_blocked_user_domains_excluded() -> None:
    config = _make_config(
        model="anthropic/claude-3-opus",
        allowlist=("169.254.169.254", "*.wildcard.com"),
    )
    result = build_network_allowlist(config)
    assert "169.254.169.254" not in result
    assert "*.wildcard.com" not in result


@pytest.mark.parametrize("provider", list(MODEL_DOMAIN_MAP.keys()))
def test_build_network_allowlist_all_known_providers(provider: str) -> None:
    config = _make_config(model=f"{provider}/some-model")
    result = build_network_allowlist(config)
    for domain in MODEL_DOMAIN_MAP[provider]:
        assert domain in result
