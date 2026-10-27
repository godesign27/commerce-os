#!/usr/bin/env python3
"""Apply the operational migrations and the smoke test inside ONE transaction, then roll back.

Usage:
    python3 scripts/test_operational_db.py

Reads COMMERCE_OS_TEST_DB_URL from the environment or .env. Point it at a disposable database or a
Neon branch made for testing, never at a storefront. Nothing persists: the whole run is wrapped in
BEGIN ... ROLLBACK, and the script refuses if the commerce_os schema already exists there.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MIGRATIONS = REPO / "database" / "operational" / "migrations"
SMOKE = REPO / "database" / "operational" / "tests" / "smoke.sql"

_spec = importlib.util.spec_from_file_location("check_read_role", REPO / "scripts" / "check_read_role.py")
_crr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_crr)


def build_script() -> str:
    parts = ["\\set ON_ERROR_STOP on", "BEGIN;"]
    for m in sorted(MIGRATIONS.glob("*.sql")):
        parts.append(f"-- >>> {m.name}\n{m.read_text()}")
    parts.append(f"-- >>> {SMOKE.name}\n{SMOKE.read_text()}")
    parts.append("ROLLBACK;")
    return "\n".join(parts) + "\n"


def main() -> int:
    key = "COMMERCE_OS_TEST_DB_URL"
    env_file = REPO / ".env"
    url = os.environ.get(key) or (_crr.parse_dotenv(env_file.read_text()).get(key) if env_file.exists() else None)
    if not url:
        print(f"{key} is not set; skipping the live database test.")
        return 0
    pg_env = _crr.pg_env_from_url(url)
    pg_env.pop("PGOPTIONS", None)   # this session must create objects (then roll them back)
    psql = _crr.Psql(pg_env)
    exists = psql.rows("SELECT 1 AS x FROM pg_namespace WHERE nspname = 'commerce_os'")
    if exists:
        raise SystemExit("refusing: schema commerce_os already exists in this database; use an empty test database")
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
        f.write(build_script())
        path = f.name
    try:
        r = subprocess.run([psql.bin, "-X", "-q", "-f", path], env=psql.env, capture_output=True, text=True, timeout=300)
    finally:
        os.unlink(path)
    out = _crr.redact(r.stdout + r.stderr, psql.secrets)
    for line in out.splitlines():
        if "ok" in line or "SMOKE" in line or "ERROR" in line:
            print(line.replace("psql:", "").strip())
    passed = r.returncode == 0 and "SMOKE PASSED" in out
    print("\nlive database test:", "PASSED (rolled back)" if passed else "FAILED (rolled back)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
