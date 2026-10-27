"""The local Storefront A stand-in (B-029): schema.sql, catalog-structure.json, seed.json and the runbook agree.

Static checks run everywhere. The live checks start a private Postgres cluster in a temp dir (Unix socket
only) and are skipped when PostgreSQL server binaries aren't installed.
"""
import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests._helpers import REPO

spec = importlib.util.spec_from_file_location("local_storefront_db", REPO / "scripts" / "local_storefront_db.py")
lsd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lsd)

BASE = REPO / "database" / "storefronts" / "storefront-a"
SNAPSHOT = json.loads((BASE / "catalog-structure.json").read_text())
SEED = json.loads((BASE / "seed.json").read_text())
PROFILE = json.loads((REPO / "resources" / "catalog-profiles" / "replit-artstore-v1.json").read_text())
CONFIG = json.loads((REPO / "config" / "storefronts.example.json").read_text())
TABLES = SNAPSHOT["tables"]


def parse_schema_sql(text: str) -> dict:
    """Parse schema.sql's catalog tables. The file keeps pg_dump's one-column-per-line layout on purpose."""
    tables = {t: {"columns": {}, "constraints": {}} for t in lsd.CATALOG_TABLES}
    for t, body in re.findall(r"CREATE TABLE public\.(\w+) \((.*?)\n\);", text, re.S):
        if t not in tables:
            continue
        for line in body.strip().splitlines():
            m = re.match(r"\s*(\w+) (.+?)(?: DEFAULT (.+?))?( NOT NULL)?,?$", line)
            name, typ, default, not_null = m.groups()
            tables[t]["columns"][name] = {"type": typ, "not_null": bool(not_null), "default": default}
    for t, name, defn in re.findall(r"ALTER TABLE ONLY public\.(\w+) ADD CONSTRAINT (\w+) (.+);", text):
        if t in tables:
            tables[t]["constraints"][name] = lsd.normalize_constraint(defn)
    return tables


class Snapshot(unittest.TestCase):
    def test_fingerprint_matches_the_recorded_tables(self):
        self.assertEqual(SNAPSHOT["fingerprint"], lsd.fingerprint(TABLES))

    def test_fingerprint_ignores_column_order(self):
        reordered = {t: {"columns": dict(reversed(list(v["columns"].items()))), "constraints": v["constraints"]}
                     for t, v in TABLES.items()}
        self.assertEqual(lsd.fingerprint(reordered), SNAPSHOT["fingerprint"])

    def test_covers_exactly_the_profile_catalog_tables(self):
        self.assertEqual(sorted(TABLES), sorted(PROFILE["catalog_tables"]))

    def test_agrees_with_the_catalog_profile(self):
        product = PROFILE["product"]
        cols = TABLES["products"]["columns"]
        for c in product["required_on_insert"]:
            self.assertIn(c, cols, f"profile requires products.{c}")
        self.assertEqual(cols["price"]["type"], product["money"]["type"])
        self.assertEqual(cols["status"]["default"], f"'{product['status']['database_default']}'::text")
        for c in (product["images"]["column"], product["tags"]["column"], PROFILE["variants"]["location"].split(".")[1]):
            self.assertEqual(cols[c]["type"], "jsonb", c)
        defs = TABLES["products"]["constraints"].values()
        for c in product["identity"]["unique"]:
            self.assertTrue(any(re.fullmatch(rf"(PRIMARY KEY|UNIQUE) \({c}\)", d) for d in defs), f"{c} not unique")
        ref = product["category"]["references"].replace(".", "(") + ")"
        self.assertIn(f"FOREIGN KEY ({product['category']['column']}) REFERENCES {ref}", defs)

    def test_no_optional_feature_columns_storefront_a_lacks(self):
        features = next(s for s in CONFIG["storefronts"] if s["id"] == "storefront-a")["features"]
        for name, feat in PROFILE["optional_features"].items():
            table, column = feat["column"].split(".")[:2]
            if name not in features and "[]" not in column:
                self.assertNotIn(column, TABLES[table]["columns"], f"{column} needs feature {name}")


