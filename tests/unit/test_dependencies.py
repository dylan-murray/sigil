from sigil.pipeline.dependencies import (
    DependencyEdge,
    DependencyGraph,
    DependencyType,
    _build_import_map,
    _detect_call_chain_deps,
    _detect_import_chain_deps,
    _detect_same_file_deps,
    _extract_item_files,
    analyze_dependencies,
    format_dependency_graph,
)
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding


def _finding(**overrides) -> Finding:
    defaults = {
        "category": "dead_code",
        "file": "src/utils.py",
        "line": 10,
        "description": "Unused import",
        "risk": "low",
        "suggested_fix": "Remove it",
        "disposition": "pr",
        "priority": 1,
        "rationale": "Not referenced",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _idea(**overrides) -> FeatureIdea:
    defaults = {
        "title": "Add retry logic",
        "description": "Retry failed HTTP calls",
        "rationale": "Improves reliability",
        "complexity": "low",
        "disposition": "pr",
        "priority": 2,
    }
    defaults.update(overrides)
    return FeatureIdea(**defaults)


class TestExtractItemFiles:
    def test_finding_with_file_only(self):
        item = _finding(file="src/utils.py")
        result = _extract_item_files(item)
        assert result == {"src/utils.py"}

    def test_finding_with_relevant_files(self):
        item = _finding(file="src/utils.py", relevant_files=("src/helpers.py", "src/types.py"))
        result = _extract_item_files(item)
        assert result == {"src/utils.py", "src/helpers.py", "src/types.py"}

    def test_idea_with_relevant_files(self):
        item = _idea(relevant_files=("src/api.py", "src/client.py"))
        result = _extract_item_files(item)
        assert result == {"src/api.py", "src/client.py"}

    def test_idea_with_no_files(self):
        item = _idea()
        result = _extract_item_files(item)
        assert result == set()


class TestSameFileDetection:
    def test_overlapping_files(self):
        items = [
            _finding(file="src/utils.py"),
            _finding(file="src/main.py", relevant_files=("src/utils.py",)),
        ]
        file_sets = [_extract_item_files(i) for i in items]
        edges = _detect_same_file_deps(items, file_sets)
        assert len(edges) == 1
        assert edges[0].dep_type == DependencyType.SAME_FILE
        assert "src/utils.py" in edges[0].shared_files

    def test_no_overlap(self):
        items = [
            _finding(file="src/utils.py"),
            _finding(file="src/main.py"),
        ]
        file_sets = [_extract_item_files(i) for i in items]
        edges = _detect_same_file_deps(items, file_sets)
        assert len(edges) == 0

    def test_partial_overlap(self):
        items = [
            _finding(file="src/a.py", relevant_files=("src/shared.py",)),
            _finding(file="src/b.py", relevant_files=("src/shared.py", "src/other.py")),
        ]
        file_sets = [_extract_item_files(i) for i in items]
        edges = _detect_same_file_deps(items, file_sets)
        assert len(edges) == 1
        assert "src/shared.py" in edges[0].shared_files

    def test_three_items_sharing_file(self):
        items = [
            _finding(file="src/shared.py"),
            _finding(file="src/other.py", relevant_files=("src/shared.py",)),
            _finding(file="src/third.py", relevant_files=("src/shared.py",)),
        ]
        file_sets = [_extract_item_files(i) for i in items]
        edges = _detect_same_file_deps(items, file_sets)
        assert len(edges) == 3


class TestImportChainDetection:
    def test_import_chain_detected(self, tmp_path):
        mod_a = tmp_path / "src" / "module_a.py"
        mod_a.parent.mkdir(parents=True)
        mod_a.write_text("from src.module_b import helper\n")

        mod_b = tmp_path / "src" / "module_b.py"
        mod_b.write_text("def helper(): pass\n")

        items = [
            _finding(file="src/module_b.py"),
            _finding(file="src/module_a.py"),
        ]
        file_sets = [_extract_item_files(i) for i in items]
        import_map = _build_import_map(tmp_path)
        edges = _detect_import_chain_deps(items, file_sets, import_map)
        assert len(edges) == 1
        assert edges[0].dep_type == DependencyType.IMPORT_CHAIN

    def test_no_import_chain(self, tmp_path):
        mod_a = tmp_path / "src" / "module_a.py"
        mod_a.parent.mkdir(parents=True)
        mod_a.write_text("import os\n")

        mod_b = tmp_path / "src" / "module_b.py"
        mod_b.write_text("import sys\n")

        items = [
            _finding(file="src/module_a.py"),
            _finding(file="src/module_b.py"),
        ]
        file_sets = [_extract_item_files(i) for i in items]
        import_map = _build_import_map(tmp_path)
        edges = _detect_import_chain_deps(items, file_sets, import_map)
        assert len(edges) == 0


class TestCallChainDetection:
    def test_call_chain_detected(self, tmp_path):
        target_file = tmp_path / "src" / "utils.py"
        target_file.parent.mkdir(parents=True)
        target_file.write_text("def process_data(): pass\n")

        items = [
            _finding(
                file="src/utils.py",
                implementation_spec="Modify the process_data function to add logging.",
            ),
            _finding(
                file="src/main.py",
                relevant_files=("src/utils.py",),
            ),
        ]
        file_sets = [_extract_item_files(i) for i in items]
        edges = _detect_call_chain_deps(items, file_sets, tmp_path)
        assert len(edges) == 1
        assert edges[0].dep_type == DependencyType.CALL_CHAIN

    def test_no_call_chain(self, tmp_path):
        target_file = tmp_path / "src" / "utils.py"
        target_file.parent.mkdir(parents=True)
        target_file.write_text("def other_function(): pass\n")

        items = [
            _finding(
                file="src/utils.py",
                implementation_spec="Remove unused imports from this file.",
            ),
            _finding(file="src/main.py"),
        ]
        file_sets = [_extract_item_files(i) for i in items]
        edges = _detect_call_chain_deps(items, file_sets, tmp_path)
        assert len(edges) == 0


class TestAnalyzeDependencies:
    def test_empty_items(self, tmp_path):
        graph = analyze_dependencies(tmp_path, [])
        assert len(graph.edges) == 0
        assert len(graph.safe_items) == 0
        assert len(graph.merge_suggestions) == 0

    def test_single_item(self, tmp_path):
        items = [_finding(file="src/utils.py")]
        graph = analyze_dependencies(tmp_path, items)
        assert len(graph.edges) == 0
        assert 0 in graph.safe_items
        assert len(graph.merge_suggestions) == 0

    def test_independent_items(self, tmp_path):
        items = [
            _finding(file="src/a.py"),
            _finding(file="src/b.py"),
        ]
        graph = analyze_dependencies(tmp_path, items)
        assert len(graph.edges) == 0
        assert 0 in graph.safe_items
        assert 1 in graph.safe_items
        assert len(graph.merge_suggestions) == 0

    def test_dependent_items(self, tmp_path):
        shared = tmp_path / "src" / "shared.py"
        shared.parent.mkdir(parents=True)
        shared.write_text("# shared module\n")

        items = [
            _finding(file="src/shared.py"),
            _finding(file="src/other.py", relevant_files=("src/shared.py",)),
        ]
        graph = analyze_dependencies(tmp_path, items)
        assert len(graph.edges) >= 1
        assert any(e.dep_type == DependencyType.SAME_FILE for e in graph.edges)
        assert len(graph.merge_suggestions) >= 1

    def test_safe_items_excludes_dependent(self, tmp_path):
        items = [
            _finding(file="src/shared.py"),
            _finding(file="src/other.py", relevant_files=("src/shared.py",)),
            _finding(file="src/isolated.py"),
        ]
        graph = analyze_dependencies(tmp_path, items)
        assert 2 in graph.safe_items


class TestFormatDependencyGraph:
    def test_empty_graph(self):
        graph = DependencyGraph(items=())
        output = format_dependency_graph(graph)
        assert "No work items to analyze" in output

    def test_single_safe_item(self):
        items = (_finding(file="src/utils.py"),)
        graph = DependencyGraph(
            items=items,
            edges=(),
            safe_items=(0,),
            merge_suggestions=(),
        )
        output = format_dependency_graph(graph)
        assert "src/utils.py" in output
        assert "safe to parallelize" in output

    def test_dependency_edge_display(self):
        items = (
            _finding(file="src/shared.py"),
            _finding(file="src/other.py", relevant_files=("src/shared.py",)),
        )
        edge = DependencyEdge(
            source_idx=0,
            target_idx=1,
            dep_type=DependencyType.SAME_FILE,
            description="Items share: src/shared.py",
            shared_files=("src/shared.py",),
        )
        graph = DependencyGraph(
            items=items,
            edges=(edge,),
            safe_items=(),
            merge_suggestions=((0, 1),),
        )
        output = format_dependency_graph(graph)
        assert "same_file" in output
        assert "src/shared.py" in output
        assert "Merge" in output

    def test_all_safe_items(self):
        items = (
            _finding(file="src/a.py"),
            _finding(file="src/b.py"),
        )
        graph = DependencyGraph(
            items=items,
            edges=(),
            safe_items=(0, 1),
            merge_suggestions=(),
        )
        output = format_dependency_graph(graph)
        assert "safe to parallelize" in output


class TestBuildImportMap:
    def test_simple_import(self, tmp_path):
        mod = tmp_path / "src" / "app.py"
        mod.parent.mkdir(parents=True)
        mod.write_text("from src.utils import helper\n")

        import_map = _build_import_map(tmp_path)
        assert "src/app.py" in import_map
        assert "src/utils.py" in import_map["src/app.py"]

    def test_no_python_files(self, tmp_path):
        import_map = _build_import_map(tmp_path)
        assert len(import_map) == 0

    def test_relative_import(self, tmp_path):
        mod = tmp_path / "pkg" / "mod.py"
        mod.parent.mkdir(parents=True)
        mod.write_text("from .helpers import func\n")

        import_map = _build_import_map(tmp_path)
        assert "pkg/mod.py" in import_map


class TestMergeSuggestions:
    def test_merge_groups_connected_items(self, tmp_path):
        items = [
            _finding(file="src/a.py", relevant_files=("src/shared.py",)),
            _finding(file="src/b.py", relevant_files=("src/shared.py",)),
            _finding(file="src/c.py"),
        ]
        graph = analyze_dependencies(tmp_path, items)
        assert len(graph.merge_suggestions) >= 1
        merged_indices = set()
        for group in graph.merge_suggestions:
            merged_indices.update(group)
        assert 0 in merged_indices
        assert 1 in merged_indices

    def test_no_merge_for_independent_items(self, tmp_path):
        items = [
            _finding(file="src/a.py"),
            _finding(file="src/b.py"),
            _finding(file="src/c.py"),
        ]
        graph = analyze_dependencies(tmp_path, items)
        assert len(graph.merge_suggestions) == 0
