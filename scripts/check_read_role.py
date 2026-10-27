#!/usr/bin/env python3
"""Verify a storefront's read-only catalog role, and compare its live category/tag lists with the mapping.

Usage:
    python3 scripts/check_read_role.py <storefront-id> [--env production]

Read-only by construction: every session runs with default_transaction_read_only=on, the only queries
are catalog/privilege lookups and SELECTs on categories and tags, and nothing is ever written. The
connection URL and password are never printed. Requires `psql` (e.g. `brew install libpq`).
See docs/runbooks/read-only-role.md.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

REPO = Path(__file__).resolve().parent.parent
ALLOWED = ("products", "categories", "tags")
WRITE_PRIVILEGES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
PSQL_CANDIDATES = ("psql", "/opt/homebrew/opt/libpq/bin/psql", "/usr/local/opt/libpq/bin/psql")


def parse_dotenv(text: str) -> dict:
    """Parse KEY=VALUE lines. Comments and blank lines are skipped; surrounding quotes are removed."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def pg_env_from_url(url: str) -> dict:
    """Turn a postgresql:// URL into libpq environment variables, so the URL never appears in argv."""
    u = urlparse(url)
    if u.scheme not in ("postgres", "postgresql"):
        raise ValueError("connection string must start with postgresql://")
    if not (u.hostname and u.username and u.path.strip("/")):
        raise ValueError("connection string needs a user, host and database")
    query = {k: v[-1] for k, v in parse_qs(u.query).items()}
    env = {
        "PGHOST": u.hostname,
        "PGPORT": str(u.port or 5432),
        "PGUSER": unquote(u.username),
        "PGDATABASE": unquote(u.path.lstrip("/")),
        "PGSSLMODE": query.get("sslmode", "require"),
        "PGCONNECT_TIMEOUT": "10",
        "PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=15000",
        "PGAPPNAME": "commerce-os-read-check",
    }
    if u.password:
        env["PGPASSWORD"] = unquote(u.password)
    return env


def redact(text: str, secrets) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "<redacted>")
    return text


def evaluate(role: dict, memberships: list, privileges: dict) -> list:
    """Return a list of (ok, message). `privileges` maps table -> {privilege: bool}."""
    results = []
    flags = {k: role.get(k) for k in ("rolsuper", "rolcreaterole", "rolcreatedb", "rolbypassrls", "rolreplication")}
    granted = [k for k, v in flags.items() if v]
    results.append((not granted, "role attributes: none elevated" if not granted else f"role has {', '.join(granted)}"))
    results.append((not memberships, "member of no other role" if not memberships
                    else f"member of other roles: {', '.join(memberships)}"))
    for table in ALLOWED:
        ok = privileges.get(table, {}).get("SELECT") is True
        results.append((ok, f"SELECT on {table}: {'allowed' if ok else 'MISSING'}"))
    leaked = sorted(t for t, p in privileges.items() if t not in ALLOWED and p.get("SELECT"))
    results.append((not leaked, "SELECT denied on every other table" if not leaked
                    else f"SELECT allowed on non-catalog tables: {', '.join(leaked)}"))
    writable = sorted(f"{t}.{priv}" for t, p in privileges.items() for priv in WRITE_PRIVILEGES if p.get(priv))
    results.append((not writable, "no write privileges" if not writable else f"write privileges: {', '.join(writable)}"))
    return results


def evaluate_rls(role_name: str, rls: dict) -> list:
    """`rls` maps catalog table -> {"rls": bool, "policies": [{"roles": [...], "cmd": "SELECT"|"ALL"|...}]}.

    A table with row-level security on and no SELECT policy for this role (or PUBLIC) grants SELECT but
    returns zero rows, which would look like an empty catalog rather than a misconfiguration.
    """
    results = []
    for table in ALLOWED:
        info = rls.get(table, {"rls": False, "policies": []})
        if not info["rls"]:
            results.append((True, f"{table}: row-level security off"))
            continue
        readable = any(p["cmd"] in ("SELECT", "ALL") and (role_name in p["roles"] or "public" in p["roles"])
                       for p in info["policies"])
        results.append((readable, f"{table}: row-level security on, "
                        + ("a policy lets this role read it" if readable else "NO policy for this role (it would see zero rows)")))
    return results


def compare(entries: list, live: list, env: str) -> list:
    """Compare mapping entries (categories or tags) with live rows [{id, name, slug}] for one environment."""
    notes = []
    matched = set()
    for e in entries:
        name = e["name"].get(env)
        if e["status"] == "proposed_new" or name is None:
            continue
        known_id = e["id"].get(env)
        hit = (next((r for r in live if r["id"] == known_id), None) if known_id else None) \
            or (next((r for r in live if e.get("slug") and r["slug"] == e["slug"]), None)) \
            or next((r for r in live if r["name"] == name), None)
        if not hit:
            notes.append(f"in mapping, not live: {e['key']} ({name})")
            continue
        matched.add(hit["id"])
        if known_id and hit["id"] != known_id:
            notes.append(f"id differs: {e['key']}")
        elif not known_id:
            notes.append(f"id can be recorded: {e['key']} → {hit['id']}")
        if hit["name"] != name:
            notes.append(f"name differs: {e['key']} mapping '{name}', live '{hit['name']}'")
        if e.get("slug") is None and hit["slug"]:
            notes.append(f"slug can be recorded: {e['key']} → {hit['slug']}")
    for r in live:
        if r["id"] not in matched:
            notes.append(f"live, not in mapping: {r['name']} ({r['slug']})")
    return notes


