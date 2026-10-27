#!/usr/bin/env python3
"""Run a throwaway local copy of a storefront's catalog tables, and check the real ones for drift (B-029).

Usage:
    python3 scripts/local_storefront_db.py up storefront-a        fresh local copy: schema, seed, read role
    python3 scripts/local_storefront_db.py status storefront-a    is it running, and how to connect
    python3 scripts/local_storefront_db.py down storefront-a      stop it and delete its data
    python3 scripts/local_storefront_db.py drift storefront-a     compare the live catalog structure
                                                                  with catalog-structure.json (read-only)
    python3 scripts/local_storefront_db.py snapshot storefront-a  print the live structure as JSON (read-only)

The local copy is a private Postgres cluster under .commerce-os/local-db/ (gitignored). It listens on a
Unix socket only, never on a network port, and is rebuilt from scratch on every `up`. It's for adapter
and contract tests: it never touches, and never migrates, a real storefront (PRD §18).

`drift` and `snapshot` connect to the real storefront with its read-only login (<PREFIX>_DB_URL in
.env) in a read-only session, and read only table structure from the system catalogs: no rows.
Requires PostgreSQL server binaries (e.g. `brew install postgresql@16`) and psql.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STOREFRONTS = REPO / "database" / "storefronts"
STATE = REPO / ".commerce-os" / "local-db"
RUNBOOK = REPO / "docs" / "runbooks" / "read-only-role.md"
CATALOG_TABLES = ("categories", "products", "tags")
READ_ROLE = "commerce_os_read"
PORT = 55432

_spec = importlib.util.spec_from_file_location("check_read_role", REPO / "scripts" / "check_read_role.py")
crr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crr)


# ---------------------------------------------------------------- structure and fingerprint

STRUCTURE_COLUMNS_SQL = (
    "SELECT c.relname AS t, a.attname AS col, format_type(a.atttypid, a.atttypmod) AS type, "
    "a.attnotnull AS not_null, pg_get_expr(d.adbin, d.adrelid) AS \"default\" "
    "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    "WHERE n.nspname = 'public' AND c.relname IN ('categories', 'products', 'tags') "
    "AND a.attnum > 0 AND NOT a.attisdropped"
)
STRUCTURE_CONSTRAINTS_SQL = (
    "SELECT c.relname AS t, k.conname AS name, pg_get_constraintdef(k.oid) AS def "
    "FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relname IN ('categories', 'products', 'tags')"
)


def normalize_constraint(defn: str) -> str:
    """pg_get_constraintdef qualifies a referenced table only when it's off the search_path."""
    return re.sub(r"REFERENCES public\.", "REFERENCES ", defn)


def structure(columns: list, constraints: list) -> dict:
    """Canonical catalog structure: order-insensitive, so column order differences don't count."""
    tables = {t: {"columns": {}, "constraints": {}} for t in CATALOG_TABLES}
    for r in columns:
        tables[r["t"]]["columns"][r["col"]] = {"type": r["type"], "not_null": bool(r["not_null"]),
                                              "default": r["default"]}
    for r in constraints:
        tables[r["t"]]["constraints"][r["name"]] = normalize_constraint(r["def"])
    return tables