class SchemaFile(unittest.TestCase):
    def test_schema_sql_reproduces_the_snapshot(self):
        parsed = parse_schema_sql((BASE / "schema.sql").read_text())
        self.assertEqual(lsd.diff(TABLES, parsed), [])
        self.assertEqual(lsd.fingerprint(parsed), SNAPSHOT["fingerprint"])

    def test_every_table_has_row_level_security_like_the_real_project(self):
        text = (BASE / "schema.sql").read_text()
        for t in re.findall(r"CREATE TABLE public\.(\w+)", text):
            self.assertIn(f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;", text)

    def test_customer_stand_ins_exist(self):
        text = (BASE / "schema.sql").read_text()
        for t in ("users", "orders"):
            self.assertIn(f"CREATE TABLE public.{t} ", text)


class Seed(unittest.TestCase):
    def products(self):
        return SEED["products"]

    def test_every_column_is_a_real_column(self):
        for table in lsd.CATALOG_TABLES:
            for row in SEED[table]:
                extra = set(row) - set(TABLES[table]["columns"]) - {"case"}
                self.assertFalse(extra, f"{table}: unknown columns {extra}")

    def test_every_product_documents_its_case(self):
        for p in self.products():
            self.assertTrue(p.get("case"), p["slug"])

    def test_status_is_always_set_explicitly_and_valid(self):
        values = PROFILE["product"]["status"]["values"]
        for p in self.products():
            self.assertIn("status", p, f"{p['slug']}: status must be set explicitly")
            self.assertIn(p["status"], values)
        self.assertTrue({"active", "draft", "archived"} <= {p["status"] for p in self.products()})

    def test_required_columns_present(self):
        for p in self.products():
            for c in PROFILE["product"]["required_on_insert"]:
                self.assertIsNotNone(p.get(c), f"{p['slug']}: {c}")

    def test_identities_unique(self):
        for key in PROFILE["product"]["identity"]["unique"]:
            values = [p[key] for p in self.products() if p.get(key) is not None]
            self.assertEqual(len(values), len(set(values)), key)

    def test_references_resolve(self):
        categories = {c["id"] for c in SEED["categories"]}
        tags = {t["id"] for t in SEED["tags"]}
        for p in self.products():
            self.assertIn(p["category_id"], categories | {None}, p["slug"])
            self.assertTrue(set(p["tags"]) <= tags, p["slug"])

    def test_images_use_the_reference_format(self):
        for p in self.products():
            for ref in p["images"]:
                self.assertRegex(ref, r"^/objects/uploads/[0-9a-f-]+$")

    def test_tiers_have_the_profile_shape(self):
        shape = set(PROFILE["variants"]["shape"])
        for p in self.products():
            for tier in p["pricing_tiers"]:
                self.assertEqual(set(tier), shape, p["slug"])
                self.assertRegex(tier["id"], r"^tier-\d{13}$")

    def test_covers_the_placeholder_and_the_sold_original(self):
        self.assertIn(PROFILE["placeholders"][0], [p["description"] for p in self.products()])
        sold = [p for p in self.products() if p["is_sold"]]
        self.assertTrue(sold and all(p["status"] == "active" for p in sold))

    def test_seed_sql_quotes_and_drops_case(self):
        sql = lsd.seed_sql({"categories": [{"id": "x", "name": "O'Brien", "case": "c"}], "tags": [], "products": []})
        self.assertEqual(sql, "INSERT INTO public.categories (id, name) VALUES ('x', 'O''Brien');\n")


class RunbookRoleScript(unittest.TestCase):
    def test_extracts_the_supabase_script_with_a_password(self):
        sql = lsd.runbook_read_role_sql("pw-123")
        self.assertIn("CREATE ROLE commerce_os_read WITH LOGIN PASSWORD 'pw-123'", sql)
        self.assertNotIn("<password", sql)
        for t in lsd.CATALOG_TABLES:
            self.assertRegex(sql, rf"CREATE POLICY commerce_os_read_catalog ON public\.{t}\s+FOR SELECT")


class Diff(unittest.TestCase):
    def tables(self):
        return json.loads(json.dumps(TABLES))

    def test_identical_is_empty(self):
        self.assertEqual(lsd.diff(TABLES, self.tables()), [])

    def test_reports_new_and_removed_columns(self):
        live = self.tables()
        live["products"]["columns"]["color_variants"] = {"type": "jsonb", "not_null": False, "default": None}
        del live["tags"]["columns"]["slug"]
        notes = lsd.diff(TABLES, live)
        self.assertIn("products.color_variants: new column (jsonb)", notes)
        self.assertIn("tags.slug: column removed", notes)

    def test_reports_type_default_and_nullability_changes(self):
        live = self.tables()
        live["products"]["columns"]["price"]["type"] = "numeric(12,2)"
        live["products"]["columns"]["status"]["default"] = "'draft'::text"
        live["products"]["columns"]["sku"]["not_null"] = True
        notes = " | ".join(lsd.diff(TABLES, live))
        for col in ("price: type", "status: default", "sku: not_null"):
            self.assertIn(col, notes)

    def test_reports_constraint_changes(self):
        live = self.tables()
        del live["products"]["constraints"]["products_sku_unique"]
        self.assertIn("products: constraint products_sku_unique removed", lsd.diff(TABLES, live))

    def test_reports_a_missing_table(self):
        live = self.tables()
        del live["tags"]
        self.assertIn("tags: table missing", lsd.diff(TABLES, live))


@unittest.skipUnless(lsd.available(), "PostgreSQL server binaries not installed")
class LiveLocal(unittest.TestCase):
    """Start a private cluster, load everything, and check it as the owner and as the read role."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="cos-"))
        cls.cluster = lsd.Cluster(cls.tmp / "data", cls.tmp / "s", port=55433)
        cls.cluster.start()
        cls.password = lsd.load(cls.cluster, "storefront-a")
        cls.reader = cls.cluster.psql(user=lsd.READ_ROLE, password=cls.password, read_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.cluster.stop(delete=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_loaded_structure_matches_the_snapshot(self):
        self.assertEqual(lsd.diff(TABLES, lsd.read_structure(self.cluster.psql())), [])

    def test_seed_rows_loaded(self):
        counts = self.cluster.psql().rows("SELECT (SELECT count(*) FROM products) AS p, "
                                          "(SELECT count(*) FROM categories) AS c, (SELECT count(*) FROM tags) AS t")[0]
        self.assertEqual(counts, {"p": len(SEED["products"]), "c": len(SEED["categories"]), "t": len(SEED["tags"])})

    def test_runbook_role_passes_the_read_role_check(self):
        role, memberships, privs, rls = lsd.crr.collect(self.reader)
        results = lsd.crr.evaluate(role, memberships, privs) + lsd.crr.evaluate_rls(role["user"], rls)
        self.assertTrue(all(ok for ok, _ in results), [m for ok, m in results if not ok])

    def test_read_role_sees_the_catalog(self):
        self.assertEqual(self.reader.rows("SELECT count(*) AS n FROM products")[0]["n"], len(SEED["products"]))

    def test_read_role_cannot_read_customer_tables(self):
        with self.assertRaises(SystemExit) as e:
            self.reader.rows("SELECT * FROM users")
        self.assertIn("permission denied", str(e.exception))

    def run_as_reader(self, sql: str):
        import subprocess
        return subprocess.run([self.reader.bin, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
                              env=self.reader.env, capture_output=True, text=True, timeout=30)

    def test_read_role_sessions_are_read_only(self):
        r = self.run_as_reader("UPDATE products SET name = 'x'")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("read-only transaction", r.stderr)

    def test_grants_still_block_writes_when_the_session_opts_out_of_read_only(self):
        # A role can switch its own session to read-write, so the grants are the real guard.
        r = self.run_as_reader("BEGIN READ WRITE; UPDATE products SET name = 'x'; COMMIT;")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("permission denied for table products", r.stderr)


if __name__ == "__main__":
    unittest.main()
