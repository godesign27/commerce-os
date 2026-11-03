"""The storefront preview and its approval (B-064): listing -> change set, Gate 3, invalidation, audit trail.

Everything runs against the fake test storefront with an invented mapping: no real names, ids or prices.
"""
import json
import re
import unittest

from packages import policy
from packages.adapters import artstore_map as am
from packages.drafting import publication
from packages.drafting.audit import Audit
from packages.drafting.store import Store, clean_price, draft_facts
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, record_for, tmp

MAPPING = {
    "storefront": "storefront-a", "version": 2, "tier_types": ["Original", "Print", "Canvas Print"],
    "categories": [{"key": "originals", "name": {"production": "Originals"}, "slug": "originals", "status": "in_scope"},
                   {"key": "art-prints", "name": {"production": "Art Prints"}, "slug": "art-prints", "status": "in_scope"},
                   {"key": "journal", "name": {"production": "Journal"}, "slug": "journal", "status": "excluded"}],
    "tags": [{"key": "bold", "name": {"production": "Bold"}, "slug": "bold", "status": "in_scope"},
             {"key": "calm", "name": {"production": "Calm"}, "slug": "calm", "status": "in_scope"}],
    "product_types": {"artwork": {"category": "originals", "alternative_categories": ["art-prints"]}},
}
FACTS = {"medium": "acrylic on canvas", "dimensions": "16 x 20 in", "price": "450.00", "sold_as": "Original",
         "edition": "original"}
ITEM = {"id": "fox", "source": "Fox.jpg", "kind": "artwork", "framed": "img/fox.framed.jpg"}
ASSETS = [{"derivative_id": "drv-fox-framed", "kind": "framed", "sha256": "a" * 64}]


def approved_entry(facts=FACTS, copy=None):
    copy = copy or {"title": "Quiet Fox", "short_description": "A fox.", "collector_description": "A fox at dusk.",
                    "store_tags": ["Bold"], "search_keywords": []}
    return {"facts": dict(facts), "approved": {"at": "2026-11-02T10:00:00Z", "by": "owner", "revision": 3, "copy": copy}}


def build(entry=None, assets=ASSETS, mapping=MAPPING, store=None):
    entry = approved_entry() if entry is None else entry
    store = store or am.test_store("storefront-a", mapping)
    copy = (entry.get("approved") or {}).get("copy")
    return am.build(item=ITEM, entry=entry, record=record_for("fox", 3), copy=copy, assets=assets,
                    mapping=mapping, store=store), store


def targets(cs, severity="blocking"):
    return sorted(b["target"] for b in cs["blockers"] if b["severity"] == severity)


