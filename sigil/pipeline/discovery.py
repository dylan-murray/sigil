import asyncio
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from sigil.core.llm import CHARS_PER_TOKEN, get_context_window
from sigil.core.utils import StatusCallback, arun, read_truncated

MAX_FILE_LIST = 500

BINARY_EXTENSIONS = {
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

SKIP_DIRS = {
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "target",
    ".next",
    ".nuxt",
    "coverage",
    ".eggs",
    "egg-info",
}

ALREADY_READ_FILENAMES = {
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "mix.exs",
    "setup.py",
    "requirements.txt",
    "setup.cfg",
}

TEST_DIR_NAMES = {
    "tests",
    "test",
    "spec",
    "specs",
    "__tests__",
    "test_",
    "unittest",
    "unittests",
}

TEST_FILE_PATTERNS = {
    "python": {"test_", "_test.py"},
    "javascript": {".test.", ".spec."},
    "typescript": {".test.", ".spec."},
    "rust": {"_test"},
    "go": {"_test.go"},
    "ruby": {"_test.rb", "_spec.rb"},
    "java": {"Test.java"},
}

TEST_FRAMEWORKS = {
    "python": {"pytest", "unittest", "nose", "nose2"},
    "javascript": {"jest", "mocha", "vitest", "ava"},
    "typescript": {"jest", "mocha", "vitest", "ava"},
    "rust": {"cargo test"},
    "go": {"go test"},
    "ruby": {"rspec", "minitest"},
    "java": {"junit", "testng"},
}

CI_TEST_COMMANDS = {
    "pytest",
    "python -m pytest",
    "python -m unittest",
    "nose2",
    "jest",
    "mocha",
    "vitest",
    "cargo test",
    "go test",
    "go test ./...",
    "rspec",
    "bundle exec rspec",
    "mvn test",
    "gradle test",
    "make test",
    "npm test",
    "yarn test",
    "pnpm test",
    "deno test",
}

LANGUAGE_MARKERS = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "requirements.txt": "python",
    "package.json": "javascript",
    "tsconfig.json": "typescript",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "Gemfile": "ruby",
    "pom.xml": "java",
    "build.gradle": "java",
    "mix.exs": "elixir",
}

CI_MARKERS = {
    ".github/workflows": "github_actions",
    ".circleci": "circleci",
    ".gitlab-ci.yml": "gitlab",
    "Jenkinsfile": "jenkins",
    ".travis.yml": "travis",
}

PROMPT_OVERHEAD_TOKENS = 8_000
RESPONSE_RESERVE_TOKENS = 4_000


def _detect_language(repo: Path) -> str:
    for marker, lang in LANGUAGE_MARKERS.items():
        if (repo / marker).exists():
            return lang
    return "unknown"


def _detect_ci(repo: Path) -> str | None:
    for marker, provider in CI_MARKERS.items():
        if (repo / marker).exists():
            return provider
    return None


async def _list_files(repo: Path, ignore: list[str] | None = None) -> list[str]:
    rc, stdout, _ = await arun(["git", "ls-files"], cwd=repo, timeout=10)
    if rc != 0:
        return []
    files = stdout.strip().splitlines()
    if ignore:
        files = [f for f in files if not _is_ignored(f, ignore)]
    return files[:MAX_FILE_LIST]


def _top_level_dirs(repo: Path) -> list[str]:
    return sorted(d.name for d in repo.iterdir() if d.is_dir() and not d.name.startswith("."))


async def _recent_commits(repo: Path, n: int = 15) -> list[str]:
    rc, stdout, _ = await arun(["git", "log", f"-{n}", "--oneline"], cwd=repo, timeout=10)
    if rc == 0:
        return stdout.strip().splitlines()
    return []


def _read_package_manifest(repo: Path, language: str) -> str:
    manifests = {
        "python": "pyproject.toml",
        "javascript": "package.json",
        "typescript": "package.json",
        "rust": "Cargo.toml",
        "go": "go.mod",
    }
    manifest = manifests.get(language)
    if manifest:
        return read_truncated(repo / manifest)
    return ""


def _should_skip(path: str) -> bool:
    parts = Path(path).parts
    return any(p in SKIP_DIRS for p in parts)


