from sigil.core.blueprint import (
    build_blueprint,
    store_blueprint,
    load_blueprint,
    ensure_blueprint,
    summarize_blueprint,
    find_complexity_hotspots,
    find_circular_dependencies,
    find_unused_functions,
)


def test_blueprint_build_empty_repo(tmp_path):
    # Create an empty repo
    repo = tmp_path / "empty_repo"
    repo.mkdir()

    bp = build_blueprint(repo)
    assert bp.graph.number_of_nodes() == 0
    assert len(bp.entities) == 0
    assert "Total Entities: 0" in summarize_blueprint(bp)


def test_blueprint_build_simple_repo(tmp_path):
    repo = tmp_path / "simple_repo"
    repo.mkdir()

    # Create a few files
    main_py = repo / "main.py"
    main_py.write_text("import utils\ndef main():\n    print(utils.do_work())\n\nmain()")

    utils_py = repo / "utils.py"
    utils_py.write_text(
        "def do_work():\n    return 'done'\n\ndef unused_func():\n    return 'no one calls me'"
    )

    bp = build_blueprint(repo)

    # Check entities
    assert "main.py" in bp.entities
    assert "utils.py" in bp.entities
    assert "main.py::main" in bp.entities
    assert "utils.py::do_work" in bp.entities
    assert "utils.py::unused_func" in bp.entities

    # Check relationships
    assert bp.graph.has_edge("main.py", "utils")
    assert bp.graph.has_edge("main.py::main", "main.py")

    # Check unused functions
    unused = find_unused_functions(bp)
    assert "utils.py::unused_func" in unused
    assert "main.py::main" not in unused  # main.py is usually an entry point


def test_blueprint_persistence(tmp_path):
    repo = tmp_path / "persist_repo"
    repo.mkdir()
    (repo / "test.py").write_text("def foo(): pass")

    bp = build_blueprint(repo)
    store_blueprint(repo, bp)

    loaded_bp = load_blueprint(repo)
    assert loaded_bp is not None
    assert loaded_bp.metadata == bp.metadata
    assert loaded_bp.graph.number_of_nodes() == bp.graph.number_of_nodes()


def test_blueprint_complexity_and_cycles(tmp_path):
    repo = tmp_path / "complex_repo"
    repo.mkdir()

    # High complexity function
    repo_py = repo / "repo.py"
    repo_py.write_text("""
def complex_func(x):
    if x > 0:
        for i in range(x):
            if i % 2 == 0:
                print(i)
            else:
                print('odd')
    elif x < 0:
        while x < 0:
            x += 1
    return x
""")

    # Circular dependency
    a_py = repo / "a.py"
    a_py.write_text("import b")
    b_py = repo / "b.py"
    b_py.write_text("import a")

    bp = build_blueprint(repo)

    # Complexity
    hotspots = find_complexity_hotspots(bp, threshold=2)
    assert any("repo.py::complex_func" == name for name, comp in hotspots)

    # Cycles
    cycles = find_circular_dependencies(bp)
    assert len(cycles) > 0
    # Check if 'a.py' and 'b.py' are in a cycle
    found_cycle = False
    for cycle in cycles:
        if "a.py" in cycle and "b.py" in cycle:
            found_cycle = True
            break
    assert found_cycle


def test_ensure_blueprint(tmp_path):
    repo = tmp_path / "ensure_repo"
    repo.mkdir()
    (repo / "test.py").write_text("def foo(): pass")

    # First call builds
    bp1 = ensure_blueprint(repo)
    assert bp1.graph.number_of_nodes() > 0

    # Second call loads
    bp2 = ensure_blueprint(repo)
    assert bp1 == bp2  # This might fail if Blueprint is not comparable, but metadata should match
    assert bp2.metadata == bp1.metadata
