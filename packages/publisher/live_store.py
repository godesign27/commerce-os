"""The live store: the one place that reads the write login and the upload login, for the publishing worker alone.

Nothing here runs unless the owner has turned the live store on (scripts/go_live.py). Before it hands the worker
anything, it proves the logins are as narrow as the runbook says (docs/runbooks/write-role.md): a login that can do
more, or a store that would accept anything but a Draft, stops here, and nothing is written. Every message is safe
to show: it names settings and tables, never a value.
"""
import json
import re
from pathlib import Path
from typing import Dict, List
from urllib.parse import unquote

import psycopg
from psycopg.conninfo import conninfo_to_dict

from packages import onboarding
from packages.adapters import artstore_map
from packages.adapters.artstore_pg import CONNECT, PgRows, PostgresArtStore
from packages.adapters.catalog import ALLOWED, WRITE_PRIVILEGES, _privileges
from packages.publisher.assets import DeliveryError, SupabaseAssetStore
from packages.publisher.local_store import READ_ROLE, WRITE_ROLE, StoreUnavailable, _ldb

REPO = Path(__file__).resolve().parents[2]
ENV_FILE = REPO / ".env"
LIVE = "live"
ADD_ONLY = "products"
SUFFIXES = {"read": "DB_URL", "write": "WRITE_DB_URL", "url": "SUPABASE_URL", "key": "SUPABASE_PUBLISHABLE_KEY",
            "email": "UPLOAD_EMAIL", "password": "UPLOAD_PASSWORD", "bucket": "STORAGE_BUCKET"}
SUPABASE_URL = re.compile(r"^https://([a-z0-9]+)\.supabase\.co/?$")


class LiveNotReady(StoreUnavailable):
    """The live store can't be used yet, and why. Safe to show the owner. Nothing was written."""


def settings(entry: dict, env: Dict[str, str]) -> Dict[str, str]:
    """This store's live settings, or which ones are missing, by name only."""
    prefix = entry.get("env_prefix")
    if not prefix:
        raise LiveNotReady("This store has no settings name in its configuration.")
    names = {k: f"{prefix}_{v}" for k, v in SUFFIXES.items()}
    missing = [n for n in names.values() if not env.get(n)]
    if missing:
        raise LiveNotReady("These settings are missing from .env: " + ", ".join(missing) + ".")
    return {k: env[n] for k, n in names.items()}


def _user_host(dsn: str):
    info = conninfo_to_dict(dsn)
    return unquote(info.get("user") or ""), info.get("host") or ""


def check_settings(found: Dict[str, str]) -> List[str]:
    """Do these logins all belong to one project, and are they the logins the runbook creates?"""
    problems = []
    project = SUPABASE_URL.match(found["url"])
    if not project:
        problems.append("The Supabase URL should look like https://<project-ref>.supabase.co.")
    try:
        read_user, read_host = _user_host(found["read"])
        write_user, write_host = _user_host(found["write"])
    except psycopg.ProgrammingError:
        return problems + ["A database login in .env isn't written correctly."]
    if read_user.split(".")[0] != READ_ROLE:
        problems.append(f"The read login should be {READ_ROLE}.")
    if write_user.split(".")[0] != WRITE_ROLE:
        problems.append(f"The write login should be {WRITE_ROLE}: anything else could do more than the runbook allows.")
    if not write_host or write_host != read_host:
        problems.append("The read and write logins point at different databases.")
    if project:
        for label, user in (("read", read_user), ("write", write_user)):
            if user.partition(".")[2] != project.group(1):
                problems.append(f"The {label} login belongs to a different project than the Supabase URL.")
    if found["key"].startswith("sb_secret_"):
        problems.append("That's the secret key. Commerce OS must never hold it: use the publishable key.")
    return problems


