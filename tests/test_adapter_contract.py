"""The storefront adapter contract (PRD §15), run against the in-memory fake (B-019).

AdapterContract is written against the interface only. Phase 3's real Storefront A adapter, pointed at
the local database stand-in, must pass the same class.
"""
import copy
import unittest

from packages.adapters import contract
from packages.adapters.contract import OutcomeUnknown, Refused
from packages.adapters.fake import FakeStorefront, seal
from tests._helpers import REPO
from tests._jsonschema import Registry

REG = Registry(REPO / "packages" / "contracts" / "schemas")
HASH = "ab" * 32
NEW_KEY = "6f1c2a8e-0000-4000-8000-0000000000aa"
SEED_PRODUCT = "5eed0000-0000-4000-8000-000000001002"     # the sold original
CATEGORY = "5eed0000-0000-4000-8000-000000000001"
TAG = "5eed0000-0000-4000-8000-000000000101"


def f(value, status="human_confirmed"):
    return {"value": value, "status": status}


class AdapterContract:
    """Mixin: subclasses set make_adapter(writes_enabled) and environment."""

    environment = "test"

    def make_adapter(self, writes_enabled=True):
        raise NotImplementedError

    def setUp(self):
        self.a = self.make_adapter(writes_enabled=True)

    # ---------------------------------------------------------------- builders

    def create_cs(self, **over):
        cs = {
            "contract": "change-set", "contract_version": 1,
            "change_set_id": "cs-new-001", "submission_id": "sub-new-001",
            "destination": self.a.storefront_id, "environment": self.environment,
            "canonical_revision": 1, "mapping_version": 3,
            "schema_fingerprint": self.a.capabilities()["schema_fingerprint"],
            "asset_manifest_hash": HASH, "requested_status": "draft",
            "operations": [{
                "seq": 1, "op": "create", "entity": "product", "key": NEW_KEY,
                "precondition": {"must_not_exist": True},
                "fields": {
                    "name": f("Tide Pool Study"), "slug": f("tide-pool-study"),
                    "price": {**f({"amount_minor": 4500, "currency": "USD"}),
                              "evidence": [{"kind": "human_decision", "ref": "decision-1"}]},
                    "status": f("draft"),
                    "category_id": f(CATEGORY), "tags": f([TAG]),
                    "description": f("Watercolor of a tide pool.", "supplied"),
                },
            }],
            "not_touched": [], "blockers": [], "change_set_hash": None, "simulated": False,
        }
        cs.update(over)
        return seal(cs)

    def update_cs(self, fields, **over):
        cs = {**self.create_cs(), "change_set_id": "cs-upd-001", "requested_status": "active",
              "operations": [{"seq": 1, "op": "update", "entity": "product", "key": SEED_PRODUCT,
                              "precondition": {"expected_row_hash": self.a.row_hash("product", SEED_PRODUCT)},
                              "fields": fields}]}
        cs.update(over)
        return seal(cs)

    def approval(self, cs, **over):
        doc = {"contract": "approval", "contract_version": 1, "approval_id": "appr-001",
               "actor": {"kind": "human", "id": "user-approver-1", "role": "approver"},
               "approved_at": "2026-10-27T15:00:00Z",
               "prepared_by": {"kind": "agent", "id": "catalog-draft", "role": "system"},
               **{k: cs[k] for k in contract.APPROVAL_BINDINGS}}
        doc.update(over)
        return doc

    def product(self, key):
        return next((p for p in self.a.read_catalog()["products"] if p["id"] == key), None)

    def refused_codes(self, cs, approval):
        with self.assertRaises(Refused) as e:
            self.a.publish_approved(cs, approval)
        return {i.code for i in e.exception.issues}

    # ---------------------------------------------------------------- documents are contract-valid

    def test_builders_make_contract_valid_documents(self):
        cs = self.create_cs()
        self.assertEqual(REG.validate(cs, "change-set.schema.json"), [])
        self.assertEqual(REG.validate(self.approval(cs), "approval.schema.json"), [])

    def test_capabilities(self):
        caps = self.a.capabilities()
        self.assertEqual(caps["writable_entities"], ["product"])
        self.assertIn("draft", caps["statuses"])
        self.assertRegex(caps["schema_fingerprint"], r"^[0-9a-f]{64}$")

    # ---------------------------------------------------------------- reads never leak live state

    def test_read_catalog_returns_copies(self):
        cat = self.a.read_catalog()
        cat["products"][0]["name"] = "changed"
        self.assertNotEqual(self.a.read_catalog()["products"][0]["name"], "changed")

    # ---------------------------------------------------------------- validation

    def test_valid_create_has_no_issues(self):
        self.assertEqual(self.a.validate(self.create_cs()), [])

    def test_wrong_destination_environment_or_fingerprint(self):
        cs = self.create_cs(destination="storefront-z", environment="production", schema_fingerprint="0" * 64)
        codes = {i.code for i in self.a.validate(cs)}
        self.assertTrue({"wrong_destination", "wrong_environment", "schema_changed"} <= codes)

    def test_create_must_set_status_explicitly(self):
        cs = self.create_cs()
        del cs["operations"][0]["fields"]["status"]
        self.assertIn("status_not_explicit", {i.code for i in self.a.validate(seal(cs))})

    def test_status_field_must_equal_requested_status(self):
        cs = self.create_cs(requested_status="active")
        self.assertIn("status_mismatch", {i.code for i in self.a.validate(cs)})

    def test_required_fields_unknown_columns_currency_and_references(self):
        cs = self.create_cs()
        fields = cs["operations"][0]["fields"]
        del fields["slug"]
        fields["color_variants"] = f([])            # a Storefront B feature column
        fields["price"]["value"]["currency"] = "EUR"
        fields["category_id"] = f("no-such-category")
        fields["tags"] = f(["no-such-tag"])
        codes = {i.code for i in self.a.validate(seal(cs))}
        self.assertTrue({"missing_required", "unknown_column", "wrong_currency", "unknown_category",
                         "unknown_tag"} <= codes, codes)

    def test_only_products_are_writable(self):
        cs = self.create_cs()
        cs["operations"][0]["entity"] = "category"
        self.assertIn("entity_not_writable", {i.code for i in self.a.validate(seal(cs))})

    def test_undelivered_assets_block(self):
        cs = self.create_cs(assets=[{"derivative_id": "drv-1", "destination_key": "/objects/uploads/x",
                                     "delivered": False}])
        self.assertIn("assets_not_delivered", {i.code for i in self.a.validate(cs)})

    # ---------------------------------------------------------------- dry run

    def test_dry_run_reports_without_writing(self):
        before = contract.canonical_json(self.a.read_catalog())
        report = self.a.dry_run(self.create_cs())
        self.assertTrue(report["dry_run"])
        self.assertTrue(report["would_publish"])
        self.assertIsNone(report["receipt_id"])
        self.assertEqual(report["plan"][0]["after"]["price"], "45.00")
        self.assertEqual(report["plan"][0]["after"]["status"], "draft")
        self.assertEqual(contract.canonical_json(self.a.read_catalog()), before)

    def test_dry_run_works_with_writes_disabled_and_on_simulated_sets(self):
        a = self.make_adapter(writes_enabled=False)
        self.assertTrue(a.dry_run(self.create_cs(simulated=True))["would_publish"])

    def test_dry_run_reports_precondition_failures(self):
        cs = self.update_cs({"is_sold": f(False)})
        cs["operations"][0]["precondition"]["expected_row_hash"] = "0" * 64
        report = self.a.dry_run(seal(cs))
        self.assertFalse(report["would_publish"])
        self.assertIn("row_changed", [i["code"] for i in report["issues"]])

    # ---------------------------------------------------------------- guards on publish

    def test_kill_switch_refuses(self):
        a = self.make_adapter(writes_enabled=False)
        cs = self.create_cs()
        with self.assertRaises(Refused) as e:
            a.publish_approved(cs, self.approval(cs))
        self.assertIn("writes_disabled", {i.code for i in e.exception.issues})
        self.assertIsNone(next((p for p in a.read_catalog()["products"] if p["id"] == NEW_KEY), None))

    def test_needs_an_approval(self):
        self.assertIn("no_approval", self.refused_codes(self.create_cs(), None))

    def test_simulated_change_sets_never_publish(self):
        cs = self.create_cs(simulated=True)
        self.assertIn("simulated", self.refused_codes(cs, self.approval(cs)))

    def test_unsealed_or_tampered_change_sets_refused(self):
        cs = self.create_cs()
        unsealed = {**cs, "change_set_hash": None}
        self.assertIn("not_sealed", self.refused_codes(unsealed, self.approval(unsealed)))
        tampered = copy.deepcopy(cs)
        tampered["operations"][0]["fields"]["price"]["value"]["amount_minor"] = 1
        self.assertIn("hash_mismatch", self.refused_codes(tampered, self.approval(cs)))

    def test_approval_must_bind_this_exact_change_set(self):
        cs = self.create_cs()
        for key, wrong in (("change_set_hash", "0" * 64), ("requested_status", "active"),
                           ("schema_fingerprint", "1" * 64), ("canonical_revision", 9)):
            with self.subTest(key=key):
                self.assertIn("binding_mismatch", self.refused_codes(cs, self.approval(cs, **{key: wrong})))

    def test_only_a_human_approver_and_not_the_preparer(self):
        cs = self.create_cs()
        agent = self.approval(cs, actor={"kind": "agent", "id": "x", "role": "approver"})
        self.assertIn("not_a_human_approver", self.refused_codes(cs, agent))
        same = self.approval(cs, prepared_by={"kind": "human", "id": "user-approver-1", "role": "reviewer"})
        self.assertIn("self_approval", self.refused_codes(cs, same))

    # ---------------------------------------------------------------- publishing

    def test_publish_creates_exactly_what_was_approved(self):
        cs = self.create_cs()
        result = self.a.publish_approved(cs, self.approval(cs))
        self.assertEqual(result.state, "SUCCEEDED")
        self.assertTrue(result.receipt_id)
        row = self.product(NEW_KEY)
        self.assertEqual((row["name"], row["status"], row["price"]), ("Tide Pool Study", "draft", "45.00"))
        self.assertEqual(row["pricing_tiers"], [])              # untouched columns take their defaults
        self.assertFalse(row["is_sold"])

    def test_publish_is_idempotent_per_change_set(self):
        cs = self.create_cs()
        first = self.a.publish_approved(cs, self.approval(cs))
        again = self.a.publish_approved(cs, self.approval(cs))
        self.assertTrue(again.replayed)
        self.assertEqual(again.receipt_id, first.receipt_id)
        self.assertEqual(sum(p["id"] == NEW_KEY for p in self.a.read_catalog()["products"]), 1)

    def test_reused_change_set_id_with_different_contents_refused(self):
        cs = self.create_cs()
        self.a.publish_approved(cs, self.approval(cs))
        other = copy.deepcopy(cs)
        other["operations"][0]["key"] = "6f1c2a8e-0000-4000-8000-0000000000bb"
        other = seal(other)
        self.assertIn("change_set_id_reused", self.refused_codes(other, self.approval(other)))

    def test_create_refuses_when_the_key_already_exists(self):
        cs = self.create_cs()
        cs["operations"][0]["key"] = SEED_PRODUCT
        cs = seal(cs)
        result = self.a.publish_approved(cs, self.approval(cs))
        self.assertEqual(result.state, "FAILED")
        self.assertIn("already_exists", result.error)

    def test_update_applies_only_its_fields(self):
        before = self.product(SEED_PRODUCT)
        cs = self.update_cs({"is_sold": f(False), "status": f("active")})
        self.assertEqual(self.a.publish_approved(cs, self.approval(cs)).state, "SUCCEEDED")
        after = self.product(SEED_PRODUCT)
        self.assertFalse(after["is_sold"])
        for col in ("name", "price", "pricing_tiers", "images"):
            self.assertEqual(after[col], before[col], col)

    def test_update_refuses_when_the_row_changed(self):
        cs = self.update_cs({"is_sold": f(False)})
        other = self.update_cs({"name": f("Renamed")}, change_set_id="cs-upd-002")
        self.a.publish_approved(other, self.approval(other))
        result = self.a.publish_approved(cs, self.approval(cs))
        self.assertEqual(result.state, "FAILED")
        self.assertIn("row_changed", result.error)
        self.assertTrue(self.product(SEED_PRODUCT)["is_sold"])

    def test_multi_operation_change_sets_are_atomic(self):
        cs = self.create_cs()
        second = copy.deepcopy(cs["operations"][0])
        second.update({"seq": 2, "key": SEED_PRODUCT})           # collides: must_not_exist fails
        cs["operations"].append(second)
        cs = seal(cs)
        result = self.a.publish_approved(cs, self.approval(cs))
        self.assertEqual(result.state, "FAILED")
        self.assertIsNone(self.product(NEW_KEY), "the first operation must not be left behind")

    def test_failure_before_write_leaves_nothing(self):
        self.a.fail_next("before_write")
        cs = self.create_cs()
        self.assertEqual(self.a.publish_approved(cs, self.approval(cs)).state, "FAILED")
        self.assertIsNone(self.product(NEW_KEY))

    # ---------------------------------------------------------------- reconciliation

    def test_lost_response_is_outcome_unknown_then_reconciles_to_success(self):
        self.a.fail_next("lose_response")
        cs = self.create_cs()
        with self.assertRaises(OutcomeUnknown) as e:
            self.a.publish_approved(cs, self.approval(cs))
        attempts = [{"attempt_id": e.exception.attempt_id, "state": "OUTCOME_UNKNOWN"}]
        report = self.a.reconcile(cs, attempts)
        self.assertEqual(REG.validate(report, "reconciliation-report.schema.json"), [])
        self.assertEqual((report["verified_state"], report["recommended_action"]), ("SUCCEEDED", "none"))

    def test_reconcile_never_claims_success_for_missing_rows(self):
        cs = self.create_cs()
        report = self.a.reconcile(cs, [{"attempt_id": "att-x", "state": "OUTCOME_UNKNOWN"}])
        self.assertEqual(REG.validate(report, "reconciliation-report.schema.json"), [])
        self.assertEqual((report["verified_state"], report["recommended_action"]), ("OUTCOME_UNKNOWN", "recheck"))
        failed = self.a.reconcile(cs, [{"attempt_id": "att-x", "state": "FAILED"}])
        self.assertEqual(failed["verified_state"], "FAILED")

    def test_reconcile_flags_remote_changes(self):
        cs = self.create_cs()
        self.a.publish_approved(cs, self.approval(cs))
        edit = {**self.create_cs(), "change_set_id": "cs-edit", "requested_status": "draft",
                "operations": [{"seq": 1, "op": "update", "entity": "product", "key": NEW_KEY,
                                "precondition": {"expected_row_hash": self.a.row_hash("product", NEW_KEY)},
                                "fields": {"name": f("Edited elsewhere")}}]}
        edit = seal(edit)
        self.a.publish_approved(edit, self.approval(edit))
        report = self.a.reconcile(cs)
        self.assertEqual(REG.validate(report, "reconciliation-report.schema.json"), [])
        self.assertEqual(report["operations"][0]["mismatched_fields"], ["name"])
        self.assertEqual(report["recommended_action"], "operator_review")