class ChangeSet(unittest.TestCase):
    def test_a_complete_listing_is_one_valid_create(self):
        cs, store = build()
        self.assertEqual([str(v) for v in policy.validate(cs)], [], "a valid change-set contract document")
        self.assertEqual(targets(cs), ["assets.delivery"], "only image delivery is left, and that's after approval")
        self.assertTrue(am.approvable(cs))
        op = cs["operations"][0]
        self.assertEqual((op["op"], op["entity"], op["precondition"]), ("create", "product", {"must_not_exist": True}))
        f = op["fields"]
        self.assertEqual(f["price"]["value"], {"amount_minor": 45000, "currency": "USD"})
        self.assertEqual(f["status"]["value"], "draft", "status is always set explicitly, hidden on create")
        self.assertEqual(cs["requested_status"], "draft")
        self.assertEqual(f["category_id"]["value"], am.test_id("category", "originals"))
        self.assertEqual(f["tags"]["value"], [am.test_id("tag", "bold")])
        self.assertTrue(f["is_original"]["value"])
        self.assertEqual(f["pricing_tiers"]["value"][0]["type"], "Original")
        self.assertEqual(f["name"]["status"], "human_confirmed", "approved copy")
        self.assertEqual(cs["mapping_version"], 2)
        self.assertEqual(cs["canonical_revision"], 3)
        self.assertTrue(cs["simulated"], "a Phase 1 change set can only ever be dry-run")
        issues = [i.code for i in store.validate(cs)]
        self.assertEqual(issues, ["assets_not_delivered"], "the store's own rules agree, apart from delivery")

    def test_missing_facts_are_blockers_never_values(self):
        for fact, target in (("price", "product.price"), ("medium", "product.material"),
                             ("dimensions", "product.dimensions"), ("sold_as", "product.sold_as")):
            facts = {k: v for k, v in FACTS.items() if k != fact}
            cs, _ = build(approved_entry(facts))
            self.assertIn(target, targets(cs), fact)
            self.assertFalse(am.approvable(cs), fact)
            column = {"sold_as": "pricing_tiers"}.get(fact, fact)
            self.assertNotIn(column, cs["operations"][0]["fields"], f"no {fact} is guessed")

    def test_a_size_without_a_unit_isnt_sent(self):
        cs, _ = build(approved_entry(dict(FACTS, dimensions="16 x 20")))
        self.assertIn("product.dimensions", targets(cs))
        self.assertNotIn("dimensions", cs["operations"][0]["fields"])

    def test_copy_must_be_approved(self):
        entry = approved_entry()
        copy = entry.pop("approved")["copy"]
        store = am.test_store("storefront-a", MAPPING)
        cs = am.build(item=ITEM, entry=entry, record=record_for("fox"), copy=copy, assets=ASSETS, mapping=MAPPING, store=store)
        self.assertIn("copy.approval", targets(cs))
        self.assertEqual(cs["operations"][0]["fields"]["name"]["status"], "inferred")

    def test_print_goes_in_the_print_category_and_isnt_original(self):
        cs, _ = build(approved_entry(dict(FACTS, sold_as="Print", edition="print")))
        f = cs["operations"][0]["fields"]
        self.assertEqual(f["category_id"]["value"], am.test_id("category", "art-prints"))
        self.assertFalse(f["is_original"]["value"])

    def test_edition_and_sold_as_must_agree(self):
        cs, _ = build(approved_entry(dict(FACTS, sold_as="Original", edition="print")))
        self.assertIn("product.edition", targets(cs))
        cs, _ = build(approved_entry(dict(FACTS, sold_as="Print", edition="both")))
        self.assertNotIn("product.edition", targets(cs), "original and prints may be sold as either")

    def test_unknown_sold_as_and_tags(self):
        cs, _ = build(approved_entry(dict(FACTS, sold_as="Poster")))
        self.assertIn("product.sold_as", targets(cs))
        entry = approved_entry(copy={"title": "T", "short_description": "s", "collector_description": "c",
                                     "store_tags": ["Bold", "Glitter"], "search_keywords": []})
        cs, _ = build(entry)
        self.assertEqual(targets(cs, "warning"), ["product.tags"], "an unknown tag is left off, with a warning")
        self.assertEqual(cs["operations"][0]["fields"]["tags"]["value"], [am.test_id("tag", "bold")])

    def test_no_image_blocks(self):
        cs, _ = build(assets=[])
        self.assertIn("product.images", targets(cs))
        self.assertFalse(am.approvable(cs))

    def test_same_listing_same_change_set(self):
        a, _ = build()
        b, _ = build()
        self.assertEqual((a["change_set_id"], a["change_set_hash"]), (b["change_set_id"], b["change_set_hash"]))
        c, _ = build(approved_entry(dict(FACTS, price="460")))
        self.assertNotEqual(a["change_set_hash"], c["change_set_hash"])
        self.assertNotEqual(a["change_set_id"], c["change_set_id"])

    def test_dry_run_writes_nothing(self):
        cs, store = build()
        before = json.dumps(store.tables, sort_keys=True, default=str)
        dry = store.dry_run(cs)
        self.assertFalse(dry["would_publish"])
        self.assertEqual(json.dumps(store.tables, sort_keys=True, default=str), before)
        rows = {r["column"]: r for r in am.preview_rows(cs, dry["plan"], store)}
        self.assertEqual(rows["price"]["value"], "450.00", "shown as the store would store it")
        self.assertEqual(rows["category_id"]["display"], "Originals")
        self.assertEqual(rows["tags"]["display"], ["Bold"])

    def test_test_catalog_is_in_scope_only_and_writes_are_off(self):
        store = am.test_store("storefront-a", MAPPING)
        self.assertNotIn(am.test_id("category", "journal"), store.tables["categories"])
        self.assertFalse(store.writes_enabled)
        self.assertEqual(store.environment, "test")

    def test_price_is_cleaned_or_refused(self):
        self.assertEqual(clean_price("$1,250"), "1250.00")
        self.assertEqual(clean_price("450.5"), "450.50")
        for bad in ("ten", "10.999", "1,25", "-5", ""):
            with self.assertRaises(ValueError, msg=bad):
                clean_price(bad)

    def test_price_and_sold_as_never_reach_the_draft(self):
        self.assertEqual(draft_facts(FACTS), {"medium": "acrylic on canvas", "dimensions": "16 x 20 in", "edition": "original"})


