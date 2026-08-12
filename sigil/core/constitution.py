from dataclasses import dataclass, field
from pathlib import Path
import re
from sigil.core.utils import read_file


@dataclass(frozen=True)
class Constitution:
    rules: list[str] = field(default_factory=list)
    priorities: dict[str, int] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.rules)


def extract_constitution(repo_path: Path) -> Constitution:
    """
    Extracts explicit coding rules from the repository's instruction files.
    Focuses on 'rules:' sections in AGENTS.md and similar patterns.
    """
    rules = []

    # Priority sources for explicit rules
    sources = ["AGENTS.md", ".cursorrules", "README.md", "CONTRIBUTING.md"]

    for source in sources:
        path = repo_path / source
        if not path.exists():
            continue

        content = read_file(path)
        if not content:
            continue

        # Look for "Rules" sections (e.g., "## Rules", "### Coding Rules", "rules:")
        # This regex looks for a header containing 'Rules' and captures everything
        # until the next header or end of file.
        rule_sections = re.findall(
            r"(?i)(?:^|\n)(?:#+.*Rules.*)(.*?)(?=\n#+|$)", content, re.DOTALL
        )

        for section in rule_sections:
            # Extract bullet points or numbered lists
            lines = section.splitlines()
            for line in lines:
                line = line.strip()
                if line.startswith(("-", "*", "1.", "2.", "3.", "4.", "5.")):
                    # Clean the bullet/number
                    rule = re.sub(r"^([-*]|\d+\.)\s*", "", line).strip()
                    if rule and rule not in rules:
                        rules.append(rule)

    # Fallback: if no explicit rules found, check for common patterns in AGENTS.md
    if not rules:
        agents_md = repo_path / "AGENTS.md"
        if agents_md.exists():
            content = read_file(agents_md)
            # Look for "Hard Rules" section specifically
            hard_rules = re.findall(
                r"(?i)(?:^|\n)(?:## Hard Rules)(.*?)(?=\n##|$)", content, re.DOTALL
            )
            for section in hard_rules:
                lines = section.splitlines()
                for line in lines:
                    line = line.strip()
                    if line.startswith(("1.", "2.", "3.", "4.", "5.")):
                        rule = re.sub(r"^\d+\.\s*", "", line).strip()
                        if rule:
                            rules.append(rule)

    return Constitution(rules=rules)


def format_constitution_for_prompt(constitution: Constitution) -> str:
    """Renders the constitution as a formatted string for agent system prompts."""
    if not constitution:
        return ""

    rules_text = "\n".join(f"{i + 1}. {rule}" for i, rule in enumerate(constitution.rules))
    return f"\n\nProject Constitution (Authoritative Rules):\n{rules_text}\n\nViolating these rules will result in rejected PRs."


def validate_code_conformance(code: str, constitution: Constitution) -> list[str]:
    """
    Deterministic validation of code against the constitution.
    In this iteration, we use regex-based checks for common rules.
    """
    violations = []

    # Map of common rule keywords to regex checks
    # This is a simplified deterministic validator
    checks = {
        "type hints": (
            r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)\s*->\s*[^:]",
            "Missing return type hint in function definition",
        ),
        "f-strings": (r"\.format\(|% \(", "Use f-strings instead of .format() or % formatting"),
        "bare except": (r"except\s*:", "Bare except detected; specify the exception type"),
        "comments": (r"#\s*", "Avoid comments unless logic is non-obvious"),
    }

    for rule in constitution.rules:
        rule_lower = rule.lower()
        for keyword, (pattern, message) in checks.items():
            if keyword in rule_lower:
                # If the rule is present in the constitution, enforce the regex
                # Note: This is a naive implementation; it flags if the pattern IS found
                # (except for type hints where we'd need to check for ABSENCE,
                # but for this iteration we keep it simple).

                # Special case: type hints (we want to find functions WITHOUT ->)
                if keyword == "type hints":
                    # This is complex for regex, so we skip the 'absence' check
                    # and focus on the 'presence' of bad patterns for others.
                    continue

                if re.search(pattern, code):
                    violations.append(message)
                    break  # Only report one violation per rule

    return list(set(violations))