class FakeStorefrontA(AdapterContract, unittest.TestCase):
    def make_adapter(self, writes_enabled=True):
        return FakeStorefront.from_repo("storefront-a", "test", writes_enabled=writes_enabled)


class FakeSpecifics(unittest.TestCase):
    def test_seeded_from_the_local_stand_in(self):
        a = FakeStorefront.from_repo("storefront-a")
        self.assertEqual(len(a.read_catalog()["products"]), 6)
        self.assertEqual(a.capabilities()["schema_fingerprint"],
                         __import__("json").loads((REPO / "database" / "storefronts" / "storefront-a" /
                                                   "catalog-structure.json").read_text())["fingerprint"])

    def test_writes_start_disabled(self):
        self.assertFalse(FakeStorefront.from_repo("storefront-a").capabilities()["writes_enabled"])

    def test_seed_rows_get_every_column(self):
        a = FakeStorefront.from_repo("storefront-a")
        cols = set(a.columns("products"))
        for p in a.read_catalog()["products"]:
            self.assertEqual(set(p), cols)
            self.assertRegex(p["price"], r"^\d+\.\d{2}$")

    def test_change_set_hash_covers_everything_but_itself(self):
        sealed = seal({"change_set_id": "cs-1", "requested_status": "draft", "operations": []})
        self.assertEqual(contract.change_set_hash(sealed), sealed["change_set_hash"])
        self.assertEqual(contract.change_set_hash({**sealed, "change_set_hash": "x"}), sealed["change_set_hash"])
        self.assertNotEqual(contract.change_set_hash({**sealed, "requested_status": "active"}),
                            sealed["change_set_hash"])

    def test_fixture_change_sets_still_validate_their_shape(self):
        # The committed fixtures target storefront-b/production; the fake for A must refuse them.
        doc = __import__("json").loads((REPO / "tests" / "fixtures" / "contracts" / "valid" /
                                        "change-set.hat-two-colors.json").read_text())
        codes = {i.code for i in FakeStorefront.from_repo("storefront-a").validate(doc)}
        self.assertIn("wrong_destination", codes)


if __name__ == "__main__":
    unittest.main()
