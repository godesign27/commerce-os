#!/usr/bin/env bash
# Run the Commerce OS structural test suite. Exit non-zero on any failure.
#   ./run-tests.sh            fast suite
#   ./run-tests.sh --mutants  also prove the suite catches each known defect
set -euo pipefail
cd "$(dirname "$0")"
if python3 -c "import pytest" 2>/dev/null; then
  python3 -m pytest tests/ -q
else
  python3 -m unittest discover -s tests -t . -q
fi
if [[ "${1:-}" == "--mutants" ]]; then
  echo; echo "== mutation check: every known defect must be caught =="
  python3 tests/mutants.py
fi
