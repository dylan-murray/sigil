import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding
from sigil.state.chronic import WorkItem


class DependencyType(str, Enum):
    SAME_FILE = "same_file"
    IMPORT_CHAIN = "import_chain"
    CALL_CHAIN = "call_chain"


@dataclass(frozen=True)
class DependencyEdge:
    source_idx: int
    target_idx: int
    dep_type: DependencyType
    description: str
    shared_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class DependencyGraph:
    items: tuple[Finding | FeatureIdea, ...]
    edges: tuple[DependencyEdge, ...] = ()
    safe_items: tuple[int, ...] = ()
    merge_suggestions: tuple[tuple[int, ...], ...] = ()


def _extract_item_files(item: WorkItem) -> set[str]:
    files: set[str] = set()
    if isinstance(item, Finding):
        if item.file:
            files.add(item.file)
    if isinstance(item, (Finding, FeatureIdea)):
        files.update(item.relevant_files)
    return files


def _build_import_map(repo: Path) -> dict[str, set[str]]:
    import_map: dict[str, set[str]] = {}
    py_files = list(repo.rglob("*.py"))
    for py_file in py_files:
        try:
            content = py_file.read_text()
        except OSError:
            continue
        rel = str(py_file.relative_to(repo))
        imported: set[str] = set()
        for line in content.splitlines():
            stripped = line.strip()
            m = re.match(r"^from\s+([\w.]+)\s+import", stripped)
            if m:
                module = m.group(1)
                path = module.replace(".", "/") + ".py"
                imported.add(path)
                pkg_path = module.replace(".", "/") + "/__init__.py"
                imported.add(pkg_path)
                continue
            m = re.match(r"^import\s+([\w.]+)", stripped)
            if m:
                module = m.group(1)
                path = module.replace(".", "/") + ".py"
                imported.add(path)
                pkg_path = module.replace(".", "/") + "/__init__.py"
                imported.add(pkg_path)
        if imported:
            import_map[rel] = imported
    return import_map


def _detect_same_file_deps(
    items: list[WorkItem],
    file_sets: list[set[str]],
) -> list[DependencyEdge]:
    edges: list[DependencyEdge] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            shared = file_sets[i] & file_sets[j]
            if shared:
                edges.append(
                    DependencyEdge(
                        source_idx=i,
                        target_idx=j,
                        dep_type=DependencyType.SAME_FILE,
                        description=f"Items share files: {', '.join(sorted(shared))}",
                        shared_files=tuple(sorted(shared)),
                    )
                )
    return edges


def _detect_import_chain_deps(
    items: list[WorkItem],
    file_sets: list[set[str]],
    import_map: dict[str, set[str]],
) -> list[DependencyEdge]:
    edges: list[DependencyEdge] = []
    for i in range(len(items)):
        for j in range(len(items)):
            if i == j:
                continue
            for src_file in file_sets[i]:
                for dst_file in file_sets[j]:
                    if dst_file in import_map:
                        imported_by_dst = import_map[dst_file]
                        if src_file in imported_by_dst:
                            edges.append(
                                DependencyEdge(
                                    source_idx=i,
                                    target_idx=j,
                                    dep_type=DependencyType.IMPORT_CHAIN,
                                    description=f"{dst_file} imports {src_file}",
                                    shared_files=(src_file,),
                                )
                            )
    return edges


def _detect_call_chain_deps(
    items: list[WorkItem],
    file_sets: list[set[str]],
    repo: Path,
) -> list[DependencyEdge]:
    edges: list[DependencyEdge] = []
    identifiers_by_item: list[set[str]] = []
    for item in items:
        ids: set[str] = set()
        spec = item.implementation_spec if hasattr(item, "implementation_spec") else ""
        if spec:
            for m in re.finditer(r"\b([a-zA-Z_]\w{2,})\b", spec):
                ids.add(m.group(1))
        identifiers_by_item.append(ids)

    for i in range(len(items)):
        if not identifiers_by_item[i]:
            continue
        for j in range(len(items)):
            if i == j:
                continue
            for dst_file in file_sets[j]:
                full_path = repo / dst_file
                try:
                    content = full_path.read_text()
                except OSError:
                    continue
                found_ids: set[str] = set()
                for m in re.finditer(r"^(?:def|class)\s+([a-zA-Z_]\w+)", content, re.MULTILINE):
                    found_ids.add(m.group(1))
                overlap = identifiers_by_item[i] & found_ids
                if overlap:
                    edges.append(
                        DependencyEdge(
                            source_idx=i,
                            target_idx=j,
                            dep_type=DependencyType.CALL_CHAIN,
                            description=f"Spec references identifiers defined in {dst_file}: {', '.join(sorted(overlap))}",
                            shared_files=(dst_file,),
                        )
                    )
    return edges


