import re
from pathlib import Path
from sigil.pipeline.models import Finding

# Patterns for secrets
SECRET_PATTERNS = [
    re.compile(r"(api_key|password|token|secret|auth_token)", re.IGNORECASE),
]

# Pattern for print
PRINT_PATTERN = re.compile(r"print\s*\(")

# Pattern for logging calls
LOG_PATTERN = re.compile(r"logger\.(info|debug|error|warning|warn|critical)\s*\(")


def check_logging(repo: Path) -> list[Finding]:
    """
    Perform a grep-based audit of logging hygiene across the repository.

    Checks for:
    - print() statements in production code.
    - Potential secrets in log messages.
    - Unstructured log messages (f-strings without key=value).
    - Logging inside loops (basic indentation heuristic).
    """
    findings: list[Finding] = []

    # Find all python files
    for py_file in repo.rglob("*.py"):
        # Skip tests
        if "tests/" in str(py_file.relative_to(repo)):
            continue

        # Skip known CLI files that use print for UX
        rel_path = str(py_file.relative_to(repo))
        if rel_path.endswith("cli.py"):
            continue

        try:
            content = py_file.read_text(errors="ignore")
        except OSError:
            continue

        lines = content.splitlines()

        # Track loop state for indentation heuristic
        loop_stack: list[int] = []  # Store indentation levels of active loops

        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if not stripped:
                continue

            indent = len(line) - len(stripped)

            # Update loop stack
            if stripped.startswith(("for ", "while ")):
                loop_stack.append(indent)

            # Pop loops that are no longer active
            while (
                loop_stack
                and indent <= loop_stack[-1]
                and not stripped.startswith(("for ", "while "))
            ):
                # This is a bit naive, but it's a heuristic
                # If we are at the same or lower indent than the last loop,
                # and we didn't just start a new loop, the previous loop might have ended.
                # However, we only pop if we are strictly less than or equal and not starting a new one.
                # Actually, let's just pop if indent <= loop_stack[-1] and it's not a loop start.
                # But we need to be careful about nested blocks.
                # For a simple heuristic, let's just check if we are currently "inside" any loop.
                break

            # 1. Check for print()
            if PRINT_PATTERN.search(line):
                findings.append(
                    Finding(
                        category="style",
                        file=rel_path,
                        line=i,
                        description="Found print() statement in production code.",
                        risk="low",
                        suggested_fix="Replace print() with a proper logger call (e.g., logger.info()).",
                        disposition="pr",
                        priority=100,
                        rationale="Production code should use logging for observability.",
                        boldness="balanced",
                    )
                )

            # 2. Check for logging calls
            log_match = LOG_PATTERN.search(line)
            if log_match:
                # Check for secrets
                for secret_pat in SECRET_PATTERNS:
                    if secret_pat.search(line):
                        findings.append(
                            Finding(
                                category="security",
                                file=rel_path,
                                line=i,
                                description="Potential secret logged in log statement.",
                                risk="high",
                                suggested_fix="Remove secret from log statement or mask it.",
                                disposition="issue",
                                priority=10,
                                rationale="Logging secrets is a security vulnerability.",
                                boldness="balanced",
                            )
                        )
                        break

                # Check for unstructured logs (f-strings without key=value)
                if ('f"' in line or "f'" in line) and "=" not in line:
                    findings.append(
                        Finding(
                            category="style",
                            file=rel_path,
                            line=i,
                            description="Unstructured log statement (f-string without key=value format).",
                            risk="low",
                            suggested_fix="Use structured logging (e.g., 'key=value' in message).",
                            disposition="pr",
                            priority=110,
                            rationale="Structured logs are easier to query in production.",
                            boldness="balanced",
                        )
                    )

                # 3. Check for logging in loops
                # Heuristic: if the line is indented and we've seen a loop start at a lower indent
                if loop_stack and indent > loop_stack[-1]:
                    findings.append(
                        Finding(
                            category="style",
                            file=rel_path,
                            line=i,
                            description="Logging statement found inside a loop.",
                            risk="low",
                            suggested_fix="Move the log statement outside the loop or use a counter to limit frequency.",
                            disposition="pr",
                            priority=120,
                            rationale="Excessive logging in loops can degrade performance and flood logs.",
                            boldness="balanced",
                        )
                    )

        # Clear loop stack for next file
        loop_stack.clear()

    return findings
