"""scripts/check_read_role.py: pure logic only. No database, no network."""
import importlib.util
import unittest

from tests._helpers import REPO, read

spec = importlib.util.spec_from_file_location("check_read_role", REPO / "scripts" / "check_read_role.py")
crr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crr)

FAKE_URL = "postgresql://commerce_os_read:fake%2Fpass@ep-fake-123.us-east-1.aws.neon.tech/neondb?sslmode=require"
GOOD_ROLE = {k: False for k in ("rolsuper", "rolcreaterole", "rolcreatedb", "rolbypassrls", "rolreplication")}


def privs(select=(), write=()):
    tables = ["products", "categories", "tags", "users", "orders"]
    return {t: {"SELECT": t in select, **{p: (t, p) in write for p in crr.WRITE_PRIVILEGES}} for t in tables}


class Connection(unittest.TestCase):
    def test_url_becomes_env_vars_and_never_argv(self):
        env = crr.pg_env_from_url(FAKE_URL)
        self.assertEqual(env["PGUSER"], "commerce_os_read")
        self.assertEqual(env["PGPASSWORD"], "fake/pass")
        self.assertEqual(env["PGDATABASE"], "neondb")
        self.assertEqual(env["PGSSLMODE"], "require")
        self.assertIn("default_transaction_read_only=on", env["PGOPTIONS"])

    def test_sslmode_defaults_to_require(self):
        self.assertEqual(crr.pg_env_from_url(FAKE_URL.split("?")[0])["PGSSLMODE"], "require")

    def test_rejects_non_postgres_urls(self):
        with self.assertRaises(ValueError):
            crr.pg_env_from_url("https://example.com/db")

    def test_dotenv_parsing(self):
        env = crr.parse_dotenv("# c\nexport A=1\nB='two'\nC=\"three\"\n\nbad line\n")
        self.assertEqual(env, {"A": "1", "B": "two", "C": "three"})

    def test_redact(self):
        self.assertEqual(crr.redact("auth failed for fake/pass", ["fake/pass"]), "auth failed for <redacted>")

    def test_script_never_prints_the_url_or_password(self):
        src = read(REPO / "scripts" / "check_read_role.py")
        for forbidden in ("print(url", "print(env", "PGPASSWORD\"])", "print(key, url"):
            self.assertNotIn(forbidden, src)


class Evaluate(unittest.TestCase):
    def test_correct_role_passes(self):
        results = crr.evaluate(GOOD_ROLE, [], privs(select=crr.ALLOWED))
        self.assertTrue(all(ok for ok, _ in results), results)

    def test_customer_table_access_fails(self):
        results = crr.evaluate(GOOD_ROLE, [], privs(select=crr.ALLOWED + ("users",)))
        self.assertFalse(all(ok for ok, _ in results))

    def test_write_privilege_fails(self):
        results = crr.evaluate(GOOD_ROLE, [], privs(select=crr.ALLOWED, write=[("products", "UPDATE")]))
        self.assertFalse(all(ok for ok, _ in results))

    def test_missing_catalog_select_fails(self):
        results = crr.evaluate(GOOD_ROLE, [], privs(select=("products", "categories")))
        self.assertFalse(all(ok for ok, _ in results))

    def test_elevated_role_or_membership_fails(self):
        self.assertFalse(all(ok for ok, _ in crr.evaluate({**GOOD_ROLE, "rolbypassrls": True}, [], privs(select=crr.ALLOWED))))
        self.assertFalse(all(ok for ok, _ in crr.evaluate(GOOD_ROLE, ["neon_superuser"], privs(select=crr.ALLOWED))))


class Compare(unittest.TestCase):
    def entry(self, key, name, slug=None, id_=None, status="in_scope"):
        return {"key": key, "name": {"production": name}, "slug": slug,
                "id": {"production": id_} if id_ else {}, "status": status}

    def test_match_by_id_slug_and_name(self):
        live = [{"id": "1", "name": "Goods", "slug": "goods"}, {"id": "2", "name": "Gear", "slug": "gear"},
                {"id": "3", "name": "Misc", "slug": "misc"}]
        entries = [self.entry("goods", "Goods", "goods", "1"), self.entry("gear", "Gear", "gear"),
                   self.entry("misc", "Misc")]
        notes = crr.compare(entries, live, "production")
        self.assertIn("id can be recorded: gear → 2", notes)
        self.assertIn("slug can be recorded: misc → misc", notes)
        self.assertFalse([n for n in notes if n.startswith(("in mapping", "live, not"))], notes)

    def test_reports_both_directions(self):
        notes = crr.compare([self.entry("old", "Old")], [{"id": "9", "name": "New", "slug": "new"}], "production")
        self.assertIn("in mapping, not live: old (Old)", notes)
        self.assertIn("live, not in mapping: New (new)", notes)

    def test_other_environments_and_proposed_entries_are_skipped(self):
        dev_only = {"key": "d", "name": {"development": "Dev"}, "slug": None, "id": {}, "status": "in_scope"}
        proposed = self.entry("p", "Planned", status="proposed_new")
        self.assertEqual(crr.compare([dev_only, proposed], [], "production"), [])


if __name__ == "__main__":
    unittest.main()
