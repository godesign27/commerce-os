#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
ln -sf ../../tests/hooks/pre-commit .git/hooks/pre-commit
echo "✓ pre-commit hook installed"
