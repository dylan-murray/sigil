import ast
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
from sigil.core.config import SIGIL_DIR
from sigil.core.utils import now_utc, read_file

logger = logging.getLogger(__name__)

BLUEPRINT_DIR = "blueprint"


@dataclass(frozen=True)
class Entity:
    name: str
    type: str  # "file", "class", "function", "method"
    path: str
    relations: list[str] = field(default_factory=list)
    complexity: int = 0
    is_public: bool = False


@dataclass
class Blueprint:
    graph: nx.DiGraph
    entities: dict[str, Entity]
    metadata: dict[str, Any]

    def to_json(self) -> str:
        # NetworkX graphs aren't directly JSON serializable
        data = {
            "metadata": self.metadata,
            "nodes": {
                n: {"type": d["type"], "complexity": d.get("complexity", 0)}
                for n, d in self.graph.nodes(data=True)
            },
            "edges": list(self.graph.edges()),
            "entities": {k: vars(v) for k, v in self.entities.items()},
        }
        return json.dumps(data, indent=2)


def _calculate_complexity(node: ast.AST) -> int:
    """Simple cyclomatic complexity approximation: count branching constructs."""
    count = 0
    for child in ast.walk(node):
        if isinstance(
            child,
            (
                ast.If,
                ast.While,
                ast.For,
                ast.AsyncFor,
                ast.ExceptHandler,
                ast.With,
                ast.AsyncWith,
                ast.And,
                ast.Or,
                ast.IfExp,
            ),
        ):
            count += 1
    return count + 1


def build_blueprint(repo: Path) -> Blueprint:
    graph = nx.DiGraph()
    entities: dict[str, Entity] = {}

    py_files = list(repo.rglob("*.py"))

    # First pass: Discover entities
    for py_file in py_files:
        rel_path = str(py_file.relative_to(repo))
        if ".sigil" in rel_path:
            continue

        file_entity = Entity(name=rel_path, type="file", path=rel_path)
        entities[rel_path] = file_entity
        graph.add_node(rel_path, type="file", complexity=0)

        try:
            content = read_file(py_file)
            tree = ast.parse(content)
        except (SyntaxError, OSError) as e:
            logger.warning("Failed to parse %s: %s", rel_path, e)
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                name = f"{rel_path}::{node.name}"
                entities[name] = Entity(
                    name=name, type="class", path=rel_path, complexity=_calculate_complexity(node)
                )
                graph.add_node(name, type="class", complexity=entities[name].complexity)
                graph.add_edge(name, rel_path)
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                name = f"{rel_path}::{node.name}"
                # Check if it's a method (inside a class)
                # This is a simplification; real AST analysis would track parent
                entity_type = "function"
                entities[name] = Entity(
                    name=name,
                    type=entity_type,
                    path=rel_path,
                    complexity=_calculate_complexity(node),
                )
                graph.add_node(name, type=entity_type, complexity=entities[name].complexity)
                graph.add_edge(name, rel_path)

    # Second pass: Relationships (Imports and Calls)
    for py_file in py_files:
        rel_path = str(py_file.relative_to(repo))
        if ".sigil" in rel_path:
            continue

        try:
            tree = ast.parse(read_file(py_file))
        except Exception:
            continue

        for node in ast.walk(tree):
            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # Map import to a potential file entity (simplification)
                    target = alias.name.replace(".", "/")
                    if target.endswith(".py"):
                        target = target.removesuffix(".py")
                    graph.add_edge(rel_path, target)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    target = node.module.replace(".", "/")
                    if target.endswith(".py"):
                        target = target.removesuffix(".py")
                    graph.add_edge(rel_path, target)

            # Calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    # Simple call: func()
                    # We can't know for sure where it's from without full symbol table,
                    # but we can track the name.
                    pass
                elif isinstance(node.func, ast.Attribute):
                    # Method call: obj.method()
                    pass

    return Blueprint(
        graph=graph,
        entities=entities,
        metadata={"updated": now_utc(), "node_count": graph.number_of_nodes()},
    )


