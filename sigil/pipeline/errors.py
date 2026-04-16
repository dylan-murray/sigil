import ast
from pathlib import Path
from sigil.pipeline.models import Finding


VAGUE_WORDS = {"error", "failed", "exception", "problem", "issue", "wrong"}
MIN_MESSAGE_LENGTH = 10


def find_poor_errors(repo: Path) -> list[Finding]:
    """
    Analyzes Python files in the repository for low-quality error messages
    and bare exception handlers.
    """
    findings: list[Finding] = []
    py_files = list(repo.rglob("*.py"))

    for file_path in py_files:
        relative_path = str(file_path.relative_to(repo))
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            # Check for bare except blocks
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    findings.append(
                        Finding(
                            category="Error Handling",
                            file=relative_path,
                            line=node.lineno,
                            description="Bare 'except:' block detected.",
                            risk="Low",
                            suggested_fix="Catch specific exceptions instead of using a bare except block.",
                            disposition="open",
                            priority=2,
                            rationale="Bare except blocks catch SystemExit and KeyboardInterrupt, making it harder to terminate the program.",
                        )
                    )

            # Check for raise statements
            if isinstance(node, ast.Raise):
                # Ignore bare 'raise' (re-raising)
                if node.exc is None:
                    continue

                # We only analyze calls like raise Exception("message")
                if isinstance(node.exc, ast.Call):
                    # Extract the message if it's a constant string
                    message = None
                    if node.exc.args:
                        first_arg = node.exc.args[0]
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            message = first_arg.value

                    if message is None:
                        # Exception raised without a string message or with a dynamic message
                        # We flag it if it's a simple call without arguments
                        if not node.exc.args:
                            findings.append(
                                Finding(
                                    category="Error Handling",
                                    file=relative_path,
                                    line=node.lineno,
                                    description="Exception raised without an error message.",
                                    risk="Low",
                                    suggested_fix="Add a descriptive error message to the exception.",
                                    disposition="open",
                                    priority=3,
                                    rationale="Exceptions without messages make debugging significantly harder.",
                                )
                            )
                    else:
                        # Analyze the message quality
                        msg_lower = message.lower().strip()
                        is_vague = len(msg_lower) < MIN_MESSAGE_LENGTH or any(
                            word == msg_lower for word in VAGUE_WORDS
                        )

                        if is_vague:
                            findings.append(
                                Finding(
                                    category="Error Handling",
                                    file=relative_path,
                                    line=node.lineno,
                                    description=f"Vague error message: '{message}'",
                                    risk="Low",
                                    suggested_fix="Provide a more descriptive error message that explains why the error occurred and how to fix it.",
                                    disposition="open",
                                    priority=3,
                                    rationale="Short or generic error messages provide little value during debugging.",
                                )
                            )
                elif isinstance(node.exc, (ast.Name, ast.Attribute)):
                    # raise ValueError (no call, no message)
                    findings.append(
                        Finding(
                            category="Error Handling",
                            file=relative_path,
                            line=node.lineno,
                            description="Exception raised without a message.",
                            risk="Low",
                            suggested_fix="Use a call to the exception class to provide a descriptive message, e.g., raise ValueError('...')",
                            disposition="open",
                            priority=3,
                            rationale="Exceptions without messages make debugging significantly harder.",
                        )
                    )

    return findings