class Approval(unittest.TestCase):
    def setUp(self):
        root = tmp()
        self.audit = Audit(root / "audit")
        self.ap = publication.Approvals(root / "approvals", self.audit)
        self.cs, _ = build()

    def approve(self, cs=None, **kw):
        cs = cs or self.cs
        args = dict(seen_hash=cs["change_set_hash"], status="draft", actor_id="owner")
        args.update(kw)
        return self.ap.approve("fox", cs, **args)

    def test_binds_the_exact_change_set(self):
        a = self.approve()
        self.assertEqual([str(v) for v in policy.validate(a, related=[self.cs])], [])
        self.assertEqual(a["change_set_hash"], self.cs["change_set_hash"])
        self.assertEqual((a["actor"]["role"], a["prepared_by"]["kind"]), ("approver", "service"))
        self.assertEqual(self.ap.status("fox", self.cs)["state"], "current")
        self.assertEqual([e["event"] for e in self.audit.events("fox")], ["storefront_approved"])

    def test_refuses_what_wasnt_seen_or_isnt_ready(self):
        with self.assertRaises(publication.ApprovalError):
            self.approve(seen_hash="b" * 64)
        with self.assertRaises(publication.ApprovalError):
            self.approve(status="active")
        blocked, _ = build(approved_entry({k: v for k, v in FACTS.items() if k != "price"}))
        with self.assertRaises(publication.ApprovalError):
            self.approve(blocked)
        self.assertEqual(self.ap.records("fox"), [], "nothing recorded")

    def test_any_change_puts_it_out_of_date(self):
        self.approve()
        changed = {
            "Price": build(approved_entry(dict(FACTS, price="500")))[0],
            "Images": build(assets=[dict(ASSETS[0], sha256="c" * 64)])[0],
            "Store mapping": build(mapping=dict(MAPPING, version=3))[0],
        }
        for word, cs in changed.items():
            st = self.ap.status("fox", cs)
            self.assertEqual(st["state"], "out_of_date", word)
            self.assertIn(word, st["changes"])
        unlocked = approved_entry()
        copy = unlocked.pop("approved")["copy"]
        store = am.test_store("storefront-a", MAPPING)
        cs = am.build(item=ITEM, entry=unlocked, record=record_for("fox", 3), copy=copy, assets=ASSETS,
                      mapping=MAPPING, store=store)
        self.assertEqual(self.ap.status("fox", cs)["state"], "out_of_date", "unlocking the copy cancels it")

    def test_out_of_date_is_recorded_once(self):
        self.approve()
        cs, _ = build(approved_entry(dict(FACTS, price="500")))
        self.ap.status("fox", cs)
        self.ap.status("fox", cs)
        self.assertEqual(sum(r["event"] == "out_of_date" for r in self.ap.records("fox")), 1)
        self.assertEqual([e["event"] for e in self.audit.events("fox")], ["storefront_approved", "approval_out_of_date"])
        self.approve(cs)
        self.assertEqual(self.ap.status("fox", cs)["state"], "current", "re-approving the new version")

    def test_an_approval_is_for_one_listing(self):
        self.approve()
        self.assertEqual(self.ap.status("owl", self.cs)["state"], "none")


