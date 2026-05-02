from fnmatch import fnmatch
from pathlib import Path

SENSITIVE_FILE_NAMES: set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    ".env.development",
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".bash_logout",
    ".bash_history",
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".zlogin",
    ".zlogout",
    ".zsh_history",
    ".profile",
    ".login",
    ".cshrc",
    ".tcshrc",
    ".kshrc",
    ".fishrc",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".pgpass",
    ".my.cnf",
    ".docker/config.json",
    ".aws/credentials",
    ".aws/config",
    ".ssh/config",
    ".ssh/known_hosts",
    ".gitconfig",
    "credentials.json",
    "service-account.json",
    "service_account.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "secrets.toml",
    ".secrets",
    "token.json",
    "tokens.json",
    "keyfile.json",
    ".htpasswd",
}

SENSITIVE_FILE_EXTENSIONS: set[str] = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    ".crt",
    ".cer",
    ".der",
    ".pkcs12",
}

SENSITIVE_FILE_PREFIXES: tuple[str, ...] = (
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
)

WRITE_PROTECTED_PATHS: tuple[str, ...] = (".sigil/",)

BINARY_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".bin",
    ".dat",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".lock",
    ".map",
}


def is_sensitive_file(file: str) -> bool:
    name = Path(file).name
    if name in SENSITIVE_FILE_NAMES:
        return True
    normalized = file.replace("\\", "/")
    for part in normalized.split("/"):
        if part in SENSITIVE_FILE_NAMES:
            return True
    suffix = Path(file).suffix.lower()
    if suffix in SENSITIVE_FILE_EXTENSIONS:
        return True
    if name.startswith(SENSITIVE_FILE_PREFIXES):
        return True
    if name.startswith(".env."):
        return True
    return False


def is_binary_file(file: str) -> bool:
    return Path(file).suffix.lower() in BINARY_EXTENSIONS


def is_write_protected(file: str) -> bool:
    normalized = file.replace("\\", "/")
    return any(normalized.startswith(p) or f"/{p}" in normalized for p in WRITE_PROTECTED_PATHS)


def validate_path(repo: Path, file: str, ignore: list[str] | None = None) -> Path | None:
    if is_sensitive_file(file):
        return None
    if ignore and any(fnmatch(file, p) for p in ignore):
        return None
    try:
        resolved = (repo / file).resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(repo.resolve()):
        return None
    return resolved
