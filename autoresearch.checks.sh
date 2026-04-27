#!/bin/bash
set -euo pipefail
python3 -m pytest tests/ -x -q
