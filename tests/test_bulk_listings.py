"""Bulk actions on the Listings page (B-087): tick several pieces, then approve their copy, supply their details,
approve them for the store or redraft them. Each piece follows its own page's rules. No model is called and nothing
is written to a store. All data is invented."""
import json
import unittest

from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, record_for, tmp
from tests.test_storefront_preview import FACTS, ITEM, MAPPING

PAGE = "apps/review-dashboard/src/pages/Listings.tsx"
BAR = "apps/review-dashboard/src/components/BulkBar.tsx"


class Bulk(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        self.dir = tmp()
        out = self.dir / "review"
        (out / "img").mkdir(parents=True)
        (out / "img" / "fox.framed.jpg").write_bytes(b"framed image")
        (out / "img" / "owl.framed.jpg").write_bytes(b"another framed image")
        items = [dict(ITEM, status="ready"),
                 dict(ITEM, id="owl", source="Owl.jpg", framed="img/owl.framed.jpg", art_file="owl.png", status="ready"),
                 dict(ITEM, id="hen", source="Hen.jpg", framed=None, art_file="hen.png", status="ready")]
        (out / "items.json").write_text(json.dumps(items))
        (self.dir / "mapping.json").write_text(json.dumps(MAPPING))
        self.app = self.srv.App(out=out, brand_root=self.dir / "brand", learning_root=self.dir / "learning",
                                config=self.dir / "none.json", source=tmp(), rooms_root=self.dir / "rooms",
                                mapping=self.dir / "mapping.json")
        for i in ("fox", "owl"):
            self.app.store.save_draft(i, record_for(i, 1))
        self.calls = []
        self.app.draft = lambda ids, label: self.calls.append((ids, label)) or {"job": "j"}

    def bulk(self, action, **body):
        return self.app.bulk_listings(dict(body, action=action))

    def skipped(self, res):
        return {s["id"]: s["reason"] for s in res["skipped"]}

    # approving copy
    def test_copy_is_approved_for_every_ticked_piece_it_suits(self):
        self.app.approve("owl")
        res = self.bulk("approve_copy", ids=["fox", "owl", "hen"])
        self.assertEqual(res["done"], ["fox"])
        self.assertEqual(self.skipped(res), {"owl": "Its copy is already approved.", "hen": "Not drafted yet."})
        self.assertTrue(self.app.store.listing("fox").get("approved"))

    # supplying details
    def test_details_fill_only_what_is_empty_unless_asked(self):
        self.app.update_listing("fox", {"facts": dict(FACTS)})
        res = self.bulk("facts", ids=["fox", "owl"], facts={"medium": "Acrylic on panel", "price": "300"})
        self.assertEqual(res["done"], ["owl"])
        self.assertIn("fox", self.skipped(res), "it already had both")
        self.assertEqual(self.app.store.listing("fox")["facts"]["price"], FACTS["price"])
        self.assertEqual(self.app.store.listing("owl")["facts"]["medium"], "Acrylic on panel")
        res = self.bulk("facts", ids=["fox"], facts={"price": "300"}, overwrite=True)
        self.assertEqual((res["done"], self.app.store.listing("fox")["facts"]["price"]), (["fox"], "300.00"))
        self.assertEqual(self.app.store.listing("fox")["facts"]["medium"], FACTS["medium"], "only what was given")

    def test_details_are_checked_like_on_the_piece(self):
        res = self.bulk("facts", ids=["fox"], facts={"sold_as": "Postcard"})
        self.assertIn("tier types", self.skipped(res)["fox"])
        for body in ({"facts": {}}, {"facts": {"colour": "red"}}, {"facts": {"price": "  "}}, {"facts": "300"},
                     {"facts": {"price": "1"}, "overwrite": "yes"}):
            with self.assertRaises(self.srv.ApiError, msg=body):
                self.bulk("facts", ids=["fox"], **body)

    # approving for the store
    def test_the_store_approval_shows_first_then_approves_those_versions(self):
        for i in ("fox", "owl"):
            self.app.update_listing(i, {"facts": dict(FACTS)})
            self.app.approve(i)
        shown = self.bulk("store_preview", ids=["fox", "owl", "hen"])
        self.assertEqual([r["id"] for r in shown["rows"]], ["fox", "owl"])
        self.assertIn("hen", self.skipped(shown))
        self.assertIsNone(self.app.approvals.latest("fox"), "showing approves nothing")
        items = [{"id": r["id"], "change_set_hash": r["change_set_hash"]} for r in shown["rows"]]
        res = self.bulk("approve_store", items=items)
        self.assertEqual(res["done"], ["fox", "owl"])
        self.assertEqual(self.app.approvals.status("fox", self.app.change_set("fox")[0])["state"], "current")
        again = self.bulk("store_preview", ids=["fox"])
        self.assertEqual((again["rows"], list(self.skipped(again))), ([], ["fox"]), "already approved")

    def test_a_piece_changed_since_it_was_shown_is_not_approved(self):
        self.app.update_listing("fox", {"facts": dict(FACTS)})
        self.app.approve("fox")
        row = self.bulk("store_preview", ids=["fox"])["rows"][0]
        self.app.update_listing("fox", {"facts": dict(FACTS, price="999")})
        res = self.bulk("approve_store", items=[{"id": "fox", "change_set_hash": row["change_set_hash"]}])
        self.assertEqual(res["done"], [])
        self.assertEqual(self.skipped(res)["fox"], "It changed since you looked: check it again, then approve.")
        self.assertIsNone(self.app.approvals.latest("fox"))

    def test_a_piece_that_is_not_ready_says_why(self):
        res = self.bulk("store_preview", ids=["owl"])         # no facts, copy not approved
        self.assertEqual(res["rows"], [])
        self.assertTrue(self.skipped(res)["owl"])

    # redrafting
    def test_redraft_only_drafted_pieces_with_open_copy(self):
        self.app.approve("owl")
        res = self.bulk("redraft", ids=["fox", "owl", "hen"])
        self.assertEqual(self.calls, [(["fox"], "Redraft 1 selected piece(s)")])
        self.assertEqual((res["job"], set(self.skipped(res))), ("j", {"owl", "hen"}))
        self.calls.clear()
        res = self.bulk("redraft", ids=["owl"])
        self.assertEqual((self.calls, res["job"]), ([], None), "nothing to redraft calls nothing")

    # requests
    def test_bad_requests_are_refused(self):
        for body in ({}, {"action": "delete", "ids": ["fox"]}, {"action": "approve_copy", "ids": []},
                     {"action": "approve_copy", "ids": "fox"}, {"action": "approve_copy", "ids": ["nope"]},
                     {"action": "approve_copy", "ids": ["fox"] * 61 + ["x"]},
                     {"action": "approve_store", "items": [{"id": "fox"}]}):
            with self.assertRaises(self.srv.ApiError, msg=body) as e:
                self.app.bulk_listings(body)
            self.assertEqual(e.exception.code, 400, body)

    def test_it_is_reachable_and_audited(self):
        self.assertIn('@route("POST", "/api/listings/bulk")', read(REPO / "services/local_api/server.py"))
        self.bulk("approve_copy", ids=["fox"])
        log = (self.dir / "audit" / "listings.jsonl")
        self.assertIn("bulk_approve_copy", log.read_text())


class Page(unittest.TestCase):
    def test_every_card_can_be_ticked(self):
        src = read(REPO / PAGE)
        self.assertIn('<li key={i.id} className="pickable">', src)
        self.assertIn("aria-label={`Select ${i.title || i.source}`}", src)
        self.assertIn("<BulkBar ticked={ticked}", src)

    def test_the_bar_offers_the_four_actions_and_shows_before_store_approval(self):
        bar = read(REPO / BAR)
        for label in ("Approve copy (", "Supply details…", "Approve for store…", "Redraft…", "Draft {undrafted.length} selected"):
            self.assertIn(label, bar)
        self.assertIn('api.bulk("store_preview"', bar)
        self.assertIn('api.bulk("approve_store", { items: rows.map((r) => ({ id: r.id, change_set_hash: r.change_set_hash })) })', bar)
        self.assertIn("one Claude call each", bar)


if __name__ == "__main__":
    unittest.main()
