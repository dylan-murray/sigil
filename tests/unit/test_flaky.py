import pytest

from sigil.pipeline.flaky import _is_test_file, _scan_file, detect_flaky_patterns
from sigil.pipeline.models import Finding


def _write_file(repo, path, content):
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


class TestIsTestFile:
    @pytest.mark.parametrize(
        "path",
        [
            "tests/test_foo.py",
            "tests/unit/test_bar.py",
            "tests/integration/test_baz.py",
            "src/test_thing.py",
            "app/test_handler.py",
            "pkg/test_inner_test.py",
            "project/whatever_test.py",
        ],
    )
    def test_identifies_test_files(self, path):
        assert _is_test_file(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "src/app.py",
            "lib/utils.py",
            "README.md",
            "setup.py",
            "conftest.py",
            "tests/conftest.py",
            "tests/__init__.py",
            "tests/fixtures/data.py",
        ],
    )
    def test_rejects_non_test_files(self, path):
        assert _is_test_file(path) is False


class TestScanFileTimeSleep:
    def test_time_sleep_detected(self):
        content = "import time\ntime.sleep(2)\nresult = do_thing()\n"
        findings = _scan_file(content, "tests/test_slow.py")
        assert len(findings) == 1
        f = findings[0]
        assert f.category == "flaky_test"
        assert f.file == "tests/test_slow.py"
        assert f.line == 2
        assert "time.sleep" in f.description
        assert f.disposition == "pr"

    def test_time_sleep_with_mock_not_detected(self):
        content = "from unittest.mock import patch\nwith patch('time.sleep'):\n    time.sleep(2)\n"
        findings = _scan_file(content, "tests/test_mocked.py")
        assert all("time.sleep" not in f.description for f in findings)

    def test_time_sleep_with_monkeypatch_not_detected(self):
        content = (
            "def test_wait(monkeypatch):\n"
            "    monkeypatch.setattr('time.sleep', lambda s: None)\n"
            "    time.sleep(2)\n"
        )
        findings = _scan_file(content, "tests/test_mp.py")
        assert all("time.sleep" not in f.description for f in findings)

    def test_non_test_file_skipped(self):
        content = "import time\ntime.sleep(2)\n"
        findings = _scan_file(content, "src/app.py")
        assert findings == []


class TestScanFileRandom:
    def test_random_usage_detected(self):
        content = "import random\nx = random.randint(1, 100)\n"
        findings = _scan_file(content, "tests/test_rand.py")
        assert len(findings) == 1
        assert "random" in findings[0].description
        assert findings[0].disposition == "pr"

    def test_random_with_seed_not_detected(self):
        content = "import random\nrandom.seed(42)\nx = random.randint(1, 100)\n"
        findings = _scan_file(content, "tests/test_seeded.py")
        assert all("random" not in f.description for f in findings)

    def test_random_choice_detected(self):
        content = "import random\nitem = random.choice([1, 2, 3])\n"
        findings = _scan_file(content, "tests/test_choice.py")
        assert len(findings) == 1
        assert "random" in findings[0].description

    def test_random_with_parametrize_not_detected(self):
        content = (
            "@pytest.mark.parametrize('x', [1, 2])\ndef test_rand(x):\n    random.randint(1, 100)\n"
        )
        findings = _scan_file(content, "tests/test_param.py")
        assert all("random" not in f.description for f in findings)


class TestScanFileUnorderedCollections:
    def test_set_comparison_detected(self):
        content = "assert set(result) == {1, 2, 3}\n"
        findings = _scan_file(content, "tests/test_set.py")
        assert len(findings) == 1
        assert (
            "unordered" in findings[0].description.lower()
            or "set" in findings[0].description.lower()
        )

    def test_dict_comparison_detected(self):
        content = "assert result == {'a': 1, 'b': 2}\n"
        findings = _scan_file(content, "tests/test_dict.py")
        assert len(findings) == 1

    def test_sorted_assertion_not_detected(self):
        content = "assert sorted(result) == [1, 2, 3]\n"
        findings = _scan_file(content, "tests/test_sorted.py")
        assert all("unordered" not in f.description.lower() for f in findings)


class TestScanFileDatetime:
    def test_datetime_now_detected(self):
        content = "from datetime import datetime\nnow = datetime.now()\nassert result == now\n"
        findings = _scan_file(content, "tests/test_time.py")
        assert len(findings) == 1
        assert "datetime" in findings[0].description.lower()
        assert findings[0].disposition == "pr"

    def test_datetime_utcnow_detected(self):
        content = "from datetime import datetime\nnow = datetime.utcnow()\n"
        findings = _scan_file(content, "tests/test_utc.py")
        assert len(findings) == 1
        assert "datetime" in findings[0].description.lower()

    def test_freezegun_not_detected(self):
        content = (
            "from freezegun import freeze_time\n"
            "with freeze_time('2024-01-01'):\n"
            "    now = datetime.now()\n"
        )
        findings = _scan_file(content, "tests/test_frozen.py")
        assert all("datetime" not in f.description.lower() for f in findings)

    def test_monkeypatch_not_detected(self):
        content = (
            "def test_time(monkeypatch):\n"
            "    monkeypatch.setattr('datetime.datetime.now', lambda: fixed_time)\n"
            "    now = datetime.now()\n"
        )
        findings = _scan_file(content, "tests/test_mp_time.py")
        assert all("datetime" not in f.description.lower() for f in findings)


