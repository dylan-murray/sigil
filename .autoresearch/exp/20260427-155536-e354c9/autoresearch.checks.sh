#!/usr/bin/env bash
set -euo pipefail

# Run unit tests for the affected module and related tests
python3 -m pytest tests/unit/test_utils.py tests/unit/test_tools.py -x -q --timeout=120
