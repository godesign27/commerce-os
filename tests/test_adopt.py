"""Linking a piece to a product made in the store's admin (B-092): its images then go to that product as an update,
and nothing else there changes. No store is written; the store's row is a stand-in. All data is invented."""
import json
import unittest

from packages.adapters import updates
from packages.publisher import records as pub
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, tmp
from tests.test_storefront_preview import ITEM, MAPPING

ROW = {"id": "store-earth-1", "name": "Earth Signal", "status": "active", "slug": "earth-signal",
       "dimensions": '16"x20"', "medium": "Acrylic on paper", "price": "995.00",
       "images": ["/objects/uploads/old-room", "/objects/uploads/old-plain"]}


class Adopt(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        self.dir = tmp()
        out = self.dir / "review"
        (out / "img").mkdir(parents=True)
        (out / "img" / "fox.framed.jpg").write_bytes(b"framed image")
        (out / "items.json").write_text(json.dumps([dict(ITEM, status="ready", art_file="fox.png"),
                                                    dict(ITEM, id="owl", source="Owl.jpg", status="ready", art_file="owl.png")]))
        (self.dir / "mapping.json").write_text(json.dumps(MAPPING))
        self.rows = {"store-earth-1": dict(ROW)}
        self.app = self.srv.App(out=out, brand_root=self.dir / "brand", learning_root=self.dir / "learning",
                                config=self.dir / "none.json", source=tmp(), rooms_root=self.dir / "rooms",
                                mapping=self.dir / "mapping.json", read_product=lambda pid: self.rows.get(pid))

    def cs(self):
        self.app._rows.clear()
        return self.app.change_set("fox")[0]

    def test_linking_takes_the_store_size_and_medium_and_marks_it_in_the_store(self):
        res = self.app.adopt("fox", {"product_id": "store-earth-1"})
        self.assertEqual(res["name"], "Earth Signal")
        facts = self.app.store.listing("fox")["facts"]
        self.assertEqual((facts["dimensions"], facts["medium"]), ("16 x 20 in", "Acrylic on paper"),
                         "so it hangs in its room at its real size")
        self.assertEqual(self.app.pubs.state("fox"), pub.SUCCEEDED)
        self.assertIsNone(self.app.approvals.latest("fox"), "linking approves nothing")

    def test_only_the_images_go_and_only_as_an_update(self):
        self.app.adopt("fox", {"product_id": "store-earth-1"})
        cs = self.cs()
        op = cs["operations"][0]
        self.assertEqual((op["op"], op["key"], list(op["fields"])), ("update", "store-earth-1", ["images"]))
        self.assertEqual(op["precondition"]["expected_fields"], {"images": ROW["images"]})
        self.assertTrue(self.app._pending_update("fox", cs))
        self.assertEqual(self.app._status_of("fox")["id"], "changed")
        self.assertEqual(cs["requested_status"], updates.UPDATE_STATUS, "the store keeps its status")

    def test_it_needs_no_draft_to_be_approved_and_sent(self):
        self.app.adopt("fox", {"product_id": "store-earth-1"})
        self.assertIsNone(self.app.store.draft("fox"))
        shown = self.app.bulk_listings({"action": "store_preview", "ids": ["fox"]})
        self.assertEqual([r["id"] for r in shown["rows"]], ["fox"])
        self.assertTrue(shown["rows"][0]["update"])
        self.assertIn("fox", [r["id"] for r in self.app.publish_queue()["changed"]], "it's on the Publish page")

    def test_an_image_edit_in_the_store_wins(self):
        self.app.adopt("fox", {"product_id": "store-earth-1"})
        self.rows["store-earth-1"]["images"] = ["/objects/uploads/owner-chose-this"]
        self.assertFalse(self.app._pending_update("fox", self.cs()))
        self.assertEqual(self.app._status_of("fox")["id"], "published")

    def test_links_are_one_to_one_and_checked(self):
        self.app.adopt("fox", {"product_id": "store-earth-1"})
        for item, body, code in (("fox", {"product_id": "store-earth-1"}, 409),       # already linked
                                 ("owl", {"product_id": "store-earth-1"}, 409),       # product taken
                                 ("owl", {"product_id": "nope"}, 404),                # not in the store
                                 ("owl", {"product_id": "bad id!"}, 400), ("owl", {}, 400)):
            with self.assertRaises(self.srv.ApiError, msg=body) as e:
                self.app.adopt(item, body)
            self.assertEqual(e.exception.code, code, body)

    def test_choices_leave_out_linked_products(self):
        self.app.catalog.load = lambda: {"read_at": "2026-11-18", "products": [
            dict(ROW), {"id": "store-other", "name": "Bound in Resolve", "dimensions": '36"x36"'}]}
        self.assertEqual([p["id"] for p in self.app.store_choices()["products"]], ["store-other", "store-earth-1"])
        self.app.adopt("fox", {"product_id": "store-earth-1"})
        self.assertEqual([p["id"] for p in self.app.store_choices()["products"]], ["store-other"])

    def test_sizes_read_the_store_way(self):
        size = self.srv.App._store_size
        self.assertEqual((size('16"x20"'), size("16 x 20 inches"), size("30 x 30 cm"), size("Large")),
                         ("16 x 20 in", "16 x 20 in", "30 x 30 cm", ""))

    def test_it_is_reachable(self):
        src = read(REPO / "services/local_api/server.py")
        self.assertIn('@route("POST", r"/api/items/([\\w.-]+)/adopt")', src)
        self.assertIn('@route("GET", "/api/store-products")', src)


class Page(unittest.TestCase):
    def test_the_listing_page_offers_the_link_until_it_is_in_the_store(self):
        page = read(REPO / "apps/review-dashboard/src/pages/ListingDetail.tsx")
        self.assertIn("{!dr && !IN_STORE.includes(d.status.id) && <LinkToStore id={id}", page)
        self.assertIn("api.adopt(id, pick)", page)
        self.assertIn("Already in the store?", page)


if __name__ == "__main__":
    unittest.main()
