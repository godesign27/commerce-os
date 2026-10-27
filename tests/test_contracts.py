"""packages/contracts: schemas are well formed, fixtures conform, and known-bad documents are rejected.

Two layers are tested:
- Schema rules: validated with the strict stdlib validator in packages/contracts/validator.py.
- Semantic rules the schemas can't express (option uniqueness, the product-type option rules, grouping,
  approval bindings), implemented in packages/policy (B-043). The semantic cases in
  fixtures/contracts/invalid.json are their specification.
"""
import copy
import json
import re
import unittest

from tests._helpers import REPO, SHARED, load_json, read
from packages.policy import semantic_violations
from tests._jsonschema import SUPPORTED, Registry, keywords_used

CONTRACTS = REPO / "packages" / "contracts"
SCHEMAS = CONTRACTS / "schemas"
FIXTURES = REPO / "tests" / "fixtures" / "contracts"
PRODUCT_TYPES = REPO / "resources" / "product-types"
REG = Registry(SCHEMAS)
DOC_SCHEMAS = sorted(n for n in REG.schemas if n != "common.schema.json")


def fixtures():
    for p in sorted((FIXTURES / "valid").glob("*.json")):
        yield p.stem, p.stem.split(".", 1)[0] + ".schema.json", load_json(p)


def fixture(name):
    return load_json(FIXTURES / "valid" / f"{name}.json")


def _walk(path):
    for part in path.split("."):
        for m in re.finditer(r"([^\[\]]+)|\[(\d+)\]", part):
            yield m.group(1) if m.group(1) is not None else int(m.group(2))


def patched(doc, case):
    doc = copy.deepcopy(doc)
    for path, value in case.get("set", {}).items():
        *parents, last = list(_walk(path))
        node = doc
        for p in parents:
            node = node[p]
        node[last] = value
    for path in case.get("delete", []):
        *parents, last = list(_walk(path))
        node = doc
        for p in parents:
            node = node[p]
        del node[last]
    return doc


def semantic_errors(doc, related=()):
    """The policy package's semantic rules (B-043), as messages."""
    return [str(v) for v in semantic_violations(doc, related)]


class Schemas(unittest.TestCase):
    def test_every_schema_is_well_formed(self):
        for name, s in REG.schemas.items():
            with self.subTest(name):
                self.assertEqual(s["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(s["$id"], name)
                self.assertTrue(s.get("title") and s.get("description"))

    def test_document_schemas_are_closed_and_named(self):
        for name in DOC_SCHEMAS:
            s = REG.schemas[name]
            with self.subTest(name):
                self.assertIs(s["additionalProperties"], False)
                self.assertEqual(s["properties"]["contract"]["const"], name.removesuffix(".schema.json"))
                self.assertIn("contract_version", s["required"])

    def test_only_supported_keywords(self):
        for name, s in REG.schemas.items():
            with self.subTest(name):
                self.assertEqual(keywords_used(s) - SUPPORTED, set(), "the test validator would ignore these")

    def test_every_ref_resolves(self):
        def refs(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    yield node["$ref"]
                for v in node.values():
                    yield from refs(v)
            elif isinstance(node, list):
                for v in node:
                    yield from refs(v)
        for name, s in REG.schemas.items():
            for r in refs(s):
                with self.subTest(f"{name} → {r}"):
                    REG.resolve(r, name)

    def test_every_document_schema_has_a_valid_fixture(self):
        covered = {schema for _, schema, _ in fixtures()}
        self.assertEqual(set(DOC_SCHEMAS) - covered, set())


class Fixtures(unittest.TestCase):
    def test_valid_fixtures_validate(self):
        for name, schema, doc in fixtures():
            with self.subTest(name):
                self.assertEqual(REG.validate(doc, schema), [])

    def test_valid_fixtures_pass_semantic_rules(self):
        all_docs = [d for _, _, d in fixtures()]
        for name, _, doc in fixtures():
            with self.subTest(name):
                self.assertEqual(semantic_errors(doc, all_docs), [])

    def test_invalid_cases_fail_for_the_stated_reason(self):
        for case in load_json(FIXTURES / "invalid.json")["cases"]:
            with self.subTest(case["name"]):
                base = fixture(case["fixture"])
                schema = case["fixture"].split(".", 1)[0] + ".schema.json"
                self.assertEqual(REG.validate(base, schema), [], "base fixture must be valid")
                errors = REG.validate(patched(base, case), schema)
                self.assertTrue(any(case["expect"] in e for e in errors),
                                f"expected an error containing {case['expect']!r}, got {errors}")

    def test_semantic_cases_fail_for_the_stated_reason(self):
        all_docs = [d for _, _, d in fixtures()]
        for case in load_json(FIXTURES / "invalid.json")["semantic_cases"]:
            with self.subTest(case["name"]):
                doc = patched(fixture(case["fixture"]), case)
                errors = semantic_errors(doc, all_docs)
                self.assertTrue(any(case["expect"] in e for e in errors),
                                f"expected an error containing {case['expect']!r}, got {errors}")


class MatchesPolicy(unittest.TestCase):
    def test_evidence_statuses_match_the_policy(self):
        table = read(SHARED / "evidence-policy.md").split("## Statuses", 1)[1].split("## Rules", 1)[0]
        policy = set(re.findall(r"^\| `(\w+)` \|", table, re.M))
        self.assertEqual(set(REG.schemas["common.schema.json"]["$defs"]["evidence_status"]["enum"]), policy)

    def test_commercial_statuses_exclude_observed_and_inferred(self):
        allowed = set(REG.schemas["common.schema.json"]["$defs"]["commercial_status"]["enum"])
        self.assertFalse(allowed & {"observed", "inferred"})

    def test_publication_states_match_the_workflow(self):
        workflow = read(SHARED / "WORKFLOW.md").split("## Per-destination publication states", 1)[1].split("## Gates", 1)[0]
        states = set(re.findall(r"`([A-Z_]+)`", workflow))
        self.assertEqual(set(REG.schemas["common.schema.json"]["$defs"]["publication_state"]["enum"]), states)

    def test_fixture_product_types_exist(self):
        for name, _, doc in fixtures():
            if "product_type" in doc:
                self.assertTrue((PRODUCT_TYPES / f"{doc['product_type']['id']}.json").exists(), name)


class Validator(unittest.TestCase):
    """The subset validator itself must not be permissive."""
    def test_rejects_common_mistakes(self):
        r = Registry(SCHEMAS)
        s = {"type": "object", "required": ["a"], "additionalProperties": False,
             "properties": {"a": {"type": "integer"}, "b": {"enum": [1]}}}
        self.assertTrue(r.is_valid({"a": 1}, s, "common.schema.json"))
        for bad in ({}, {"a": True}, {"a": 1.5}, {"a": 1, "c": 0}, {"a": 1, "b": True}):
            self.assertFalse(r.is_valid(bad, s, "common.schema.json"), bad)


if __name__ == "__main__":
    unittest.main()
