"""packages/policy (B-043): schema plus semantic validation of contract documents."""
import copy
import json
import re
import unittest

from packages import policy
from packages.adapters import contract
from packages.policy import Violation, validate
from tests._helpers import REPO, load_json
from tests.test_contracts import FIXTURES, fixture, fixtures, patched

ALL_DOCS = [d for _, _, d in fixtures()]


def codes(violations):
    return {v.code for v in violations}


class Validate(unittest.TestCase):
    def test_every_valid_fixture_passes(self):
        for name, _, doc in fixtures():
            with self.subTest(name):
                self.assertEqual(validate(doc, ALL_DOCS), [])

    def test_every_schema_case_fails_through_policy(self):
        for case in load_json(FIXTURES / "invalid.json")["cases"]:
            with self.subTest(case["name"]):
                expected = case["fixture"].split(".", 1)[0]
                found = validate(patched(fixture(case["fixture"]), case), ALL_DOCS, expected=expected)
                self.assertTrue(found, "must be rejected")
                if found[0].code != "wrong_contract":
                    self.assertTrue(any(case["expect"] in str(v) for v in found), [str(v) for v in found])

    def test_a_document_of_another_contract_is_refused(self):
        found = validate(fixture("approval.hat-two-colors"), expected="change-set")
        self.assertEqual(codes(found), {"wrong_contract"})
        self.assertEqual(validate(fixture("change-set.hat-two-colors"), expected="change-set"), [])

    def test_every_semantic_case_fails_through_policy(self):
        for case in load_json(FIXTURES / "invalid.json")["semantic_cases"]:
            with self.subTest(case["name"]):
                found = validate(patched(fixture(case["fixture"]), case), ALL_DOCS)
                self.assertTrue(any(case["expect"] in str(v) for v in found), [str(v) for v in found])

    def test_schema_runs_first(self):
        doc = fixture("canonical-draft.hat-two-colors")
        doc["variants"][1]["option_values"] = {"color": "navy"}     # a semantic error...
        del doc["product"]                                          # ...hidden behind a schema error
        self.assertEqual(codes(validate(doc)), {"schema"})

    def test_unknown_contract(self):
        for doc in ({"contract": "nonsense"}, {"contract": "common"}, {}, []):
            self.assertEqual(codes(validate(doc)), {"unknown_contract"}, doc)

    def test_violations_are_structured(self):
        v = validate(patched(fixture("approval.hat-two-colors"), {"set": {"mapping_version": 2}}), ALL_DOCS)[0]
        self.assertIsInstance(v, Violation)
        self.assertEqual((v.code, v.path), ("binding_mismatch", "mapping_version"))
        self.assertEqual(set(v.as_dict()), {"code", "path", "message"})


class Options(unittest.TestCase):
    def draft(self, type_id, defs, variants):
        doc = fixture("canonical-draft.hat-two-colors")
        doc["product_type"]["id"] = type_id
        doc["product"]["option_definitions"] = defs
        doc["variants"] = [{**copy.deepcopy(doc["variants"][0]), "option_values": v} for v in variants]
        return doc

    def test_size_allowed_only_where_the_type_permits(self):
        size = [{"key": "size", "label": "Size", "values": ["S", "M"]}]
        variants = [{"size": "S"}, {"size": "M"}]
        self.assertEqual(policy.semantic_violations(self.draft("hat", size, variants)), [])
        self.assertIn("option_not_allowed", codes(policy.semantic_violations(self.draft("sunglasses", size, variants))))

    def test_undeclared_options_are_refused(self):
        doc = self.draft("hat", [{"key": "material", "label": "Material", "values": ["wool"]}], [{"material": "wool"}])
        found = policy.semantic_violations(doc)
        self.assertIn("option_not_allowed", codes(found))
        self.assertIn("undeclared", str(found[0]))

    def test_every_variant_sets_every_option(self):
        color = [{"key": "color", "label": "Color", "values": ["navy", "red"]}]
        doc = self.draft("hat", color, [{"color": "navy"}, {}])
        self.assertIn("option_value_missing", codes(policy.semantic_violations(doc)))

    def test_an_option_is_defined_once(self):
        color = [{"key": "color", "label": "Color", "values": ["navy"]},
                 {"key": "color", "label": "Colour", "values": ["red"]}]
        self.assertIn("duplicate_option", codes(policy.semantic_violations(self.draft("hat", color, [{"color": "navy"}]))))

    def test_unknown_product_type(self):
        self.assertEqual(codes(policy.semantic_violations(self.draft("spaceship", [], [{}]))), {"unknown_product_type"})

    def test_product_types_can_be_injected(self):
        types = {"hat": {"options": {"color": "not_applicable"}}}
        doc = fixture("canonical-draft.hat-two-colors")
        self.assertIn("option_not_allowed", codes(policy.semantic_violations(doc, product_types=types)))

    def test_every_product_type_rule_is_known(self):
        for name, t in policy.load_product_types().items():
            for key, rule in t["options"].items():
                self.assertIn(key, policy.semantics.OPTION_PERMITTED, f"{name}: option {key} has no rule")
                known = {"allowed", "not_applicable", "from_tiers", "supplied_only"}
                self.assertIn(rule, known, f"{name}: {key}={rule}")


class Approvals(unittest.TestCase):
    def test_bindings_checked_only_against_the_named_change_set(self):
        approval = fixture("approval.hat-two-colors")
        other = {**fixture("change-set.artwork-update"), "mapping_version": 99}
        self.assertEqual(policy.semantic_violations(approval, [other]), [])

    def test_binding_violations_cover_every_binding(self):
        cs = fixture("change-set.hat-two-colors")
        approval = fixture("approval.hat-two-colors")
        for key in policy.APPROVAL_BINDINGS:
            with self.subTest(key):
                wrong = {**approval, key: "different"}
                self.assertEqual([v.path for v in policy.binding_violations(wrong, cs)], [key])

    def test_adapters_use_the_same_bindings(self):
        self.assertEqual(set(contract.APPROVAL_BINDINGS), {"change_set_id", *policy.APPROVAL_BINDINGS})

    def test_database_trigger_binds_the_same_fields(self):
        sql = (REPO / "database" / "operational" / "migrations" / "0007_review_and_approval.sql").read_text()
        tuple_sql = re.search(r"IF \(NEW\.(.*?)\)\s*IS DISTINCT FROM", sql, re.S).group(1)
        trigger = {c.strip().removeprefix("NEW.") for c in tuple_sql.split(",")}
        fk = re.search(r"FOREIGN KEY \(change_set_id, (\w+), (\w+)\)", sql).groups()
        # destination/environment are enforced by the foreign key; prepared_by feeds the self-approval check
        self.assertEqual(trigger | set(fk) | {"change_set_id"},
                         {"change_set_id", *policy.APPROVAL_BINDINGS, "prepared_by"}
                         - {"destination", "environment"} | {"storefront_id", "environment"})


if __name__ == "__main__":
    unittest.main()
