#!/usr/bin/env bash
# Start Commerce OS on this computer: check what's needed, install it once, build the dashboard, open it.
#   ./start.sh              set up if needed, start the dashboard, open the browser
#   ./start.sh --check      only say whether this computer has what's needed
#   ./start.sh --no-browser don't open the browser
# Runs on this computer only (127.0.0.1). It never changes anything in a storefront.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${COMMERCE_OS_PORT:-8770}"
CHECK_ONLY=false; OPEN=true
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=true ;;
    --no-browser) OPEN=false ;;
    *) echo "Unknown option: $arg"; exit 2 ;;
  esac
done

missing=0
need() {  # need <what> <the command that fixes it>
  echo "✗ $1 is missing. Install it with:"; echo "    $2"; missing=1
}
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
  need "Python 3.9 or newer" "brew install python"
else echo "✓ Python"; fi
if ! command -v npm >/dev/null; then need "Node.js" "brew install node"; else echo "✓ Node.js"; fi
if command -v psql >/dev/null || [[ -x /opt/homebrew/opt/libpq/bin/psql ]] || [[ -x /usr/local/opt/libpq/bin/psql ]]; then
  echo "✓ psql"
else need "psql (used to read your store's catalog)" "brew install libpq"; fi
if ! command -v initdb >/dev/null && ! ls /opt/homebrew/opt/postgresql*/bin/initdb /usr/local/opt/postgresql*/bin/initdb >/dev/null 2>&1 && [[ ! -x /opt/homebrew/opt/libpq/bin/initdb ]]; then
  echo "! Postgres isn't installed. Everything works except publishing to the local test store. To add it:"
  echo "    brew install postgresql@16"
fi
if [[ $missing == 1 ]]; then echo; echo "Install what's missing, then run ./start.sh again."; exit 1; fi
if $CHECK_ONLY; then echo "This computer has what Commerce OS needs."; exit 0; fi

if [[ ! -x .venv/bin/python ]]; then
  echo "Setting up Python (first run only)…"; python3 -m venv .venv
fi
if [[ ! -f .venv/.installed ]] || [[ requirements.txt -nt .venv/.installed ]]; then
  .venv/bin/python -m pip install -q -r requirements.txt && touch .venv/.installed
fi
dash=apps/review-dashboard
if [[ ! -d $dash/node_modules ]] || [[ $dash/package-lock.json -nt $dash/node_modules/.package-lock.json ]]; then
  echo "Setting up the dashboard…"
  if ! out=$(cd "$dash" && npm ci --silent 2>&1); then
    echo "$out" | tail -20; echo "The dashboard's packages didn't install. Check your internet connection, then run ./start.sh again."; exit 1
  fi
fi
if [[ ! -f $dash/dist/index.html ]] || [[ -n "$(find "$dash/src" "$dash/package-lock.json" -newer "$dash/dist/index.html" -print -quit)" ]]; then
  echo "Building the dashboard…"
  if ! out=$(cd "$dash" && npm run build --silent 2>&1); then
    echo "$out" | tail -20
    echo "The dashboard didn't build. To reinstall its packages and try again, run:"
    echo "  rm -rf $dash/node_modules && ./start.sh"
    exit 1
  fi
fi

URL="http://127.0.0.1:$PORT/"
open_it() {
  $OPEN || return 0
  if command -v open >/dev/null; then open "$URL"; elif command -v xdg-open >/dev/null; then xdg-open "$URL"; fi
}
if curl -fs -m 2 "${URL}api/inbox" >/dev/null 2>&1; then
  echo "Commerce OS is already running at $URL"; open_it; exit 0
fi
echo "Commerce OS: $URL  (press Ctrl-C to stop)"
( sleep 1; open_it ) &
.venv/bin/python services/workers/publisher.py &     # the only program that can write to a store
WORKER=$!
.venv/bin/python services/local_api/server.py --port "$PORT" &
SERVER=$!
stop() { trap - EXIT INT TERM; kill "$SERVER" "$WORKER" 2>/dev/null || true; wait 2>/dev/null || true; exit 0; }
trap stop EXIT INT TERM
wait "$SERVER"      # waiting in the background is what lets a stop signal act right away