def store_blueprint(repo: Path, blueprint: Blueprint) -> None:
    bdir = repo / SIGIL_DIR / BLUEPRINT_DIR
    bdir.mkdir(parents=True, exist_ok=True)

    (bdir / "graph.json").write_text(blueprint.to_json())

    # Human readable index
    hotspots = find_complexity_hotspots(blueprint)
    cycles = find_circular_dependencies(blueprint)

    index_content = f"# Project Blueprint Index\n\nUpdated: {blueprint.metadata['updated']}\n\n"
    index_content += f"Total Entities: {blueprint.metadata['node_count']}\n\n"

    index_content += "## Complexity Hotspots\n"
    for name, comp in hotspots[:10]:
        index_content += f"- {name} (Complexity: {comp})\n"

    index_content += "\n## Circular Dependencies\n"
    if not cycles:
        index_content += "None detected.\n"
    else:
        for cycle in cycles:
            index_content += f"- {' -> '.join(cycle)}\n"

    (bdir / "index.md").write_text(index_content)


def load_blueprint(repo: Path) -> Blueprint | None:
    bdir = repo / SIGIL_DIR / BLUEPRINT_DIR
    graph_file = bdir / "graph.json"
    if not graph_file.exists():
        return None

    try:
        data = json.loads(graph_file.read_text())
        graph = nx.DiGraph()
        for node, attrs in data["nodes"].items():
            graph.add_node(node, **attrs)
        graph.add_edges_from(data["edges"])

        entities = {k: Entity(**v) for k, v in data["entities"].items()}
        return Blueprint(graph=graph, entities=entities, metadata=data["metadata"])
    except Exception as e:
        logger.error("Failed to load blueprint: %s", e)
        return None


def ensure_blueprint(repo: Path) -> Blueprint:
    bp = load_blueprint(repo)
    if bp:
        return bp

    logger.info("Building project blueprint...")
    bp = build_blueprint(repo)
    store_blueprint(repo, bp)
    return bp


def query_callers(blueprint: Blueprint, entity_name: str) -> list[str]:
    """Find all entities that have an edge to the given entity."""
    return list(blueprint.graph.predecessors(entity_name)) if entity_name in blueprint.graph else []


def find_complexity_hotspots(blueprint: Blueprint, threshold: int = 10) -> list[tuple[str, int]]:
    hotspots = []
    for node, data in blueprint.graph.nodes(data=True):
        comp = data.get("complexity", 0)
        if comp >= threshold:
            hotspots.append((node, comp))
    return sorted(hotspots, key=lambda x: x[1], reverse=True)


def find_circular_dependencies(blueprint: Blueprint) -> list[list[str]]:
    try:
        return list(nx.simple_cycles(blueprint.graph))
    except Exception:
        return []


def find_unused_functions(blueprint: Blueprint) -> list[str]:
    """Find functions with no incoming edges (excluding public entry points)."""
    unused = []
    for node, data in blueprint.graph.nodes(data=True):
        if data.get("type") == "function":
            if blueprint.graph.in_degree(node) == 0:
                # Conservative: only mark as unused if it's not in a 'main' or 'api' file
                if not any(x in node for x in ["main.py", "api.py", "cli.py"]):
                    unused.append(node)
    return unused


def summarize_blueprint(blueprint: Blueprint) -> str:
    hotspots = find_complexity_hotspots(blueprint)
    cycles = find_circular_dependencies(blueprint)
    unused = find_unused_functions(blueprint)

    summary = "### Project Architecture Health\n"
    summary += f"- Total Entities: {blueprint.metadata['node_count']}\n"

    if hotspots:
        summary += f"- Complexity Hotspots: {len(hotspots)} functions exceed threshold (Top: {hotspots[0][0]})\n"
    else:
        summary += "- No significant complexity hotspots detected.\n"

    if cycles:
        summary += f"- Circular Dependencies: {len(cycles)} cycles detected.\n"
    else:
        summary += "- No circular dependencies detected.\n"

    if unused:
        summary += f"- Potential Dead Code: {len(unused)} unused internal functions detected.\n"
    else:
        summary += "- No obvious dead code detected.\n"

    return summary
