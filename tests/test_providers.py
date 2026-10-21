"""Provider registry, catalog profiles and storefront config: complete, consistent and credential-free."""
import re
import unittest

from tests._helpers import REPO, load_json, read

PROVIDERS = REPO / "resources" / "providers"
PROFILES = REPO / "resources" / "catalog-profiles"
EXAMPLE = REPO / "config" / "storefronts.example.json"
DOC = REPO / "docs" / "storefront-connections.md"

PROVIDER_KEYS = {"id", "display_name", "engine", "status", "used_for", "connection", "roles", "assets",
                 "schema_changes", "verify_before_use"}
PROFILE_KEYS = {"id", "display_name", "sources", "catalog_tables", "write_tables", "product", "variants",
                "optional_features", "placeholders"}
STATUSES = {"documented", "adapter-built", "verified"}
USES = {"storefront", "operational"}
SLUG = re.compile(r"^[a-z][a-z0-9-]*$")
ENV_PREFIX = re.compile(r"^[A-Z][A-Z0-9_]*$")


def providers():
    return {p.stem: load_json(p) for p in PROVIDERS.glob("*.json")}


def profiles():
    return {p.stem: load_json(p) for p in PROFILES.glob("*.json")}


class Providers(unittest.TestCase):
    def test_at_least_the_two_discovered_providers(self):
        self.assertTrue({"replit-postgres", "supabase"} <= set(providers()))

    def test_required_keys_and_values(self):
        for stem, p in providers().items():
            self.assertEqual(PROVIDER_KEYS - set(p), set(), f"{stem}: missing keys")
            self.assertEqual(p["id"], stem, f"{stem}: id must equal filename")
            self.assertRegex(stem, SLUG)
            self.assertIn(p["status"], STATUSES, stem)
            self.assertTrue(p["used_for"] and set(p["used_for"]) <= USES, stem)
            self.assertTrue(p["verify_before_use"], f"{stem}: list what must be verified")

    def test_no_provider_authorizes_commerce_os_upload_yet(self):
        for stem, p in providers().items():
            self.assertEqual(p["assets"].get("commerce_os_upload"), "not_authorized", stem)

    def test_every_provider_is_in_the_connections_doc(self):
        doc = read(DOC)
        for stem in providers():
            self.assertIsNotNone(re.search(rf"^\| `{re.escape(stem)}` \|", doc, re.M), f"{stem} missing from {DOC.name}")


class Profiles(unittest.TestCase):
    def test_required_keys(self):
        for stem, p in profiles().items():
            self.assertEqual(PROFILE_KEYS - set(p), set(), f"{stem}: missing keys")
            self.assertEqual(p["id"], stem)

    def test_hidden_status_is_a_real_status_and_set_explicitly(self):
        for stem, p in profiles().items():
            status = p["product"]["status"]
            self.assertIn(status["hidden_on_create"], status["values"], stem)
            self.assertIn(status["column"], p["product"]["required_on_insert"],
                          f"{stem}: status must be required on insert so a default never publishes")
            self.assertTrue(status["always_set_explicitly"], stem)

    def test_write_tables_are_catalog_tables(self):
        for stem, p in profiles().items():
            self.assertTrue(set(p["write_tables"]) <= set(p["catalog_tables"]), stem)


class StorefrontConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = load_json(EXAMPLE)
        self.providers, self.profiles = providers(), profiles()

    def test_operational_database_provider(self):
        ops = self.cfg["operational_database"]
        self.assertIn(ops["provider"], self.providers)
        self.assertIn("operational", self.providers[ops["provider"]]["used_for"])

    def test_storefront_entries_resolve(self):
        for s in self.cfg["storefronts"]:
            self.assertRegex(s["id"], SLUG)
            self.assertIn(s["provider"], self.providers, s["id"])
            self.assertIn("storefront", self.providers[s["provider"]]["used_for"], s["id"])
            self.assertIn(s["catalog_profile"], self.profiles, s["id"])
            optional = set(self.profiles[s["catalog_profile"]]["optional_features"])
            self.assertTrue(set(s["features"]) <= optional, f"{s['id']}: unknown feature")
            self.assertEqual(s["mapping"], f"resources/storefront-mappings/{s['id']}")

    def test_isolation_unique_ids_and_prefixes(self):
        ids = [s["id"] for s in self.cfg["storefronts"]]
        prefixes = [s["env_prefix"] for s in self.cfg["storefronts"]] + [self.cfg["operational_database"]["env_prefix"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(prefixes), len(set(prefixes)), "env_prefix must be unique per database")
        for p in prefixes:
            self.assertRegex(p, ENV_PREFIX)

    def test_safe_defaults(self):
        for s in self.cfg["storefronts"]:
            self.assertIs(s["writes_enabled"], False, s["id"])
            self.assertEqual(s["asset_upload"], "not_authorized", s["id"])

    def test_no_connection_strings_in_config(self):
        self.assertNotIn("://", read(EXAMPLE), "config holds env var prefixes, never URLs")

    def test_env_example_has_a_read_url_per_database(self):
        env = read(REPO / ".env.example")
        prefixes = [s["env_prefix"] for s in self.cfg["storefronts"]] + [self.cfg["operational_database"]["env_prefix"]]
        for p in prefixes:
            self.assertRegex(env, rf"(?m)^{p}_DB_URL=", f".env.example lacks {p}_DB_URL")

    def test_local_config_is_gitignored(self):
        self.assertRegex(read(REPO / ".gitignore"), r"(?m)^config/storefronts\.local\.json$")


if __name__ == "__main__":
    unittest.main()
