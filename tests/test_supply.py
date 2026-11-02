"""What a listing still needs supplied (medium, size), and a size read from the file name."""
import re
import unittest

from packages.drafting import listing
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, tmp


class SizeFromName(unittest.TestCase):
    def test_reads_a_size_as_inches(self):
        self.assertEqual(listing.size_from_name("Animal Art 16x20_0005_Lion.jpg"), "16 x 20 in")
        self.assertEqual(listing.size_from_name("a 8.5x11 b.jpg"), "8.5 x 11 in")
        self.assertEqual(listing.size_from_name('Fox 12"x16".jpg'), "12 x 16 in")
        self.assertEqual(listing.size_from_name("print 40 x 50 cm.png"), "40 x 50 cm", "a name that says cm keeps it")

    def test_no_size_from_other_numbers(self):
        for name in ("Abstract-31.jpg", "IMG_1920x1080.jpg", "2024x3.jpg", "0005_0006.jpg", None, ""):
            self.assertIsNone(listing.size_from_name(name), name)
        self.assertIsNone(listing.size_from_name("Thing 1x500.jpg"), "too small or too big to be a size in inches")

    def test_size_from_name_parses_as_a_size(self):
        self.assertEqual(listing.parse_dimensions(listing.size_from_name("Owl 16x20.jpg")),
                         {"width": 16.0, "height": 20.0, "unit": "in"})


class Supplied(unittest.TestCase):
    def test_a_supplied_fact_answers_its_check(self):
        size = {"severity": "blocking", "target": "product.dimensions"}
        medium = {"severity": "blocking", "target": "product.material"}
        claim = {"severity": "blocking", "target": "product.description"}
        facts = {"dimensions": "16 x 20 in"}
        self.assertTrue(listing.supplied(size, facts))
        self.assertFalse(listing.supplied(medium, facts))
        self.assertFalse(listing.supplied(claim, {"medium": "oil", "dimensions": "1 x 1 in"}), "a bad claim is never 'supplied'")
        self.assertFalse(listing.supplied(dict(size, severity="warning"), facts))
        self.assertFalse(listing.supplied(size, None))

    def test_same_rule_on_the_listing_page(self):
        page = read(REPO / "apps/review-dashboard/src/pages/ListingDetail.tsx")
        js = dict(re.findall(r'"(product\.\w+)": "(\w+)"', re.search(r"const SUPPLIED_BY[^{]*\{([^}]*)\}", page).group(1)))
        self.assertEqual(js, listing.SUPPLIED_BY, "SUPPLIED_BY is copied in ListingDetail.tsx: change both")

    def test_wiring(self):
        server = read(REPO / "services/local_api/server.py")
        self.assertIn('"blocking": sum(i["severity"] == "blocking" and not listing.supplied(i, entry.get("facts"))', server,
                      "the list's 'to supply' count drops once the fact is saved")
        self.assertEqual(server.count('listing.size_from_name(it.get("source"))'), 4,
                         "listing page, photo page, and the list and save of sizes from file names")
        about = read(REPO / "apps/review-dashboard/src/components/AboutPiece.tsx")
        for s in ("const fromName = !start.size && sizeFromName ? splitSize(sizeFromName) : null;", "to supply</span>",
                  "✓ Supplied", "Read from the file name", "Still to supply:", 'className="steps"'):
            self.assertIn(s, about)
        for page in ("ListingDetail.tsx", "PhotoDetail.tsx"):
            self.assertIn("sizeFromName={", read(REPO / "apps/review-dashboard/src/pages" / page), page)
        self.assertIn("supplied · redraft", read(REPO / "apps/review-dashboard/src/pages/Listings.tsx"))


class NameSizesApi(unittest.TestCase):
    def setUp(self):
        import json
        self.srv = load_server()
        out = tmp() / "review"
        out.mkdir()
        (out / "items.json").write_text(json.dumps([
            {"id": "lion", "source": "Animal Art 16x20_0005_Lion.jpg", "kind": "artwork", "status": "ready"},
            {"id": "owl", "source": "Owl 12x16.jpg", "kind": "artwork", "status": "ready"},
            {"id": "sized", "source": "Bull 16x20.jpg", "kind": "artwork", "status": "ready"},
            {"id": "plain", "source": "Abstract-31.jpg", "kind": "artwork", "status": "ready"}]))
        self.app = self.srv.App(out=out, brand_root=out / "brand", learning_root=out / "learning",
                                config=out / "none.json", source=tmp(), rooms_root=tmp() / "rooms")
        self.app.store.update("sized", facts={"dimensions": "18 x 24 in"})
        self.app.store.update("lion", facts={"medium": "acrylic on canvas"})

    def test_lists_only_pieces_without_a_size(self):
        got = [(p["id"], p["size"]) for p in self.app.name_sizes()["pieces"]]
        self.assertEqual(got, [("lion", "16 x 20 in"), ("owl", "12 x 16 in")], "not one with a size, not one with no size in its name")

    def test_saves_the_ticked_ones_and_keeps_other_facts(self):
        r = self.app.save_name_sizes({"ids": ["lion", "sized", "plain"]})
        self.assertEqual(r["saved"], [{"id": "lion", "size": "16 x 20 in"}])
        self.assertEqual([s["id"] for s in r["skipped"]], ["sized", "plain"])
        self.assertEqual(self.app.store.listing("lion")["facts"], {"medium": "acrylic on canvas", "dimensions": "16 x 20 in"})
        self.assertEqual(self.app.store.listing("sized")["facts"], {"dimensions": "18 x 24 in"}, "a saved size is kept")
        self.assertNotIn("dimensions", self.app.store.listing("owl").get("facts") or {}, "an unticked piece is left alone")
        self.assertEqual([p["id"] for p in self.app.name_sizes()["pieces"]], ["owl"])

    def test_refuses_a_bad_request_before_saving_anything(self):
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.save_name_sizes({"ids": ["lion", "nope"]})
        self.assertEqual(e.exception.code, 404)
        self.assertNotIn("dimensions", self.app.store.listing("lion").get("facts") or {})
        with self.assertRaises(self.srv.ApiError):
            self.app.save_name_sizes({"ids": "lion"})

    def test_wiring(self):
        server = read(REPO / "services/local_api/server.py")
        self.assertIn('@route("GET", "/api/sizes/from-names")', server)
        self.assertIn('@route("POST", "/api/sizes/from-names")', server)
        drawer = read(REPO / "apps/review-dashboard/src/components/NameSizes.tsx")
        for s in ("api.saveNameSizes([...picked])", "<Drawer", "setPicked(new Set(list.map((p) => p.id)))"):
            self.assertIn(s, drawer)
        self.assertIn("<NameSizes", read(REPO / "apps/review-dashboard/src/pages/Listings.tsx"))


if __name__ == "__main__":
    unittest.main()