def fingerprint(tables: dict) -> str:
    """sha256 of the canonical structure. Proposed as the schema fingerprint a mapping binds to (B-028)."""
    return hashlib.sha256(json.dumps(tables, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_structure(pg) -> dict:
    return structure(pg.rows(STRUCTURE_COLUMNS_SQL), pg.rows(STRUCTURE_CONSTRAINTS_SQL))


def diff(expected: dict, live: dict) -> list:
    """Human-readable differences between two canonical structures."""
    notes = []
    for t in CATALOG_TABLES:
        e, l = expected.get(t, {}), live.get(t, {})
        ec, lc = e.get("columns", {}), l.get("columns", {})
        if not lc:
            notes.append(f"{t}: table missing")
            continue
        for col in sorted(set(ec) - set(lc)):
            notes.append(f"{t}.{col}: column removed")
        for col in sorted(set(lc) - set(ec)):
            notes.append(f"{t}.{col}: new column ({lc[col]['type']})")
        for col in sorted(set(ec) & set(lc)):
            for k in ("type", "not_null", "default"):
                if ec[col][k] != lc[col][k]:
                    notes.append(f"{t}.{col}: {k} changed from {ec[col][k]!r} to {lc[col][k]!r}")
        ek, lk = e.get("constraints", {}), l.get("constraints", {})
        for name in sorted(set(ek) | set(lk)):
            if ek.get(name) != lk.get(name):
                notes.append(f"{t}: constraint {name} " + (
                    "removed" if name not in lk else "added" if name not in ek
                    else f"changed from {ek[name]!r} to {lk[name]!r}"))
    return notes


# ---------------------------------------------------------------- seed

def lit(value) -> str:
    """A SQL literal for a seed value. Seed files are ours, but quote properly anyway."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, dict)):
        return lit(json.dumps(value)) + "::jsonb"
    return "'" + str(value).replace("'", "''") + "'"


def seed_sql(seed: dict) -> str:
    out = []
    for table in ("categories", "tags", "products"):
        for row in seed[table]:
            row = {k: v for k, v in row.items() if k != "case"}   # `case` documents the row; not a column
            cols = ", ".join(row)
            vals = ", ".join(lit(v) for v in row.values())
            out.append(f"INSERT INTO public.{table} ({cols}) VALUES ({vals});")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- the read role, from the runbook

def runbook_read_role_sql(password: str) -> str:
    """The Supabase §2a role script, taken from the runbook itself so the runbook is what gets tested."""
    text = RUNBOOK.read_text()
    section = text.split("## 2a.", 1)[1].split("## 2b.", 1)[0]
    blocks = re.findall(r"```sql\n(.*?)```", section, re.S)
    script = next(b for b in blocks if "CREATE ROLE" in b)
    if "<password from step 1>" not in script:
        raise SystemExit("runbook §2a no longer has the password placeholder; update local_storefront_db.py")
    return script.replace("<password from step 1>", password)


# ---------------------------------------------------------------- local cluster

def server_bin(name: str) -> str:
    """Server binaries come from the same install as `postgres`, so initdb matches the server."""
    pg = shutil.which("postgres")
    candidates = [Path(pg).resolve().parent / name] if pg else []
    candidates += sorted(Path("/opt/homebrew/opt").glob(f"postgresql@*/bin/{name}"), reverse=True)
    for c in candidates:
        if c.exists():
            return str(c)
    raise SystemExit("PostgreSQL server binaries not found. Install them with: brew install postgresql@16")


def available() -> bool:
    try:
        server_bin("initdb")
        return True
    except SystemExit:
        return False


# macOS: without a valid locale in its environment the server refuses to start ("postmaster became
# multithreaded during startup").
SERVER_ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


class Cluster:
    """A private Postgres cluster: Unix socket only, trust auth for the owner, deleted on stop()."""

    def __init__(self, data_dir: Path, socket_dir: Path, port: int = PORT):
        self.data_dir, self.socket_dir, self.port = Path(data_dir), Path(socket_dir), port

    def env(self, user: str = None, password: str = None, read_only: bool = False) -> dict:
        env = {"PGHOST": str(self.socket_dir), "PGPORT": str(self.port), "PGDATABASE": "postgres",
               "PGAPPNAME": "commerce-os-local"}
        if user:
            env["PGUSER"] = user
        if password:
            env["PGPASSWORD"] = password
        if read_only:
            env["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=15000"
        return env

    def running(self) -> bool:
        r = subprocess.run([server_bin("pg_ctl"), "status", "-D", str(self.data_dir)], capture_output=True,
                           env=SERVER_ENV)
        return r.returncode == 0

    def start(self):
        self.socket_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.socket_dir, 0o700)
        if not (self.data_dir / "PG_VERSION").exists():
            self.data_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([server_bin("initdb"), "-D", str(self.data_dir), "-A", "trust", "-E", "UTF8",
                            "--locale=C", "-U", "postgres"], check=True, capture_output=True, env=SERVER_ENV)
        opts = f"-k {self.socket_dir} -p {self.port} -c listen_addresses='' -c fsync=off"
        subprocess.run([server_bin("pg_ctl"), "start", "-w", "-D", str(self.data_dir), "-o", opts,
                        "-l", str(self.data_dir / "server.log")], check=True, capture_output=True, env=SERVER_ENV)

    def stop(self, delete: bool = True):
        if (self.data_dir / "PG_VERSION").exists() and self.running():
            subprocess.run([server_bin("pg_ctl"), "stop", "-w", "-m", "fast", "-D", str(self.data_dir)],
                           check=True, capture_output=True, env=SERVER_ENV)
        if delete:
            shutil.rmtree(self.data_dir, ignore_errors=True)
            shutil.rmtree(self.socket_dir, ignore_errors=True)

    def run_sql(self, sql: str, user: str = "postgres"):
        """Run a script as the cluster owner, stopping at the first error."""
        psql = crr.Psql(self.env(user=user))
        r = subprocess.run([psql.bin, "-X", "-q", "-v", "ON_ERROR_STOP=1"], input=sql, env=psql.env,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip())

    def psql(self, user: str = "postgres", password: str = None, read_only: bool = False):
        return crr.Psql(self.env(user=user, password=password, read_only=read_only))


def load(cluster: Cluster, storefront: str) -> str:
    """Load schema, seed and the runbook's read role. Returns the read role's generated password."""
    base = STOREFRONTS / storefront
    cluster.run_sql((base / "schema.sql").read_text())
    cluster.run_sql(seed_sql(json.loads((base / "seed.json").read_text())))
    password = secrets.token_urlsafe(24)
    cluster.run_sql(runbook_read_role_sql(password))
    return password


def socket_dir_for(storefront: str) -> Path:
    # Unix socket paths are limited to ~100 characters, so the socket lives in the system temp dir.
    return Path(tempfile.gettempdir()) / f"commerce-os-{os.getuid()}-{storefront}"


def local_cluster(storefront: str) -> Cluster:
    return Cluster(STATE / storefront / "data", socket_dir_for(storefront))


# ---------------------------------------------------------------- commands

def require_storefront(storefront: str) -> Path:
    base = STOREFRONTS / storefront
    if not (base / "schema.sql").exists():
        raise SystemExit(f"no local stand-in for '{storefront}' in database/storefronts/")
    return base


def live_psql(storefront: str):
    cfg_path = REPO / "config" / "storefronts.local.json"
    if not cfg_path.exists():
        raise SystemExit("config/storefronts.local.json not found; run /setup-storefront first")
    entry = next((s for s in json.loads(cfg_path.read_text())["storefronts"] if s["id"] == storefront), None)
    if not entry:
        raise SystemExit(f"no storefront '{storefront}' in config/storefronts.local.json")
    key = f"{entry['env_prefix']}_DB_URL"
    env_file = REPO / ".env"
    url = (crr.parse_dotenv(env_file.read_text()).get(key) if env_file.exists() else None) or os.environ.get(key)
    if not url:
        raise SystemExit(f"{key} is not set in .env")
    return crr.Psql(crr.pg_env_from_url(url))   # read-only session, forced by pg_env_from_url


def cmd_up(storefront: str) -> int:
    require_storefront(storefront)
    cluster = local_cluster(storefront)
    cluster.stop(delete=True)
    cluster.start()
    password = load(cluster, storefront)
    expected = json.loads((STOREFRONTS / storefront / "catalog-structure.json").read_text())["tables"]
    notes = diff(expected, read_structure(cluster.psql()))
    if notes:
        cluster.stop(delete=True)
        raise SystemExit("schema.sql doesn't reproduce catalog-structure.json:\n  - " + "\n  - ".join(notes))
    (STATE / storefront).mkdir(parents=True, exist_ok=True)
    pw_file = STATE / storefront / "read-role-password"
    pw_file.write_text(password + "\n")
    os.chmod(pw_file, 0o600)
    counts = cluster.psql().rows("SELECT (SELECT count(*) FROM public.products) AS products, "
                                 "(SELECT count(*) FROM public.categories) AS categories, "
                                 "(SELECT count(*) FROM public.tags) AS tags")[0]
    print(f"{storefront}: local copy running (Unix socket only)")
    print("  rows: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return cmd_status(storefront)


def cmd_status(storefront: str) -> int:
    cluster = local_cluster(storefront)
    if not (cluster.data_dir / "PG_VERSION").exists() or not cluster.running():
        print(f"{storefront}: not running. Start it with: python3 scripts/local_storefront_db.py up {storefront}")
        return 1
    print(f"{storefront}: running")
    print(f"  owner:     PGHOST={cluster.socket_dir} PGPORT={cluster.port} PGUSER=postgres psql postgres")
    print(f"  read role: PGHOST={cluster.socket_dir} PGPORT={cluster.port} PGUSER={READ_ROLE} psql postgres")
    print(f"  (read role password: .commerce-os/local-db/{storefront}/read-role-password)")
    return 0


def cmd_down(storefront: str) -> int:
    local_cluster(storefront).stop(delete=True)
    shutil.rmtree(STATE / storefront, ignore_errors=True)
    print(f"{storefront}: local copy stopped and deleted")
    return 0


def cmd_snapshot(storefront: str) -> int:
    tables = read_structure(live_psql(storefront))
    print(json.dumps({"tables": tables, "fingerprint": fingerprint(tables)}, indent=2, sort_keys=True))
    return 0


def cmd_drift(storefront: str) -> int:
    base = require_storefront(storefront)
    expected = json.loads((base / "catalog-structure.json").read_text())
    live = read_structure(live_psql(storefront))
    notes = diff(expected["tables"], live)
    print(f"{storefront}: live catalog structure vs catalog-structure.json "
          f"(verified {expected['verified'][-1]['date']})")
    if not notes:
        print(f"  matches (fingerprint {fingerprint(live)[:12]})")
        return 0
    for n in notes:
        print(f"  - {n}")
    print("\nThe storefront's catalog tables changed. Review the change, then update schema.sql, "
          "catalog-structure.json and the catalog profile together.")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["up", "status", "down", "drift", "snapshot"])
    ap.add_argument("storefront")
    args = ap.parse_args(argv)
    return {"up": cmd_up, "status": cmd_status, "down": cmd_down,
            "drift": cmd_drift, "snapshot": cmd_snapshot}[args.command](args.storefront)


if __name__ == "__main__":
    sys.exit(main())