def _is_already_read(path: str) -> bool:
    p = Path(path)
    return p.name in ALREADY_READ_FILENAMES and len(p.parts) == 1


def _is_binary(path: str) -> bool:
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


def _is_ignored(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, p) for p in patterns)


def _source_budget(model: str) -> int:
    context_window = get_context_window(model)
    usable = context_window - PROMPT_OVERHEAD_TOKENS - RESPONSE_RESERVE_TOKENS
    return max(usable * CHARS_PER_TOKEN, 20_000)


def _summarize_source_files(
    repo: Path,
    files: list[str],
    budget: int,
    *,
    ignore: list[str] | None = None,
    on_status: StatusCallback | None = None,
) -> str:
    source_files = [
        f
        for f in files
        if not _is_binary(f)
        and not _should_skip(f)
        and not _is_already_read(f)
        and not (ignore and _is_ignored(f, ignore))
    ]

    chunks: list[str] = []
    total_chars = 0

    for filepath in source_files:
        if total_chars >= budget:
            remaining = len(source_files) - len(chunks)
            chunks.append(f"\n... ({remaining} more files not shown, context budget reached)")
            break

        full_path = repo / filepath
        if not full_path.exists():
            continue

        if on_status:
            on_status(f"Reading {filepath}...")

        try:
            content = full_path.read_text(errors="replace")
        except OSError:
            continue

        chunk = f"\n--- {filepath} ---\n{content}"

        budget_left = budget - total_chars
        if len(chunk) > budget_left:
            chunk = chunk[:budget_left] + "\n... (truncated, budget limit)"

        chunks.append(chunk)
        total_chars += len(chunk)

    return "".join(chunks)


@dataclass(frozen=True)
class TestInfrastructureReport:
    has_tests: bool
    has_ci_for_tests: bool
    language: str
    test_dirs_found: list[str]
    test_config_found: bool
    suggested_framework: str
    suggested_test_dir: str
    sample_function_file: str
    sample_function_name: str


@dataclass
class DiscoveryData:
    name: str = ""
    language: str = "unknown"
    ci: str | None = None
    dirs: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    readme: str = ""
    manifest: str = ""
    commits: list[str] = field(default_factory=list)
    source_text: str = ""
    repo_path: Path = field(default_factory=lambda: Path("."))
    ignore: list[str] = field(default_factory=list)

    @property
    def metadata_context(self) -> str:
        return "\n".join(
            [
                f"Name: {self.name}",
                f"Language: {self.language}",
                f"CI: {self.ci or 'none detected'}",
                f"Top-level dirs: {', '.join(self.dirs) or 'none'}",
                f"File count: {len(self.files)}",
                f"\nFiles:\n{chr(10).join(self.files)}",
                f"\nREADME:\n{self.readme or '(no README found)'}",
                f"\nPackage manifest:\n{self.manifest or '(no manifest found)'}",
                f"\nRecent commits:\n{chr(10).join(self.commits) or '(no commits)'}",
            ]
        )

    def to_context(self) -> str:
        return (
            self.metadata_context
            + f"\n\nSource files:\n{self.source_text or '(no source files found)'}"
        )

    def read_source_files(
        self,
        budget: int,
        *,
        priority_files: list[str] | None = None,
        on_status: StatusCallback | None = None,
    ) -> str:
        ordered_files = list(self.files)
        if priority_files:
            files_set = set(ordered_files)
            priority_set = set(priority_files)
            front = [f for f in priority_files if f in files_set]
            rest = [f for f in ordered_files if f not in priority_set]
            ordered_files = front + rest
        return _summarize_source_files(
            self.repo_path, ordered_files, budget, ignore=self.ignore or None, on_status=on_status
        )