def analyze_dependencies(repo: Path, items: list[WorkItem]) -> DependencyGraph:
    if not items:
        return DependencyGraph(items=())

    file_sets = [_extract_item_files(item) for item in items]

    all_edges: list[DependencyEdge] = []
    all_edges.extend(_detect_same_file_deps(items, file_sets))

    import_map = _build_import_map(repo)
    all_edges.extend(_detect_import_chain_deps(items, file_sets, import_map))

    all_edges.extend(_detect_call_chain_deps(items, file_sets, repo))

    connected: set[int] = set()
    for edge in all_edges:
        connected.add(edge.source_idx)
        connected.add(edge.target_idx)

    safe_items = tuple(i for i in range(len(items)) if i not in connected)

    adjacency: dict[int, set[int]] = {i: set() for i in range(len(items))}
    for edge in all_edges:
        adjacency[edge.source_idx].add(edge.target_idx)
        adjacency[edge.target_idx].add(edge.source_idx)

    visited: set[int] = set()
    groups: list[tuple[int, ...]] = []
    for node in range(len(items)):
        if node in visited:
            continue
        group: list[int] = []
        stack = [node]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            group.append(current)
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    stack.append(neighbor)
        if len(group) > 1:
            groups.append(tuple(sorted(group)))

    return DependencyGraph(
        items=tuple(items),
        edges=tuple(all_edges),
        safe_items=safe_items,
        merge_suggestions=tuple(groups),
    )


def format_dependency_graph(graph: DependencyGraph) -> str:
    if not graph.items:
        return "No work items to analyze."

    lines: list[str] = []
    lines.append("Dependency Analysis")
    lines.append("=" * 40)

    if not graph.edges:
        lines.append("\nAll items are independent — safe to parallelize.")
    else:
        lines.append(f"\nFound {len(graph.edges)} dependency(ies):")
        for edge in graph.edges:
            src = _item_label(graph.items[edge.source_idx], edge.source_idx)
            tgt = _item_label(graph.items[edge.target_idx], edge.target_idx)
            lines.append(f"  [{edge.dep_type.value}] {src} → {tgt}")
            lines.append(f"    {edge.description}")

    if graph.safe_items:
        lines.append("\nSafe to parallelize:")
        for idx in graph.safe_items:
            lines.append(f"  • {_item_label(graph.items[idx], idx)}")

    if graph.merge_suggestions:
        lines.append("\nMerge suggestions:")
        for group in graph.merge_suggestions:
            items_str = ", ".join(_item_label(graph.items[i], i) for i in group)
            lines.append(f"  ⚠ Consider merging: {items_str}")

    return "\n".join(lines)


def _item_label(item: WorkItem, idx: int) -> str:
    if isinstance(item, Finding):
        return f"[{idx}] {item.category} ({item.file})"
    return f"[{idx}] {item.title}"


def format_dependency_graph_mermaid(graph: DependencyGraph) -> str:
    if not graph.items:
        return "graph TD\n"

    lines = ["graph TD"]
    for idx, item in enumerate(graph.items):
        label = _item_label(item, idx).replace('"', "'")
        lines.append(f'    N{idx}["{label}"]')

    for edge in graph.edges:
        style = edge.dep_type.value
        lines.append(f"    N{edge.source_idx} -->|{style}| N{edge.target_idx}")

    return "\n".join(lines) + "\n"
