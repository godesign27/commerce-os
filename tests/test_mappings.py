"""Product types and storefront mappings: valid shape, resolvable references, versioned edits.

Runs on the committed example, and on real local mappings (config/mappings/*.local.json) when present.
"""
import re
import unittest

from tests._helpers import REPO, load_json, read

TYPES = REPO / "resources" / "product-types"
MAPPINGS = REPO / "config" / "mappings"
COLOR = {"allowed", "not_applicable"}
SIZE = {"from_tiers", "supplied_only", "not_applicable"}
TYPE_STATUS = {"draft", "active", "retired"}
ENTRY_STATUS = {"in_scope", "excluded", "proposed_new"}
SLUG = re.compile(r"^[a-z][a-z0-9-]*$")


def product_types():
    return {p.stem: load_json(p) for p in TYPES.glob("*.json")}


def mapping_files():
    return sorted(MAPPINGS.glob("*.json"))


class ProductTypes(unittest.TestCase):
    def test_shape(self):
        for stem, t in product_types().items():
            self.assertEqual(t["id"], stem)
            self.assertRegex(stem, SLUG)
            self.assertIsInstance(t["version"], int)
            self.assertIn(t["status"], TYPE_STATUS, stem)
            self.assertIn(t["kind"], {"artwork", "tangible"}, stem)
            self.assertIn(t["options"]["color"], COLOR, stem)
            self.assertIn(t["options"]["size"], SIZE, stem)
            self.assertIn("price", t["required_facts"], stem)

    def test_color_rule_follows_kind(self):
        """B-030: artwork never has a color option; tangible goods may."""
        for stem, t in product_types().items():
            expected = "not_applicable" if t["kind"] == "artwork" else "allowed"
            self.assertEqual(t["options"]["color"], expected, stem)

    def test_readme_table_matches_files(self):
        readme = read(TYPES / "README.md")
        for stem, t in product_types().items():
            row = re.search(rf"^\| `{re.escape(stem)}` \| (\w+) \| (\w+) \| (\w+) \|$", readme, re.M)
            self.assertIsNotNone(row, f"README lacks a row for {stem}")
            self.assertEqual(row.groups(), (t["kind"], t["options"]["color"], t["options"]["size"]), stem)


class Mappings(unittest.TestCase):
    def setUp(self):
        self.types = product_types()

    def test_example_is_committed_and_local_files_are_ignored(self):
        self.assertTrue((MAPPINGS / "storefront.example.json").exists())
        self.assertRegex(read(REPO / ".gitignore"), r"(?m)^config/mappings/\*\.local\.json$")

    def test_every_mapping_is_well_formed(self):
        for path in mapping_files():
            with self.subTest(path.name):
                m = load_json(path)
                envs = set(m["environments"])
                self.assertIsInstance(m["version"], int)
                self.assertEqual([c["version"] for c in m["changes"]], list(range(1, m["version"] + 1)),
                                 "changes must record every version, in order")
                self.assertTrue(m["tier_types"])
                for kind in ("categories", "tags"):
                    keys = [e["key"] for e in m[kind]]
                    self.assertEqual(len(keys), len(set(keys)), f"duplicate {kind} keys")
                    for e in m[kind]:
                        self.assertIn(e["status"], ENTRY_STATUS, e["key"])
                        self.assertTrue(set(e["name"]) <= envs, f"{e['key']}: unknown environment")
                        self.assertTrue(set(e["id"]) <= set(e["name"]), f"{e['key']}: id for an environment with no name")
                        if e["status"] == "proposed_new":
                            self.assertEqual(e["id"], {}, f"{e['key']}: a proposed entry can't have IDs yet")
                        elif "merged_into" in e:
                            self.assertEqual(e["status"], "excluded", f"{e['key']}: a merged entry is retired")
                            self.assertIn(e["merged_into"], keys, f"{e['key']}: merged into an unknown key")
                            self.assertEqual(e["name"], {}, f"{e['key']}: a merged entry gives its names to the survivor")
                        else:
                            self.assertTrue(e["name"], f"{e['key']}: needs a name in at least one environment")
                    if kind == "tags":
                        for e in m["tags"]:
                            self.assertIn(e.get("kind"), {"type", "descriptive"}, e["key"])

    def test_product_type_mappings_resolve(self):
        for path in mapping_files():
            with self.subTest(path.name):
                m = load_json(path)
                cats = {e["key"] for e in m["categories"]}
                tags = {e["key"] for e in m["tags"]}
                for ptype, rule in m["product_types"].items():
                    self.assertIn(ptype, self.types, f"{ptype}: no such product type")
                    self.assertIn(rule["category"], cats, f"{ptype}: unknown category")
                    for alt in rule.get("alternative_categories", []):
                        self.assertIn(alt, cats, f"{ptype}: unknown alternative category")
                    for tag in rule["type_tags"]:
                        self.assertIn(tag, tags, f"{ptype}: unknown tag {tag}")
                    self.assertIsInstance(rule["proposed"], bool)

    def test_ids_are_never_shared_between_storefronts(self):
        seen = {}
        for path in mapping_files():
            m = load_json(path)
            for e in m["categories"] + m["tags"]:
                for env, i in e["id"].items():
                    other = seen.setdefault(i, (m["storefront"], env, e["key"]))
                    self.assertEqual(other[0], m["storefront"], f"ID {i} appears in {other[0]} and {m['storefront']}")


if __name__ == "__main__":
    unittest.main()