async def discover(
    repo: Path,
    model: str,
    *,
    ignore: list[str] | None = None,
    on_status: StatusCallback | None = None,
) -> DiscoveryData:
    language = _detect_language(repo)
    ci = _detect_ci(repo)
    dirs = _top_level_dirs(repo)

    if on_status:
        on_status("Listing files and reading git log...")
    files, commits = await asyncio.gather(_list_files(repo, ignore=ignore), _recent_commits(repo))

    if on_status:
        on_status("Reading README and manifest...")
    readme = read_truncated(repo / "README.md")
    manifest = _read_package_manifest(repo, language)
    budget = _source_budget(model)
    source_text = _summarize_source_files(repo, files, budget, ignore=ignore, on_status=on_status)

    return DiscoveryData(
        name=repo.resolve().name,
        language=language,
        ci=ci,
        dirs=dirs,
        files=files,
        readme=readme,
        manifest=manifest,
        commits=commits,
        source_text=source_text,
        repo_path=repo,
        ignore=ignore or [],
    )


def _ci_runs_tests(repo: Path) -> bool:
    workflows_dir = repo / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return False
    for wf_file in workflows_dir.iterdir():
        if not wf_file.is_file():
            continue
        try:
            content = wf_file.read_text(errors="replace")
        except OSError:
            continue
        for line in content.lower().splitlines():
            stripped = line.strip()
            if any(cmd in stripped for cmd in CI_TEST_COMMANDS):
                return True
    return False


def _has_test_dirs(repo: Path) -> list[str]:
    found: list[str] = []
    for d in repo.iterdir():
        if d.is_dir() and d.name in TEST_DIR_NAMES:
            found.append(d.name)
    return found


def _has_test_files(repo: Path, files: list[str], language: str) -> bool:
    patterns = TEST_FILE_PATTERNS.get(language, set())
    for f in files:
        name = Path(f).name.lower()
        for pat in patterns:
            if pat in name:
                return True
    return False


def _has_test_config(repo: Path, language: str) -> bool:
    frameworks = TEST_FRAMEWORKS.get(language, set())
    if language in ("python",):
        try:
            content = (repo / "pyproject.toml").read_text(errors="replace")
        except OSError:
            content = ""
        for fw in frameworks:
            if fw in content:
                return True
    if language in ("javascript", "typescript"):
        try:
            content = (repo / "package.json").read_text(errors="replace")
        except OSError:
            content = ""
        for fw in frameworks:
            if fw in content:
                return True
    return False


def _suggest_framework(language: str) -> str:
    defaults = {
        "python": "pytest",
        "javascript": "jest",
        "typescript": "jest",
        "rust": "cargo test",
        "go": "go test",
        "ruby": "rspec",
        "java": "junit",
    }
    return defaults.get(language, "language-appropriate test framework")


def _suggest_test_dir(discovery_data: DiscoveryData) -> str:
    if "src" in discovery_data.dirs or "pkg" in discovery_data.dirs:
        return "tests/"
    if discovery_data.language == "go":
        return "(same package, _test.go files)"
    return "tests/"


def _find_simple_function(
    repo: Path, files: list[str], language: str
) -> tuple[str, str] | None:
    source_exts = {
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "rust": ".rs",
        "go": ".go",
    }
    ext = source_exts.get(language)
    if not ext:
        return None

    for filepath in files:
        if not filepath.endswith(ext):
            continue
        if filepath.startswith(("test_", "tests/", "spec/", "__tests__/")):
            continue
        if "_test" in filepath:
            continue
        try:
            content = (repo / filepath).read_text(errors="replace")
        except OSError:
            continue
        result = _extract_simple_function(content, filepath, language)
        if result:
            return result
    return None


def _extract_simple_function(
    content: str, filepath: str, language: str
) -> tuple[str, str] | None:
    if language == "python":
        return _extract_python_function(content, filepath)
    if language in ("javascript", "typescript"):
        return _extract_js_function(content, filepath)
    if language == "rust":
        return _extract_rust_function(content, filepath)
    if language == "go":
        return _extract_go_function(content, filepath)
    return None


def _extract_python_function(content: str, filepath: str) -> tuple[str, str] | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("def ") and "self" not in stripped and "cls" not in stripped:
            name = stripped[4:].split("(")[0].strip()
            if name.startswith("_"):
                continue
            return (filepath, name)
    return None


def _extract_js_function(content: str, filepath: str) -> tuple[str, str] | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("export function ") or stripped.startswith("function "):
            prefix = "export function " if stripped.startswith("export function ") else "function "
            name = stripped[len(prefix) :].split("(")[0].strip()
            if name.startswith("_"):
                continue
            return (filepath, name)
    return None