def check_write_login(pg) -> List[str]:
    """Is the connected login as narrow as the runbook says? `pg` has .rows(sql). Empty means yes."""
    problems = []
    role = pg.rows("SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolreplication "
                   "FROM pg_roles WHERE rolname = current_user")[0]
    name = role.pop("rolname")
    if name != WRITE_ROLE:
        problems.append(f"The write login is {name}, not {WRITE_ROLE}.")
    power = sorted(k for k, v in role.items() if v)
    if power:
        problems.append("The write login has powers it must not have: " + ", ".join(power) + ".")
    member = pg.rows("SELECT r.rolname AS name FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid "
                     "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = current_user")
    if member:
        problems.append("The write login is a member of another role: " + ", ".join(r["name"] for r in member) + ".")
    privileges = _privileges(pg)
    for table, row in sorted(privileges.items()):
        wrote = [p for p in WRITE_PRIVILEGES if row.get(p) and not (table == ADD_ONLY and p == "INSERT")]
        if wrote:
            problems.append(f"The write login can do more than add products: {table} ({', '.join(wrote)}).")
        if row.get("SELECT") and table not in ALLOWED:
            problems.append(f"The write login can read beyond the catalog: {table}.")
    if not privileges.get(ADD_ONLY, {}).get("INSERT"):
        problems.append("The write login can't add products.")
    secured = pg.rows("SELECT c.relrowsecurity AS rls, pg_get_userbyid(c.relowner) = current_user AS owner FROM pg_class c "
                      "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relname = 'products'")
    if not secured or not secured[0]["rls"] or secured[0]["owner"]:
        problems.append("The products table doesn't enforce its rules on this login, so Draft can't be guaranteed.")
    policies = pg.rows("SELECT policyname, permissive, with_check FROM pg_policies WHERE schemaname = 'public' "
                       "AND tablename = 'products' AND cmd IN ('INSERT', 'ALL') AND "
                       "(roles && ARRAY[current_user]::name[] OR roles && ARRAY['public']::name[])")
    only_draft = [p for p in policies if re.fullmatch(r"\(*\s*status\s*=\s*'draft'(::text)?\s*\)*", (p["with_check"] or "").strip())]
    if not only_draft or len(only_draft) != len(policies):
        problems.append("The store would let this login add something other than a Draft: its add policy must allow "
                        "only status = 'draft'.")
    return problems


def check_upload_policy(pg, bucket: str) -> List[str]:
    """Uploads must be add-only, into the store's uploads folders. `pg` has .rows(sql)."""
    rows = pg.rows("SELECT policyname, cmd, with_check FROM pg_policies WHERE schemaname = 'storage' "
                   "AND tablename = 'objects' AND policyname LIKE 'commerce_os_%'")
    if not rows:
        return ["The upload rule for images isn't in place in the store."]
    problems = []
    for r in rows:
        check = r["with_check"] or ""
        if r["cmd"] != "INSERT":
            problems.append(f"The upload rule {r['policyname']} allows more than adding images.")
        elif f"'{bucket}'" not in check or "auth.uid()" not in check or "uploads/" not in check:
            problems.append(f"The upload rule {r['policyname']} isn't limited to one login and the uploads folders.")
    return problems


def preflight(found: Dict[str, str], assets_store: SupabaseAssetStore) -> List[str]:
    """Everything that must hold before the worker may write. It reads only, and signs in once to prove the upload login."""
    problems = check_settings(found)
    if problems:
        return problems
    try:
        with psycopg.connect(found["write"], autocommit=True, **CONNECT) as conn:
            rows = PgRows(conn)
            problems += check_write_login(rows)
            problems += check_upload_policy(rows, found["bucket"])
    except psycopg.Error:                                  # its message can quote the login, so it isn't shown
        problems.append("Couldn't connect with the write login.")
    try:
        assets_store.sign_in()
    except DeliveryError as e:
        problems.append(str(e))
    return problems


def _structure_reader():
    ldb = _ldb()

    def live(rows) -> dict:
        tables = ldb.read_structure(rows)
        return {"tables": tables, "fingerprint": ldb.fingerprint(tables)}
    return live


def connect(app, env_file: Path = ENV_FILE):
    """The adapter and image store for the live store, after every check has passed. Raises LiveNotReady otherwise."""
    entry = app.storefront_entry()
    if entry.get("publish_target") != LIVE:
        raise LiveNotReady("The live store isn't turned on.")
    found = settings(entry, onboarding.read_env(env_file))
    images = SupabaseAssetStore(found["url"], found["key"], found["email"], found["password"], found["bucket"])
    problems = preflight(found, images)
    if problems:
        raise LiveNotReady("Publishing to the live store is stopped: " + " ".join(problems))
    structure = app.catalog.structure()
    mapping = app.mapping()
    if not structure or not app.catalog.load() or not mapping:
        raise LiveNotReady("Check the store on Getting started first.")
    profile = json.loads((REPO / "resources" / "catalog-profiles" / f"{entry['catalog_profile']}.json").read_text())
    _, host = _user_host(found["read"])
    adapter = PostgresArtStore(app.storefront, artstore_map.LIVE_ENVIRONMENT, profile, structure,
                               write_dsn=found["write"], read_dsn=found["read"], live_host=host,
                               currency=entry.get("currency", "USD"), features=entry.get("features", []),
                               read_structure=_structure_reader())
    return adapter, images