class TestScanFileOsEnviron:
    def test_os_environ_set_detected(self):
        content = "import os\nos.environ['KEY'] = 'value'\n"
        findings = _scan_file(content, "tests/test_env.py")
        assert len(findings) == 1
        assert "os.environ" in findings[0].description
        assert findings[0].disposition == "issue"

    def test_os_environ_update_detected(self):
        content = "import os\nos.environ.update({'KEY': 'value'})\n"
        findings = _scan_file(content, "tests/test_env_update.py")
        assert len(findings) == 1
        assert "os.environ" in findings[0].description

    def test_os_environ_del_detected(self):
        content = "import os\ndel os.environ['KEY']\n"
        findings = _scan_file(content, "tests/test_env_del.py")
        assert len(findings) == 1
        assert "os.environ" in findings[0].description

    def test_monkeypatch_setenv_not_detected(self):
        content = "def test_env(monkeypatch):\n    monkeypatch.setenv('KEY', 'value')\n"
        findings = _scan_file(content, "tests/test_mp_env.py")
        assert all("os.environ" not in f.description for f in findings)

    def test_context_manager_not_detected(self):
        content = (
            "from unittest.mock import patch\n"
            "with patch.dict(os.environ, {'KEY': 'value'}):\n"
            "    do_thing()\n"
        )
        findings = _scan_file(content, "tests/test_ctx_env.py")
        assert all("os.environ" not in f.description for f in findings)

    def test_os_environ_pop_not_detected(self):
        content = "import os\nos.environ.pop('KEY', None)\n"
        findings = _scan_file(content, "tests/test_env_pop.py")
        assert all("os.environ" not in f.description for f in findings)


class TestDetectFlakyPatterns:
    def test_detects_time_sleep_in_test_file(self, tmp_path):
        _write_file(tmp_path, "tests/test_slow.py", "import time\ntime.sleep(5)\n")
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) == 1
        assert findings[0].category == "flaky_test"
        assert findings[0].file == "tests/test_slow.py"
        assert findings[0].line == 2

    def test_skips_non_test_files(self, tmp_path):
        _write_file(tmp_path, "src/app.py", "import time\ntime.sleep(5)\n")
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) == 0

    def test_empty_repo(self, tmp_path):
        findings = detect_flaky_patterns(tmp_path)
        assert findings == []

    def test_multiple_patterns_same_file(self, tmp_path):
        content = (
            "import time\n"
            "import random\n"
            "import os\n"
            "from datetime import datetime\n"
            "\n"
            "time.sleep(1)\n"
            "random.choice([1, 2])\n"
            "os.environ['KEY'] = 'val'\n"
            "now = datetime.now()\n"
        )
        _write_file(tmp_path, "tests/test_flaky.py", content)
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) >= 3
        descriptions = {f.description for f in findings}
        assert any("time.sleep" in d for d in descriptions)
        assert any("random" in d for d in descriptions)
        assert any("os.environ" in d for d in descriptions)

    def test_respects_ignore_patterns(self, tmp_path):
        _write_file(tmp_path, "tests/test_slow.py", "import time\ntime.sleep(5)\n")
        findings = detect_flaky_patterns(tmp_path, ignore=["tests/**"])
        assert len(findings) == 0

    def test_finding_has_correct_fields(self, tmp_path):
        _write_file(tmp_path, "tests/test_env.py", "import os\nos.environ['KEY'] = 'val'\n")
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) == 1
        f = findings[0]
        assert isinstance(f, Finding)
        assert f.category == "flaky_test"
        assert f.risk in ("low", "medium", "high")
        assert f.disposition in ("pr", "issue")
        assert f.priority >= 1
        assert f.suggested_fix
        assert f.rationale

    def test_nested_test_dir(self, tmp_path):
        _write_file(tmp_path, "tests/unit/test_utils.py", "import time\ntime.sleep(2)\n")
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) == 1
        assert findings[0].file == "tests/unit/test_utils.py"

    def test_test_prefix_file(self, tmp_path):
        _write_file(tmp_path, "test_main.py", "import random\nrandom.randint(1, 10)\n")
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) == 1
        assert findings[0].file == "test_main.py"

    def test_set_comparison_in_test(self, tmp_path):
        content = "def test_set():\n    assert set(result) == {1, 2, 3}\n"
        _write_file(tmp_path, "tests/test_set.py", content)
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) >= 1
        assert any(
            "unordered" in f.description.lower() or "set" in f.description.lower() for f in findings
        )

    def test_skips_git_dir(self, tmp_path):
        _write_file(tmp_path, ".git/refs/test_x.py", "import time\ntime.sleep(1)\n")
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) == 0

    def test_skips_venv_dir(self, tmp_path):
        _write_file(tmp_path, ".venv/lib/test_x.py", "import time\ntime.sleep(1)\n")
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) == 0

    def test_os_environ_disposition_is_issue(self, tmp_path):
        _write_file(tmp_path, "tests/test_env.py", "import os\nos.environ['KEY'] = 'val'\n")
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) == 1
        assert findings[0].disposition == "issue"

    def test_datetime_now_disposition_is_pr(self, tmp_path):
        content = "from datetime import datetime\nnow = datetime.now()\n"
        _write_file(tmp_path, "tests/test_time.py", content)
        findings = detect_flaky_patterns(tmp_path)
        assert len(findings) == 1
        assert findings[0].disposition == "pr"

    def test_priorities_are_sequential(self, tmp_path):
        content = "import time\nimport random\ntime.sleep(1)\nrandom.randint(1, 10)\n"
        _write_file(tmp_path, "tests/test_multi.py", content)
        findings = detect_flaky_patterns(tmp_path)
        priorities = [f.priority for f in findings]
        assert priorities == sorted(priorities)
        assert len(set(priorities)) == len(priorities)
