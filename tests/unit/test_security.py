import pytest

from sigil.core.security import is_sensitive_file, is_write_protected, validate_path


@pytest.mark.parametrize(
    "file_path",
    [
        ".env",
        ".env.local",
        ".env.production",
        ".env.staging",
        ".env.development",
        ".bashrc",
        ".zshrc",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".gitconfig",
        "credentials.json",
        "service-account.json",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        "token.json",
        ".htpasswd",
    ],
)
def test_is_sensitive_file_known_names(file_path):
    assert is_sensitive_file(file_path)


@pytest.mark.parametrize(
    "file_path",
    [
        ".aws/credentials",
        ".aws/config",
        ".ssh/config",
        ".ssh/known_hosts",
        ".docker/config.json",
        "home/user/.aws/credentials",
        "home/user/.ssh/config",
    ],
)
def test_is_sensitive_file_known_paths(file_path):
    assert is_sensitive_file(file_path)


@pytest.mark.parametrize(
    "file_path",
    [
        "key.pem",
        "server.key",
        "cert.p12",
        "store.pfx",
        "trust.jks",
        "keystore.keystore",
        "cert.crt",
        "cert.cer",
        "cert.der",
        "bundle.pkcs12",
    ],
)
def test_is_sensitive_file_extensions(file_path):
    assert is_sensitive_file(file_path)


@pytest.mark.parametrize(
    "file_path",
    [
        "id_rsa",
        "id_rsa.pub",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    ],
)
def test_is_sensitive_file_ssh_key_prefix(file_path):
    assert is_sensitive_file(file_path)


@pytest.mark.parametrize(
    "file_path",
    [
        ".env.production",
        ".env.custom_name",
        ".env.test",
    ],
)
def test_is_sensitive_file_env_prefix_variants(file_path):
    assert is_sensitive_file(file_path)


@pytest.mark.parametrize(
    "file_path",
    [
        "src/main.py",
        "README.md",
        "pyproject.toml",
        "config.yaml",
        "settings.json",
        "data.csv",
        ".gitignore",
    ],
)
def test_is_sensitive_file_safe_files(file_path):
    assert not is_sensitive_file(file_path)


def test_is_sensitive_file_nested_sensitive_name():
    assert is_sensitive_file("subdir/.env")
    assert is_sensitive_file("deep/nested/.aws/credentials")


@pytest.mark.parametrize(
    "file_path",
    [
        ".sigil/config.yml",
        ".sigil/memory/working.md",
        ".sigil/ideas/foo.md",
    ],
)
def test_is_write_protected_sigil_paths(file_path):
    assert is_write_protected(file_path)


@pytest.mark.parametrize(
    "file_path",
    [
        "src/main.py",
        "README.md",
        ".github/workflows/ci.yml",
    ],
)
def test_is_write_protected_safe_paths(file_path):
    assert not is_write_protected(file_path)


def test_validate_path_valid(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1")
    result = validate_path(tmp_path, "src/main.py")
    assert result is not None
    assert result == (tmp_path / "src" / "main.py").resolve()


def test_validate_path_sensitive_file(tmp_path):
    result = validate_path(tmp_path, ".env")
    assert result is None


def test_validate_path_traversal(tmp_path):
    result = validate_path(tmp_path, "../etc/passwd")
    assert result is None


def test_validate_path_absolute_escape(tmp_path):
    result = validate_path(tmp_path, "/etc/passwd")
    assert result is None


def test_validate_path_ignored_by_pattern(tmp_path):
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "lib.py").write_text("x = 1")
    result = validate_path(tmp_path, "vendor/lib.py", ignore=["vendor/**"])
    assert result is None


def test_validate_path_not_ignored_without_pattern(tmp_path):
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "lib.py").write_text("x = 1")
    result = validate_path(tmp_path, "vendor/lib.py")
    assert result is not None
