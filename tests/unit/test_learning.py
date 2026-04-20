from sigil.core.learning import OutcomeTracker, LearningEngine


def test_outcome_tracker_persistence(tmp_path):
    repo = tmp_path
    tracker = OutcomeTracker(repo)

    tracker.record_outcome(123, "dead_code", True, feedback="Merged quickly")
    assert 123 in tracker.outcomes

    # Create new tracker to test loading
    tracker2 = OutcomeTracker(repo)
    assert 123 in tracker2.outcomes
    assert tracker2.outcomes[123].category == "dead_code"
    assert tracker2.outcomes[123].merged is True


def test_learning_engine_success_rates(tmp_path):
    repo = tmp_path
    tracker = OutcomeTracker(repo)
    tracker.record_outcome(1, "security", True)
    tracker.record_outcome(2, "security", True)
    tracker.record_outcome(3, "security", False)
    tracker.record_outcome(4, "style", False)

    engine = LearningEngine(tracker)
    assert engine.get_success_rate("security") == 2 / 3
    assert engine.get_success_rate("style") == 0.0
    assert engine.get_success_rate("unknown") == 0.0


def test_learning_engine_guidance(tmp_path):
    repo = tmp_path
    tracker = OutcomeTracker(repo)

    # High success category
    tracker.record_outcome(1, "type_fix", True)
    tracker.record_outcome(2, "type_fix", True)
    tracker.record_outcome(3, "type_fix", True)
    tracker.record_outcome(4, "type_fix", True)
    tracker.record_outcome(5, "type_fix", True)

    # Low success category
    tracker.record_outcome(6, "refactor", False, feedback="Too complex")
    tracker.record_outcome(7, "refactor", False, feedback="Broke tests")
    tracker.record_outcome(8, "refactor", False, feedback="Out of scope")
    tracker.record_outcome(9, "refactor", False, feedback="Wrong approach")
    tracker.record_outcome(10, "refactor", True)

    engine = LearningEngine(tracker)
    guidance = engine.get_prompt_guidance()

    assert "type_fix: High success rate" in guidance
    assert "refactor: Low success rate" in guidance
    assert "Too complex" in guidance or "Broke tests" in guidance


def test_learning_engine_empty_history(tmp_path):
    repo = tmp_path
    tracker = OutcomeTracker(repo)
    engine = LearningEngine(tracker)
    assert engine.get_prompt_guidance() == "No historical outcome data available."