def _extract_rust_function(content: str, filepath: str) -> tuple[str, str] | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("pub fn "):
            name = stripped[7:].split("(")[0].strip()
            return (filepath, name)
    return None


def _extract_go_function(content: str, filepath: str) -> tuple[str, str] | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("func ") and not stripped.startswith("func ("):
            name = stripped[5:].split("(")[0].strip()
            if name[:1].isupper():
                return (filepath, name)
    return None


def detect_test_infrastructure(repo: Path, discovery_data: DiscoveryData) -> TestInfrastructureReport:
    language = discovery_data.language
    test_dirs = _has_test_dirs(repo)
    test_config = _has_test_config(repo, language)
    has_test_files = _has_test_files(repo, discovery_data.files, language)
    has_tests = bool(test_dirs) or test_config or has_test_files
    has_ci_for_tests = _ci_runs_tests(repo) if has_tests else False
    suggested_framework = _suggest_framework(language)
    suggested_test_dir = _suggest_test_dir(discovery_data)
    simple_fn = _find_simple_function(repo, discovery_data.files, language)
    sample_function_file = simple_fn[0] if simple_fn else ""
    sample_function_name = simple_fn[1] if simple_fn else ""

    return TestInfrastructureReport(
        has_tests=has_tests,
        has_ci_for_tests=has_ci_for_tests,
        language=language,
        test_dirs_found=test_dirs,
        test_config_found=test_config,
        suggested_framework=suggested_framework,
        suggested_test_dir=suggested_test_dir,
        sample_function_file=sample_function_file,
        sample_function_name=sample_function_name,
    )


def build_test_infrastructure_finding(
    report: TestInfrastructureReport, discovery_data: DiscoveryData
) -> Finding | None:
    if report.has_tests and report.has_ci_for_tests:
        return None

    from sigil.pipeline.models import Finding

    if not report.has_tests:
        description = _build_no_tests_description(report, discovery_data)
        suggested_fix = f"Set up {report.suggested_framework} and add a tests/ directory"
    else:
        description = _build_no_ci_tests_description(report, discovery_data)
        suggested_fix = "Add test execution to your CI workflow"

    return Finding(
        category="test-infrastructure",
        file=".",
        line=None,
        description=description,
        risk="medium",
        suggested_fix=suggested_fix,
        disposition="issue",
        priority=5,
        rationale="Tests are essential for code quality and preventing regressions",
    )


def _build_no_tests_description(
    report: TestInfrastructureReport, discovery_data: DiscoveryData
) -> str:
    parts = [
        "This repository has no test infrastructure detected.",
        "",
        f"**Language:** {report.language}",
        f"**Recommended framework:** {report.suggested_framework}",
        f"**Suggested test directory:** {report.suggested_test_dir}",
        "",
    ]

    if report.sample_function_file and report.sample_function_name:
        parts.extend(
            [
                "## Sample Test",
                f"Here is a sample test for `{report.sample_function_name}` in `{report.sample_function_file}`:",
                "",
                _sample_test_code(report, discovery_data),
                "",
            ]
        )

    parts.extend(
        [
            "## Suggested Directory Structure",
            _suggested_structure(report, discovery_data),
            "",
            "## CI Integration",
            _ci_suggestion(report, discovery_data),
        ]
    )

    return "\n".join(parts)


def _build_no_ci_tests_description(
    report: TestInfrastructureReport, discovery_data: DiscoveryData
) -> str:
    return (
        "This repository has tests but they are not run in CI.\n"
        "\n"
        "Detected test directories: " + ", ".join(report.test_dirs_found) + "\n"
        "\n"
        "## CI Integration\n"
        + _ci_suggestion(report, discovery_data)
    )


