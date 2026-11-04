"""First run: what's set up, what's next, and the rules for each step (B-068).

Every step's status comes from what's actually there (config, .env, the catalog copy, the mapping, the brand
context), never from a "finished" flag, so a person can stop and come back, and an existing install simply shows
as done. Nothing here connects to anything; services/local_api/server.py does that and calls these rules.

Credentials: a read-only login and the Claude API key are entered on the local page, checked, and written to
.env (readable by this user only). They're never returned, logged or put in an error. Write logins never come
through here: they stay out of the browser, for the publishing worker alone (AGENTS.md).

Stdlib only; Python 3.9+.
"""
import json
import os
import re
from pathlib import Path
from typing import List, Optional

from packages.adapters.artstore_map import slugify

REPO = Path(__file__).resolve().parents[1]
PROVIDERS = REPO / "resources" / "providers"
PROFILES = REPO / "resources" / "catalog-profiles"
PRODUCT_TYPES = REPO / "resources" / "product-types"
READ_ROLE = "commerce_os_read"
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
ENVIRONMENT = "production"


class SetupError(ValueError):
    """Why a step can't be saved, in words for the owner. Holds no credential."""


# ---------------------------------------------------------------- .env

def read_env(path: Path) -> dict:
    """KEY=VALUE lines. Comments and blank lines are skipped; surrounding quotes are removed."""
    p, out = Path(path), {}
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip().removeprefix("export ").strip()] = value
    return out


def set_env(path: Path, key: str, value: str):
    """Set one value, leaving every other line as it was. The file is readable by this user only."""
    if not ENV_KEY_RE.match(key):
        raise SetupError("That isn't a setting name.")
    if not value or any(c in value for c in "\r\n"):
        raise SetupError("That value can't be saved: it's empty or spans more than one line.")
    p = Path(path)
    lines = p.read_text().splitlines() if p.exists() else []
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(key)}\s*=")
    entry = f"{key}={value}"
    if any(pattern.match(x) for x in lines):
        lines = [entry if pattern.match(x) else x for x in lines]
    else:
        lines.append(entry)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, p)


def scrub(message: str, *secrets) -> str:
    """Take credentials out of a message, whole and in part, before anyone sees it."""
    text = str(message)
    for s in secrets:
        if s:
            text = text.replace(s, "<hidden>")
    return text


