"""The local test store: a private Postgres on a Unix socket, with the real structure and invented contents.

Its categories and tags are the mapping's, with test ids, which is what a change set for the test environment
refers to. It has two logins: a read login from the runbook, and a write login that can add products and do
nothing else. Nothing here reads .env or can reach a real store.
"""
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from packages.adapters import artstore_map, updates
from packages.adapters.artstore_pg import PostgresArtStore

REPO = Path(__file__).resolve().parents[2]
STOREFRONTS = REPO / "database" / "storefronts"
ROOT = REPO / ".commerce-os" / "local-store"
PORT = 55434
WRITE_ROLE = "commerce_os_write"
READ_ROLE = "commerce_os_read"
# The write login: read the catalog, add products. No updates, no deletes, nothing else in the database.
WRITE_ROLE_SQL = f"""
CREATE ROLE {WRITE_ROLE} WITH LOGIN CONNECTION LIMIT 3;
ALTER ROLE {WRITE_ROLE} SET statement_timeout = '15s';
GRANT USAGE ON SCHEMA public TO {WRITE_ROLE};
GRANT SELECT ON public.products, public.categories, public.tags TO {WRITE_ROLE};
GRANT INSERT ON public.products TO {WRITE_ROLE};
CREATE POLICY commerce_os_write_read ON public.products FOR SELECT TO {WRITE_ROLE} USING (true);
CREATE POLICY commerce_os_write_add ON public.products FOR INSERT TO {WRITE_ROLE} WITH CHECK (true);
CREATE POLICY commerce_os_write_read ON public.categories FOR SELECT TO {WRITE_ROLE} USING (true);
CREATE POLICY commerce_os_write_read ON public.tags FOR SELECT TO {WRITE_ROLE} USING (true);
"""

# Updates (B-085): only the listing's own columns, never status, slug or id. The same as the runbook's update step,
# made safe to run again, so a test store built before updates existed gets it on its next start.
UPDATE_ROLE_SQL = f"""
GRANT UPDATE ({", ".join(updates.UPDATABLE)}) ON public.products TO {WRITE_ROLE};
DROP POLICY IF EXISTS commerce_os_write_update ON public.products;
CREATE POLICY commerce_os_write_update ON public.products FOR UPDATE TO {WRITE_ROLE} USING (true) WITH CHECK (true);
"""


def _ldb():
    spec = importlib.util.spec_from_file_location("local_storefront_db", REPO / "scripts" / "local_storefront_db.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StoreUnavailable(Exception):
    """The local test store can't run here. Safe to show the owner."""


class LocalStore:
    def __init__(self, storefront: str, root: Path = ROOT, port: int = PORT):
        self.storefront, self.root, self.port = storefront, Path(root), port
        self.ldb = _ldb()
        self.base = STOREFRONTS / storefront
        # Unix socket paths are short and this folder's path may have spaces, so the socket lives in the temp dir.
        tag = f"{os.getuid()}-{hashlib.sha256(str(self.root).encode()).hexdigest()[:8]}"     # the same in every process
        self.cluster = self.ldb.Cluster(self.root / "data", Path(tempfile.gettempdir()) / f"cos-pub-{tag}", port=port)
        self.assets = self.root / "assets"

    def _structure(self) -> dict:
        p = self.base / "catalog-structure.json"
        if not p.exists():
            raise StoreUnavailable("There's no local test store for this storefront yet.")
        return json.loads(p.read_text())

    def up(self, mapping: dict):
        """Start it, building it the first time, and bring its categories and tags up to date with the mapping."""
        self._structure()
        if not self.ldb.available():
            raise StoreUnavailable("Postgres isn't installed, so the local test store can't run. "
                                   "Install it with: brew install postgresql@16")
        fresh = not (self.cluster.data_dir / "PG_VERSION").exists()
        if not self.cluster.running():
            self.cluster.start()
        if fresh:
            self.cluster.run_sql((self.base / "schema.sql").read_text())
            self.cluster.run_sql(self.ldb.runbook_read_role_sql(secrets.token_urlsafe(24)))
            self.cluster.run_sql(WRITE_ROLE_SQL)
        self.cluster.run_sql(UPDATE_ROLE_SQL)
        self.sync(mapping)

    def sync(self, mapping: dict):
        seed = artstore_map.test_seed(mapping)
        lines = []
        for table in ("categories", "tags"):
            for row in seed[table]:
                cols = ", ".join(row)
                vals = ", ".join(self.ldb.lit(v) for v in row.values())
                lines.append(f"INSERT INTO public.{table} ({cols}) VALUES ({vals}) ON CONFLICT DO NOTHING;")
        if lines:
            self.cluster.run_sql("\n".join(lines))

    def down(self, delete: bool = False):
        self.cluster.stop(delete=delete)
        if delete:
            shutil.rmtree(self.root, ignore_errors=True)

    def dsn(self, role: str) -> str:
        return f"host={self.cluster.socket_dir} port={self.port} dbname=postgres user={role}"

    def adapter(self, entry: Optional[dict] = None) -> PostgresArtStore:
        entry = entry or {}
        structure = self._structure()
        profile = json.loads((REPO / "resources" / "catalog-profiles" / f"{structure['catalog_profile']}.json").read_text())

        def live(rows) -> dict:
            tables = self.ldb.read_structure(rows)
            return {"tables": tables, "fingerprint": self.ldb.fingerprint(tables)}
        return PostgresArtStore(self.storefront, artstore_map.ENVIRONMENT, profile, structure,
                                write_dsn=self.dsn(WRITE_ROLE), read_dsn=self.dsn(READ_ROLE),
                                currency=entry.get("currency", "USD"), features=entry.get("features", []), read_structure=live)