class Psql:
    def __init__(self, env: dict):
        self.bin = next((p for p in PSQL_CANDIDATES if shutil.which(p) or Path(p).exists()), None)
        if not self.bin:
            raise SystemExit("psql not found. Install it with: brew install libpq")
        self.env = {**os.environ, **env}
        self.secrets = [env.get("PGPASSWORD")]

    def rows(self, sql: str) -> list:
        """Run one query; return rows as lists of strings. JSON output avoids delimiter parsing."""
        wrapped = f"SELECT coalesce(json_agg(q), '[]') FROM ({sql}) q"
        r = subprocess.run([self.bin, "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1", "-c", wrapped],
                           env=self.env, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise SystemExit("query failed: " + redact(r.stderr.strip(), self.secrets))
        return json.loads(r.stdout.strip() or "[]")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("storefront")
    ap.add_argument("--env", default="production", help="mapping environment to compare against")
    args = ap.parse_args(argv)

    cfg_path = REPO / "config" / "storefronts.local.json"
    if not cfg_path.exists():
        raise SystemExit("config/storefronts.local.json not found; run /setup-storefront first")
    entry = next((s for s in json.loads(cfg_path.read_text())["storefronts"] if s["id"] == args.storefront), None)
    if not entry:
        raise SystemExit(f"no storefront '{args.storefront}' in config/storefronts.local.json")
    key = f"{entry['env_prefix']}_DB_URL"
    env_file = REPO / ".env"
    url = parse_dotenv(env_file.read_text()).get(key) if env_file.exists() else None
    url = url or os.environ.get(key)
    if not url:
        raise SystemExit(f"{key} is not set in .env")

    pg = Psql(pg_env_from_url(url))
    role = pg.rows("SELECT current_user AS user, current_database() AS db, rolsuper, rolcreaterole, rolcreatedb, "
                   "rolbypassrls, rolreplication FROM pg_roles WHERE rolname = current_user")[0]
    memberships = [r["rolname"] for r in pg.rows(
        "SELECT b.rolname FROM pg_auth_members m JOIN pg_roles b ON b.oid = m.roleid "
        "WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = current_user)")]
    privs = {}
    for r in pg.rows(
            "SELECT c.relname AS t, "
            + ", ".join(f"has_table_privilege(c.oid, '{p}') AS \"{p}\"" for p in ("SELECT",) + WRITE_PRIVILEGES)
            + " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
              "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')"):
        privs[r.pop("t")] = r

    rls = {}
    for r in pg.rows(
            "SELECT c.relname AS t, c.relrowsecurity AS rls, "
            "coalesce(json_agg(json_build_object('roles', p.roles, 'cmd', p.cmd)) FILTER (WHERE p.policyname IS NOT NULL), '[]') AS policies "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_policies p ON p.schemaname = n.nspname AND p.tablename = c.relname "
            "WHERE n.nspname = 'public' AND c.relname IN ('products', 'categories', 'tags') GROUP BY c.relname, c.relrowsecurity"):
        rls[r.pop("t")] = r

    print(f"{args.storefront}: connected as {role['user']} to database {role['db']} (read-only session)")
    results = evaluate(role, memberships, privs) + evaluate_rls(role["user"], rls)
    for ok, msg in results:
        print(f"  {'✓' if ok else '✗'} {msg}")
    passed = all(ok for ok, _ in results)

    if passed:
        counts = pg.rows("SELECT (SELECT count(*) FROM public.products) AS products, "
                         "(SELECT count(*) FROM public.categories) AS categories, (SELECT count(*) FROM public.tags) AS tags")[0]
        print("\nrows visible: " + ", ".join(f"{k} {v}" for k, v in counts.items()))

    mapping_path = REPO / entry["mapping"]
    if passed and mapping_path.exists():
        mapping = json.loads(mapping_path.read_text())
        for kind in ("categories", "tags"):
            live = pg.rows(f"SELECT id, name, slug FROM public.{kind} ORDER BY name")
            notes = compare(mapping[kind], live, args.env)
            print(f"\n{kind} vs mapping v{mapping['version']} ({args.env}): "
                  + ("matches" if not notes else f"{len(notes)} difference(s)"))
            for n in notes:
                print(f"  - {n}")
        print("\nNothing was changed. Apply differences with /edit-mappings " + args.storefront)
    elif not passed:
        print("\nRole check failed: fix the grants (docs/runbooks/read-only-role.md) before using this login.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