def url_password(url: str) -> Optional[str]:
    m = re.match(r"^[a-z]+://[^:/@]+:([^@]+)@", url or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- resources

def _load_all(folder: Path) -> List[dict]:
    return [json.loads(p.read_text()) for p in sorted(Path(folder).glob("*.json"))]


def providers() -> List[dict]:
    return [p for p in _load_all(PROVIDERS) if "storefront" in p.get("used_for", [])]


def profiles() -> List[dict]:
    return _load_all(PROFILES)


def product_types(site_kind: Optional[str]) -> List[dict]:
    """An artist site sells artwork; a product site sells everything else."""
    rows = [{"id": t["id"], "label": t.get("display_name", t["id"])} for t in _load_all(PRODUCT_TYPES)]
    return [t for t in rows if (t["id"] == "artwork") == (site_kind == "artist")]


# ---------------------------------------------------------------- step: your store

def load_config(path: Path) -> dict:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {"version": 1, "storefronts": []}


def env_prefix(storefront: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", storefront.upper()).strip("_")


def save_store(path: Path, storefront: str, body: dict) -> dict:
    """Add or update this store's entry. Writes stay off and uploads unauthorized, whatever is sent."""
    name = (body.get("display_name") or "").strip()
    kind, provider, currency = body.get("site_kind"), body.get("provider"), (body.get("currency") or "").strip().upper()
    if not name:
        raise SetupError("What's the store called?")
    if kind not in ("artist", "product"):
        raise SetupError("Is this an artist site or a product site?")
    if provider not in [p["id"] for p in providers()]:
        raise SetupError("Choose the database your store uses.")
    if not CURRENCY_RE.match(currency):
        raise SetupError("Use a three-letter currency code, such as USD.")
    available = [p["id"] for p in profiles()]
    profile = body.get("catalog_profile") or (available[0] if available else None)
    if profile not in available:
        raise SetupError("That catalog profile doesn't exist.")
    cfg = load_config(path)
    entry = next((s for s in cfg["storefronts"] if s["id"] == storefront), None)
    prefix = (entry or {}).get("env_prefix") or env_prefix(storefront)
    if any(s["id"] != storefront and s.get("env_prefix") == prefix for s in cfg["storefronts"]):
        raise SetupError(f"Another store already uses {prefix}.")
    if entry is None:
        entry = {"id": storefront, "features": []}
        cfg["storefronts"].append(entry)
    entry.update({"display_name": name, "provider": provider, "catalog_profile": profile, "currency": currency,
                  "env_prefix": prefix, "mapping": f"config/mappings/{storefront}.local.json", "site_kind": kind,
                  "brand_context": f"config/brand/{storefront}.local.json",
                  "asset_upload": "not_authorized", "writes_enabled": False})
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    return entry


def record_features(path: Path, storefront: str, features: List[str]):
    cfg = load_config(path)
    for s in cfg["storefronts"]:
        if s["id"] == storefront:
            s["features"] = sorted(features)
    Path(path).write_text(json.dumps(cfg, indent=2) + "\n")


# ---------------------------------------------------------------- step: read-only login

def login_sql() -> str:
    """The script the owner runs in their own database: the runbook's, for any provider. `<password>` is filled in
    by the page, in the browser, with a password that never reaches this server until it's part of the login. The
    policies are always included: a store on any provider can have row-level security on, and without them that
    store's check refuses the login with no way forward."""
    tables = "public.products, public.categories, public.tags"
    lines = [f"CREATE ROLE {READ_ROLE} WITH LOGIN PASSWORD '<password>' CONNECTION LIMIT 3;",
             f"ALTER ROLE {READ_ROLE} SET default_transaction_read_only = on;",
             f"ALTER ROLE {READ_ROLE} SET statement_timeout = '15s';",
             "DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO " + READ_ROLE
             + "', current_database()); END $$;",
             f"GRANT USAGE ON SCHEMA public TO {READ_ROLE};",
             f"GRANT SELECT ON {tables} TO {READ_ROLE};",
             "",
             "-- Where row-level security is on, the login needs a read policy on exactly these three tables.",
             "-- Where it's off, these change nothing."]
    lines += [f"CREATE POLICY commerce_os_read_catalog ON public.{t} FOR SELECT TO {READ_ROLE} USING (true);"
              for t in ("products", "categories", "tags")]
    return "\n".join(lines)


def login_example(provider: Optional[str]) -> str:
    if provider == "supabase":
        return (f"postgresql://{READ_ROLE}.<project-ref>:<password>@<pooler host>:5432/postgres?sslmode=require")
    return f"postgresql://{READ_ROLE}:<password>@<host>/<database>?sslmode=require"


def login_where(provider: Optional[str]) -> str:
    if provider == "supabase":
        return ("Run it in your Supabase project's SQL Editor. Then copy the host from Connect → Session pooler; "
                "the username is the role name, a dot, and your project ref.")
    return "Run it in your database console's SQL Editor (on Neon, not the Roles page), then build the login below."


# ---------------------------------------------------------------- step: check the store

def fit(tables: dict, profile: dict) -> List[str]:
    """Why this store's structure doesn't match the catalog profile. Empty means it fits."""
    out = []
    for t in profile.get("catalog_tables", []):
        if not tables.get(t, {}).get("columns"):
            out.append(f"The store has no {t} table Commerce OS can see.")
    product = profile.get("product", {})
    columns = tables.get(product.get("table", "products"), {}).get("columns", {})
    needed = list(product.get("required_on_insert", []))
    for part in ("status", "category", "images", "tags"):
        col = (product.get(part) or {}).get("column")
        if col:
            needed.append(col)
    missing = sorted({c for c in needed if c not in columns})
    if columns and missing:
        out.append("Its products table is missing: " + ", ".join(missing) + ".")
    return out


def detect_features(tables: dict, profile: dict) -> List[str]:
    """Which optional features the store really has, judged from its columns."""
    found = []
    for name, feature in profile.get("optional_features", {}).items():
        m = re.fullmatch(r"(\w+)\.(\w+)", feature.get("column", ""))
        if m and m.group(2) in tables.get(m.group(1), {}).get("columns", {}):
            found.append(name)
    return found


# ---------------------------------------------------------------- step: categories and tags

def _merge(live: List[dict], chosen: List[str], old: List[dict], kind: str) -> List[dict]:
    known = {r["slug"] or r["id"] for r in live}
    unknown = [c for c in chosen if c not in known]
    if unknown:
        raise SetupError(f"These {kind} aren't in the store: " + ", ".join(unknown))
    out, used = [], set()
    for r in live:
        ref = r["slug"] or r["id"]
        prior = next((o for o in old if (o.get("id") or {}).get(ENVIRONMENT) == r["id"] or (r["slug"] and o.get("slug") == r["slug"])), None)
        entry = dict(prior) if prior else {"key": slugify(r["slug"] or r["name"])}
        used.add(id(prior))
        entry["name"] = dict(entry.get("name") or {}, **{ENVIRONMENT: r["name"]})
        entry["id"] = dict(entry.get("id") or {}, **{ENVIRONMENT: r["id"]})
        entry["slug"] = r["slug"]
        entry["status"] = "in_scope" if ref in chosen else "excluded"
        out.append(entry)
    return out + [o for o in old if id(o) not in used]       # entries the store doesn't list stay as they were


def build_mapping(storefront: str, snapshot: dict, choices: dict, old: Optional[dict], today: str) -> dict:
    """The mapping, from the store's real lists and the owner's choices. Ids come only from the store."""
    if not isinstance(choices, dict) or set(choices) != {"categories", "tags", "tier_types", "product_types"}:
        raise SetupError("Send categories, tags, tier_types and product_types.")
    old = old or {}
    chosen = choices["categories"]
    if not chosen:
        raise SetupError("Choose at least one category.")
    tiers = [t.strip() for t in choices["tier_types"] if isinstance(t, str) and t.strip()]
    if not tiers:
        raise SetupError("Say how pieces are sold: at least one tier type.")
    live_tiers = snapshot.get("tier_types") or []
    if live_tiers and [t for t in tiers if t not in live_tiers]:
        raise SetupError("Those tier types aren't in the store: " + ", ".join(t for t in tiers if t not in live_tiers))
    categories = _merge(snapshot["categories"], chosen, old.get("categories", []), "categories")
    by_ref = {(c.get("slug") or (c.get("id") or {}).get(ENVIRONMENT)): c["key"] for c in categories}
    types = dict(old.get("product_types") or {})
    picked = {k: v for k, v in (choices["product_types"] or {}).items() if v and v.get("category")}
    if not picked:
        raise SetupError("Say which category at least one kind of product goes in.")
    for ptype, choice in picked.items():
        if choice["category"] not in chosen:
            raise SetupError(f"{ptype} goes in a category you haven't chosen.")
        row = {"category": by_ref[choice["category"]], "type_tags": (types.get(ptype) or {}).get("type_tags", []), "proposed": False}
        alternative = choice.get("alternative")
        if alternative:
            if alternative not in chosen:
                raise SetupError(f"{ptype}'s other category isn't one you've chosen.")
            row["alternative_categories"] = [by_ref[alternative]]
        types[ptype] = row
    version = int(old.get("version") or 0) + 1
    changes = list(old.get("changes") or []) + [{"version": version, "date": today, "by": "owner, on the Getting started page",
                                                  "summary": "Chosen from the store's own lists."}]
    return {"storefront": storefront, "version": version, "environments": [ENVIRONMENT], "changes": changes,
            "tier_types": tiers, "categories": categories,
            "tags": _merge(snapshot["tags"], choices["tags"], old.get("tags", []), "tags"), "product_types": types}


def mapping_ready(mapping: Optional[dict]) -> bool:
    m = mapping or {}
    return (any(c.get("status") == "in_scope" for c in m.get("categories", [])) and bool(m.get("tier_types"))
            and any(isinstance(t, dict) and t.get("category") for t in (m.get("product_types") or {}).values()))


# ---------------------------------------------------------------- the steps

STEPS = [("store", "Your store"), ("login", "Read-only login"), ("check", "Check the store"),
         ("mapping", "Categories and tags"), ("key", "Claude API key"), ("voice", "Voice"), ("photos", "First photos")]
REQUIRED = ("store", "login", "check", "mapping", "key", "voice")   # first photos is where setup ends, not a gate


def steps(*, entry: Optional[dict], login: bool, snapshot: bool, mapping: Optional[dict], key: bool, brand: bool,
          photos: int) -> dict:
    """Each step in order, whether it's done, and which comes next. A step needs the ones it depends on."""
    store = bool(entry and entry.get("provider") and entry.get("site_kind") and entry.get("display_name"))
    done = {"store": store, "login": store and login, "check": store and login and snapshot,
            "mapping": store and mapping_ready(mapping), "key": key, "voice": brand, "photos": photos > 0}
    rows = [{"id": k, "label": v, "done": bool(done[k])} for k, v in STEPS]
    return {"steps": rows, "complete": all(done[k] for k in REQUIRED),
            "next": next((r["id"] for r in rows if not r["done"]), None)}
