import warnings
from pathlib import Path
from typing import Any

import tree_sitter_languages

warnings.filterwarnings("ignore", category=FutureWarning, module="tree_sitter")

EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "c_sharp",
    ".ex": "elixir",
    ".exs": "elixir",
    ".scala": "scala",
    ".lua": "lua",
    ".r": "r",
    ".jl": "julia",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".clj": "clojure",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".php": "php",
    ".pl": "perl",
    ".dart": "dart",
    ".vim": "vim",
    ".zig": "zig",
    ".tf": "hcl",
}

IMPORT_TYPES = {
    "import_statement",
    "import_from_statement",
    "import_declaration",
    "use_declaration",
    "include_expression",
    "preproc_include",
    "package_clause",
}

DEFINITION_TYPES = {
    "class_definition",
    "class_declaration",
    "class_specifier",
    "function_definition",
    "function_declaration",
    "function_item",
    "method_declaration",
    "method_definition",
    "method",
    "singleton_method",
    "struct_item",
    "struct_specifier",
    "struct_declaration",
    "type_declaration",
    "type_alias_declaration",
    "interface_declaration",
    "trait_item",
    "enum_item",
    "enum_declaration",
    "enum_specifier",
    "impl_item",
    "module",
    "module_definition",
    "const_declaration",
    "const_item",
}

BODY_TYPES = {
    "block",
    "class_body",
    "declaration_list",
    "field_declaration_list",
    "enum_body",
    "impl_body",
    "interface_body",
    "body",
    "do_block",
}

FIELD_TYPES = {
    "expression_statement",
    "field_declaration",
    "field_definition",
    "typed_parameter",
    "public_field_definition",
    "property_declaration",
}


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _signature_line(node: Any, source: bytes) -> str:
    text = _node_text(node, source)
    first_line = text.split("\n")[0].rstrip()
    if len(first_line) > 150:
        first_line = first_line[:150] + "..."
    return first_line


CLASS_TYPES = {
    "class_definition",
    "class_declaration",
    "class_specifier",
    "struct_item",
    "struct_specifier",
    "struct_declaration",
    "interface_declaration",
    "trait_item",
    "enum_item",
    "enum_declaration",
    "enum_specifier",
    "impl_item",
    "module",
    "module_definition",
}


def _extract_class_body(node: Any, source: bytes, indent: str = "    ") -> list[str]:
    lines: list[str] = []
    for child in node.children:
        if child.type in BODY_TYPES:
            for member in child.children:
                if member.type in DEFINITION_TYPES:
                    sig = _signature_line(member, source)
                    lines.append(f"{indent}{sig}")
                elif member.type in FIELD_TYPES:
                    sig = _signature_line(member, source)
                    stripped = sig.strip()
                    if stripped and not stripped.startswith(("#", "//", "/*", "pass")):
                        lines.append(f"{indent}{stripped}")
                elif member.type == "decorated_definition":
                    for deco_child in member.children:
                        if deco_child.type == "decorator":
                            lines.append(f"{indent}{_signature_line(deco_child, source)}")
                        elif deco_child.type in DEFINITION_TYPES:
                            lines.append(f"{indent}{_signature_line(deco_child, source)}")
    return lines


def _extract_top_level(root: Any, source: bytes) -> tuple[list[str], list[str]]:
    imports: list[str] = []
    definitions: list[str] = []

    for node in root.children:
        if node.type in IMPORT_TYPES:
            imports.append(_signature_line(node, source))

        elif node.type == "decorated_definition":
            for child in node.children:
                if child.type == "decorator":
                    definitions.append(_signature_line(child, source))
                elif child.type in DEFINITION_TYPES:
                    definitions.append(_signature_line(child, source))
                    if child.type in CLASS_TYPES:
                        definitions.extend(_extract_class_body(child, source))

        elif node.type == "export_statement":
            definitions.append(_signature_line(node, source))
            for child in node.children:
                if child.type in CLASS_TYPES:
                    definitions.extend(_extract_class_body(child, source))
                elif child.type == "decorated_definition":
                    for deco_child in child.children:
                        if deco_child.type in CLASS_TYPES:
                            definitions.extend(_extract_class_body(deco_child, source))

        elif node.type in DEFINITION_TYPES:
            definitions.append(_signature_line(node, source))
            if node.type in CLASS_TYPES:
                definitions.extend(_extract_class_body(node, source))

        elif node.type == "expression_statement":
            sig = _signature_line(node, source)
            stripped = sig.strip()
            if "=" in stripped and not stripped.startswith(("#", "//", "/*")):
                definitions.append(sig)

        elif node.type == "lexical_declaration":
            sig = _signature_line(node, source)
            if "require(" in sig:
                imports.append(sig)
            else:
                definitions.append(sig)

    return imports, definitions


def summarize(content: str, filepath: str) -> str:
    suffix = Path(filepath).suffix.lower()
    language = EXTENSION_TO_LANGUAGE.get(suffix)
    if not language:
        return _fallback_summary(content)

    try:
        parser = tree_sitter_languages.get_parser(language)
    except (AttributeError, KeyError, ImportError):
        return _fallback_summary(content)

    source = content.encode("utf-8", errors="replace")
    try:
        tree = parser.parse(source)
    except (ValueError, OSError, UnicodeDecodeError):
        return _fallback_summary(content)

    imports, definitions = _extract_top_level(tree.root_node, source)

    result: list[str] = []
    if imports:
        result.append("Imports:")
        for imp in imports[:20]:
            result.append(f"  {imp}")
        if len(imports) > 20:
            result.append(f"  ... ({len(imports) - 20} more)")
    if definitions:
        result.append("Structure:")
        for defn in definitions:
            result.append(f"  {defn}")

    return "\n".join(result) if result else _fallback_summary(content)


def _fallback_summary(content: str) -> str:
    line_count = content.count("\n") + 1
    first_lines = "\n".join(content.splitlines()[:15])
    return f"({line_count} lines)\n{first_lines}"