def _sample_test_code(report: TestInfrastructureReport, discovery_data: DiscoveryData) -> str:
    lang = report.language
    fn_name = report.sample_function_name
    if lang == "python":
        return (
            f"```python\n"
            f"from {Path(report.sample_function_file).stem} import {fn_name}\n"
            f"\n"
            f"\ndef test_{fn_name}():\n"
            f"    result = {fn_name}()\n"
            f"    assert result is not None\n"
            f"```"
        )
    if lang in ("javascript", "typescript"):
        ext = ".ts" if lang == "typescript" else ".js"
        return (
            f"```{lang}\n"
            f"import {{ {fn_name} }} from '../{Path(report.sample_function_file).stem}'\n"
            f"\n"
            f"test('{fn_name} works', () => {{\n"
            f"  expect({fn_name}()).toBeDefined()\n"
            f"}})\n"
            f"```"
        )
    if lang == "rust":
        return (
            f"```rust\n"
            f"#[cfg(test)]\n"
            f"mod tests {{\n"
            f"    use super::*;\n"
            f"\n"
            f"    #[test]\n"
            f"    fn test_{fn_name}() {{\n"
            f"        assert!({fn_name}().is_some());\n"
            f"    }}\n"
            f"}}\n"
            f"```"
        )
    if lang == "go":
        return (
            f"```go\n"
            f"func Test{fn_name[:1].upper() + fn_name[1:]}(t *testing.T) {{\n"
            f"    result := {fn_name}()\n"
            f"    if result == nil {{\n"
            f"        t.Error('expected non-nil result')\n"
            f"    }}\n"
            f"}}\n"
            f"```"
        )
    return f"Add a test for `{fn_name}` using {report.suggested_framework}."


def _suggested_structure(
    report: TestInfrastructureReport, discovery_data: DiscoveryData
) -> str:
    lang = report.language
    test_dir = report.suggested_test_dir
    if lang == "python":
        return (
            f"```\n"
            f"{test_dir}\n"
            f"├── __init__.py\n"
            f"├── conftest.py\n"
            f"└── test_{Path(report.sample_function_file).stem}.py\n"
            f"```"
        )
    if lang in ("javascript", "typescript"):
        return (
            f"```\n"
            f"{test_dir}\n"
            f"├── {Path(report.sample_function_file).stem}.test.{'ts' if lang == 'typescript' else 'js'}\n"
            f"└── setup.ts\n"
            f"```"
        )
    if lang == "rust":
        return "```tests are typically in the same file under #[cfg(test)] or in a tests/ directory```"
    if lang == "go":
        return "```test files are placed alongside source files as *_test.go```"
    return f"```\n{test_dir}\n```"


def _ci_suggestion(report: TestInfrastructureReport, discovery_data: DiscoveryData) -> str:
    lang = report.language
    ci = discovery_data.ci
    if ci == "github_actions":
        if lang == "python":
            return (
                "```yaml\n"
                "# .github/workflows/test.yml\n"
                "name: Tests\n"
                "on: [push, pull_request]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-python@v5\n"
                "        with:\n"
                "          python-version: '3.11'\n"
                "      - run: pip install -e '.[dev]'\n"
                "      - run: pytest\n"
                "```"
            )
        if lang in ("javascript", "typescript"):
            return (
                "```yaml\n"
                "# .github/workflows/test.yml\n"
                "name: Tests\n"
                "on: [push, pull_request]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-node@v4\n"
                "        with:\n"
                "          node-version: '20'\n"
                "      - run: npm ci\n"
                "      - run: npm test\n"
                "```"
            )
        if lang == "rust":
            return (
                "```yaml\n"
                "# .github/workflows/test.yml\n"
                "name: Tests\n"
                "on: [push, pull_request]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - run: cargo test\n"
                "```"
            )
        if lang == "go":
            return (
                "```yaml\n"
                "# .github/workflows/test.yml\n"
                "name: Tests\n"
                "on: [push, pull_request]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-go@v5\n"
                "        with:\n"
                "          go-version: '1.22'\n"
                "      - run: go test ./...\n"
                "```"
            )
        return (
            "```yaml\n"
            "# .github/workflows/test.yml\n"
            "name: Tests\n"
            "on: [push, pull_request]\n"
            "jobs:\n"
            "  test:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - run: make test\n"
            "```"
        )
    if ci is None:
        return "Consider setting up GitHub Actions or another CI provider to run tests automatically on push and pull requests."
    return f"Add a test step to your existing {ci} configuration using `{report.suggested_framework}`."
