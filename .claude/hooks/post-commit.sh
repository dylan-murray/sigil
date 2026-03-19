#!/bin/bash
# Post-commit hook: detect git commits and signal to Claude to check issues

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if echo "$COMMAND" | grep -qE 'git commit'; then
    echo '{"additionalContext": "A git commit was just made. Check open issues in .issues/ against recent commits. If any acceptance criteria are now satisfied, propose closing them."}'
fi

exit 0
