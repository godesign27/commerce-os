#!/usr/bin/env bash
# Run the Commerce OS structural test suite. Exit non-zero on any failure.
#   ./run-tests.sh            fast suite
#   ./run-tests.sh --mutants  also prove the suite catches each known defect
# Uses the project environment (.venv, requirements.txt) when it exists, so tests that need Pillow
# run too; without it they are skipped and everything else still runs on the system python3.
set -euo pipefail
cd "$(dirname "$0")"
PY=python3
if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python; fi
if "$PY" -c "import pytest" 2>/dev/null; then
  "$PY" -m pytest tests/ -q
else
  "$PY" -m unittest discover -s tests -t . -q
fi
if [[ "${1:-}" == "--mutants" ]]; then
  echo; echo "== mutation check: every known defect must be caught =="
  "$PY" tests/mutants.py
fi