class StorefrontApi(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        out = tmp() / "review"
        (out / "img").mkdir(parents=True)
        (out / "img" / "fox.framed.jpg").write_bytes(b"framed")
        (out / "items.json").write_text(json.dumps([dict(ITEM, status="ready")]))
        mapping = out / "mapping.json"
        mapping.write_text(json.dumps(MAPPING))
        self.app = self.srv.App(out=out, brand_root=out / "brand", learning_root=out / "learning",
                                config=out / "none.json", source=tmp(), rooms_root=tmp() / "rooms", mapping=mapping)
        self.app.store.save_draft("fox", record_for("fox", 1))
        self.out = out

    def test_flow_from_blocked_to_approved_to_out_of_date(self):
        p = self.app.storefront_preview("fox")
        self.assertFalse(p["approvable"])
        self.assertIn("copy.approval", [b["target"] for b in p["blockers"]])
        self.app.store.approve("fox", "owner")
        self.app.update_listing("fox", {"facts": FACTS})
        p = self.app.storefront_preview("fox")
        self.assertTrue(p["approvable"], p["blockers"])
        self.assertEqual(self.app.state()["items"][0]["storefront"], "ready")
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.approve_storefront("fox", {"change_set_hash": "0" * 64, "status": "draft"})
        self.assertEqual(e.exception.code, 409, "a hash the owner didn't see is refused")
        p = self.app.approve_storefront("fox", {"change_set_hash": p["change_set"]["change_set_hash"], "status": "draft"})
        self.assertEqual(p["approval"]["state"], "current")
        self.assertEqual(self.app.state()["items"][0]["storefront"], "approved")
        (self.out / "img" / "fox.framed.jpg").write_bytes(b"re-cropped")
        p = self.app.storefront_preview("fox")
        self.assertEqual((p["approval"]["state"], p["approval"]["changes"]), ("out_of_date", ["Images"]))
        self.assertEqual(self.app.state()["items"][0]["storefront"], "out_of_date")
        events = [e["event"] for e in p["history"]]
        for e in ("drafted", "copy_approved", "facts_saved", "storefront_approved", "approval_out_of_date"):
            self.assertIn(e, events)
        self.assertTrue((self.out.parent / "approvals" / "fox.jsonl").exists(), "beside the review folder")

    def test_bad_requests(self):
        with self.assertRaises(self.srv.ApiError):
            self.app.update_listing("fox", {"facts": {"sold_as": "Poster"}})
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.approve_storefront("fox", {"change_set_hash": "x"})
        self.assertEqual(e.exception.code, 400)
        self.assertEqual(self.app.detail("fox")["tier_types"], MAPPING["tier_types"])

    def test_no_mapping_means_no_preview(self):
        app = self.srv.App(out=self.out, brand_root=self.out / "brand", learning_root=self.out / "learning",
                           config=self.out / "none.json", source=tmp(), rooms_root=tmp() / "rooms",
                           mapping=self.out / "missing.json")
        self.assertFalse(app.storefront_preview("fox")["available"])
        self.assertIsNone(app.state()["items"][0]["storefront"])


class Wiring(unittest.TestCase):
    def test_price_rule_is_the_same_in_both_places(self):
        from packages.drafting import store
        js = re.search(r"const PRICE = /(.+)/;", read(REPO / "apps/review-dashboard/src/components/AboutPiece.tsx")).group(1)
        self.assertEqual(js, store.PRICE.pattern)

    def test_drafting_uses_only_the_copy_facts(self):
        service = read(REPO / "packages/drafting/service.py")
        self.assertEqual(service.count('draft_facts(entry.get("facts"))'), 3, "prompt, canonical draft and the record")
        self.assertNotIn('facts=entry.get("facts")', service)

    def test_after_approval_targets_are_the_same(self):
        js = re.search(r'const AFTER_APPROVAL = "([^"]+)"', read(REPO / "apps/review-dashboard/src/components/StorefrontPanel.tsx")).group(1)
        self.assertEqual((js,), am.AFTER_APPROVAL)

    def test_routes_and_panel_are_wired(self):
        server = read(REPO / "services/local_api/server.py")
        self.assertIn('@route("POST", r"/api/items/([\\w.-]+)/storefront/approve")', server)
        self.assertIn("<StorefrontPanel", read(REPO / "apps/review-dashboard/src/pages/ListingDetail.tsx"))
        self.assertIn("api.approveStorefront(id, p.change_set.change_set_hash", read(REPO / "apps/review-dashboard/src/components/StorefrontPanel.tsx"))
        self.assertIn("price, sold_as: soldAs", read(REPO / "apps/review-dashboard/src/components/AboutPiece.tsx"),
                      "saving About this piece keeps price and sold as")
        self.assertTrue((REPO / "packages" / "adapters" / "artstore_map.py").exists())


if __name__ == "__main__":
    unittest.main()
