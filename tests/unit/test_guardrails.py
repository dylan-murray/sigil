from sigil.core.config import Config
from sigil.pipeline.guardrails import check_complexity, filter_complexity
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding


def _finding(**overrides) -> Finding:
    defaults = {
        "category": "dead_code",
        "file": "utils.py",
        "line": 10,
        "description": "Unused function",
        "risk": "low",
        "suggested_fix": "Remove it",
        "disposition": "pr",
        "priority": 1,
        "rationale": "Dead code",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _idea(**overrides) -> FeatureIdea:
    defaults = {
        "title": "Add Caching Layer",
        "description": "Cache API responses",
        "rationale": "Reduce latency",
        "complexity": "small",
        "disposition": "pr",
        "priority": 1,
    }
    defaults.update(overrides)
    return FeatureIdea(**defaults)


class TestCheckComplexity:
    def test_no_spec_few_files_proceeds(self):
        item = _finding(implementation_spec="", relevant_files=("a.py", "b.py"))
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "proceed"
        assert verdict.reason == ""

    def test_persistence_keyword_in_spec_downgrades(self):
        item = _finding(
            implementation_spec="Add a persistent state tracker for veto memory",
            relevant_files=("a.py",),
        )
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "downgrade"
        assert "persist" in verdict.reason.lower()
        assert "cross-session persistence" in verdict.reason

    def test_database_keyword_downgrades(self):
        item = _idea(
            implementation_spec="Store results in sqlite for caching",
            relevant_files=("a.py",),
        )
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "downgrade"
        assert "sqlite" in verdict.reason.lower()

    def test_too_many_files_downgrades(self):
        item = _finding(
            implementation_spec="Simple fix",
            relevant_files=("a.py", "b.py", "c.py", "d.py"),
        )
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "downgrade"
        assert "4 files" in verdict.reason
        assert "threshold: 3" in verdict.reason

    def test_keyword_takes_priority_over_file_count(self):
        item = _idea(
            implementation_spec="Use redis for cross-session state tracking",
            relevant_files=("a.py", "b.py", "c.py", "d.py"),
        )
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "downgrade"
        assert "cross-session persistence" in verdict.reason

    def test_exact_file_count_passes(self):
        item = _finding(
            implementation_spec="Simple fix",
            relevant_files=("a.py", "b.py", "c.py"),
        )
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "proceed"

    def test_case_insensitive_keyword_match(self):
        item = _finding(
            implementation_spec="Implement PERSIST storage mechanism",
            relevant_files=("a.py",),
        )
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "downgrade"

    def test_empty_spec_empty_files_proceeds(self):
        item = _finding(implementation_spec="", relevant_files=())
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "proceed"

    def test_cross_run_keyword(self):
        item = _idea(
            implementation_spec="Track state across_run invocations",
            relevant_files=("a.py",),
        )
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "downgrade"
        assert "cross_run" in verdict.reason

    def test_cross_run_hyphen_keyword(self):
        item = _idea(
            implementation_spec="Persist data cross-run",
            relevant_files=("a.py",),
        )
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "downgrade"
        assert "cross-session persistence" in verdict.reason

    def test_state_management_keyword(self):
        item = _idea(
            implementation_spec="Add state management for tracking vetoes",
            relevant_files=("a.py",),
        )
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "downgrade"
        assert "state management" in verdict.reason.lower()

    def test_custom_max_files(self):
        item = _finding(
            implementation_spec="Simple fix",
            relevant_files=("a.py", "b.py", "c.py", "d.py", "e.py"),
        )
        verdict = check_complexity(item, max_files=5)
        assert verdict.action == "proceed"

    def test_leveldb_keyword(self):
        item = _idea(
            implementation_spec="Use leveldb for local storage",
            relevant_files=("a.py",),
        )
        verdict = check_complexity(item, max_files=3)
        assert verdict.action == "downgrade"
        assert "leveldb" in verdict.reason.lower()


class TestFilterComplexity:
    def test_all_items_pass(self):
        items = [
            _finding(implementation_spec="Fix typo", relevant_files=("a.py",)),
            _idea(implementation_spec="Add docstring", relevant_files=("b.py",)),
        ]
        config = Config()
        execute, issues, skipped = filter_complexity(items, [], config)
        assert len(execute) == 2
        assert len(issues) == 0
        assert len(skipped) == 0

    def test_some_items_downgraded(self):
        good = _finding(implementation_spec="Fix typo", relevant_files=("a.py",))
        bad = _idea(
            implementation_spec="Add persistent state tracking",
            relevant_files=("a.py", "b.py", "c.py", "d.py"),
        )
        config = Config()
        execute, issues, skipped = filter_complexity([good, bad], [], config)
        assert len(execute) == 1
        assert len(issues) == 1
        assert len(skipped) == 0
        assert issues[0] is bad

    def test_existing_issues_preserved(self):
        existing_issue = _finding(disposition="issue", implementation_spec="", relevant_files=())
        pr_item = _finding(implementation_spec="Fix typo", relevant_files=("a.py",))
        config = Config()
        execute, issues, skipped = filter_complexity([pr_item], [existing_issue], config)
        assert len(execute) == 1
        assert len(issues) == 1
        assert issues[0] is existing_issue

    def test_empty_input(self):
        config = Config()
        execute, issues, skipped = filter_complexity([], [], config)
        assert execute == []
        assert issues == []
        assert skipped == []

    def test_custom_max_files_from_config(self):
        item = _finding(
            implementation_spec="Simple fix",
            relevant_files=("a.py", "b.py", "c.py", "d.py"),
        )
        config = Config(complexity_max_files=5)
        execute, issues, skipped = filter_complexity([item], [], config)
        assert len(execute) == 1

    def test_default_max_files_is_3(self):
        item = _finding(
            implementation_spec="Simple fix",
            relevant_files=("a.py", "b.py", "c.py", "d.py"),
        )
        config = Config()
        execute, issues, skipped = filter_complexity([item], [], config)
        assert len(execute) == 0
        assert len(issues) == 1

    def test_downgraded_items_go_to_issues(self):
        bad = _idea(
            implementation_spec="Add persistent database storage",
            relevant_files=("a.py", "b.py", "c.py", "d.py"),
        )
        config = Config()
        execute, issues, skipped = filter_complexity([bad], [], config)
        assert len(issues) == 1
        assert issues[0] is bad
        assert len(skipped) == 0

    def test_mixed_pass_and_downgrade(self):
        good = _finding(implementation_spec="Fix typo", relevant_files=("a.py",))
        bad_keyword = _idea(
            implementation_spec="Use redis for caching",
            relevant_files=("a.py",),
        )
        bad_files = _finding(
            implementation_spec="Refactor module",
            relevant_files=("a.py", "b.py", "c.py", "d.py"),
        )
        config = Config()
        execute, issues, skipped = filter_complexity([good, bad_keyword, bad_files], [], config)
        assert len(execute) == 1
        assert execute[0] is good
        assert len(issues) == 2
        assert len(skipped) == 0
