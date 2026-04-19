from sigil.pipeline.health import compute_health, HealthMetrics, HealthDashboard


def test_compute_health_empty_repo(tmp_path):
    # Setup a minimal repo structure
    (tmp_path / "sigil").mkdir(parents=True)
    (tmp_path / "sigil" / "main.py").write_text("def hello():\n    print('hi')")

    metrics = compute_health(tmp_path)

    assert isinstance(metrics, HealthMetrics)
    assert metrics.open_findings == 0
    assert metrics.type_coverage == 0.0
    assert metrics.test_coverage == 0.0
    assert metrics.dependency_health == 0
    assert metrics.pr_success_rate == 0.0


def test_compute_health_with_artifacts(tmp_path):
    # Setup repo with artifacts
    (tmp_path / "sigil").mkdir(parents=True)
    (tmp_path / "sigil" / "main.py").write_text(
        "def hello(name: str) -> str:\n    return f'hi {name}'"
    )

    # Memory
    memory_dir = tmp_path / ".sigil" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "findings.md").write_text(
        "finding 1: disposition: issue\nfinding 2: disposition: unreviewed"
    )

    # Dependencies
    deps_dir = tmp_path / ".sigil" / "dependencies"
    deps_dir.mkdir(parents=True)
    (deps_dir / "deps.json").write_text('{"outdated": 2, "vulnerable": 1}')

    # Outcomes
    outcomes_dir = tmp_path / ".sigil" / "outcomes"
    outcomes_dir.mkdir(parents=True)
    (outcomes_dir / "pr1.json").write_text('{"status": "merged"}')
    (outcomes_dir / "pr2.json").write_text('{"status": "closed"}')

    # Tests
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_sigil_main.py").write_text("def test_hello(): pass")

    metrics = compute_health(tmp_path)

    assert metrics.open_findings == 2
    assert metrics.type_coverage == 1.0
    assert metrics.test_coverage == 1.0
    assert metrics.dependency_health < 100
    assert metrics.pr_success_rate == 0.5


def test_health_dashboard_rendering():
    metrics = HealthMetrics(
        open_findings=5,
        type_coverage=0.8,
        test_coverage=0.7,
        dependency_health=90,
        pr_success_rate=0.9,
        knowledge_staleness=2,
        status="healthy",
    )
    dashboard = HealthDashboard(metrics)

    render = dashboard.render()
    assert "Open Findings" in str(render)
    assert "80.0%" in str(render)

    json_out = dashboard.export_json()
    assert '"open_findings": 5' in json_out

    csv_out = dashboard.export_csv()
    assert "open_findings,5" in csv_out
