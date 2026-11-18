"""Usual pricing tiers (B-078): learned from the store, used only once the owner confirms them. All data is invented."""
import unittest

from packages import onboarding as ob
from packages.adapters import tier_ladders as tl
from tests._helpers import REPO, read
from tests.test_onboarding import CHOICES, SNAP
from tests.test_storefront_preview import FACTS, MAPPING, approved_entry, build


def tier(kind, size, price, description="Enter description", stock=100):
    return {"id": "t", "type": kind, "size": size, "price": price, "description": description, "stock": stock}


PRINTS = [tier("Print", "16 x 20 inches", 185, "Limited Edition Print."), tier("Print", "24 x 30 inches", 275),
          tier("Canvas Print", "16 x 20 inches", 300)]


def product(original_size, extras=PRINTS, original_price=995):
    return [tier("Original", original_size, original_price, stock=1)] + [dict(t) for t in extras]


class SizeKey(unittest.TestCase):
    def test_the_store_writes_the_same_size_many_ways(self):
        for text in ("16 x 20 inches", "16x20", '16"x20" Original', "16 × 20 in", "16.0 x 20"):
            self.assertEqual(tl.size_key(text), "16x20", text)
        self.assertIsNone(tl.size_key("large"))
        self.assertIsNone(tl.size_key(None))


class Propose(unittest.TestCase):
    def test_the_most_common_ladder_for_each_size(self):
        odd = [tier("Print", "16 x 20 inches", 475)]
        found = tl.propose([product("16 x 20 inches"), product("16x20"), product("16 x 20 inches", odd)])
        self.assertEqual(len(found), 1)
        p = found[0]
        self.assertEqual((p["size"], p["label"], p["based_on"], p["of"], p["original_stock"]), ("16x20", "16 × 20 in", 2, 3, 1))
        self.assertEqual([(t["type"], t["size"], t["price"], t["stock"]) for t in p["tiers"]],
                         [("Print", "16 x 20 inches", 185, 100), ("Print", "24 x 30 inches", 275, 100),
                          ("Canvas Print", "16 x 20 inches", 300, 100)])

    def test_order_in_the_store_does_not_matter(self):
        found = tl.propose([product("16 x 20"), product("16 x 20", list(reversed(PRINTS)))])
        self.assertEqual(found[0]["based_on"], 2)

    def test_a_one_off_is_not_a_habit(self):
        self.assertEqual(tl.propose([product("16 x 20")]), [])
        self.assertEqual(tl.propose([product("16 x 20", [])] * 3), [], "an original sold alone has no ladder to add")

    def test_descriptions_must_be_the_stores_habit_and_never_the_placeholder(self):
        one_off = [tier("Print", "16 x 20 inches", 185, "Stretched canvas print")] + PRINTS[1:]
        found = tl.propose([product("16 x 20"), product("16 x 20"), product("16 x 20", one_off)])
        by = {(t["type"], t["price"]): t["description"] for t in found[0]["tiers"]}
        self.assertEqual(by[("Print", 185)], "Limited Edition Print.")
        self.assertEqual(by[("Print", 275)], "", "the admin's 'Enter description' isn't copied")

    def test_sizes_are_kept_apart(self):
        square = [tier("Print", "30 x 30 inches", 325)]
        found = tl.propose([product("16 x 20"), product("16 x 20"), product('30"x30" Original', square),
                            product("30 x 30", square)])
        self.assertEqual([p["size"] for p in found], ["16x20", "30x30"])
        self.assertEqual(found[1]["tiers"][0]["price"], 325)

    def test_products_without_an_original_are_ignored(self):
        self.assertEqual(tl.propose([PRINTS, PRINTS, ["not a tier"]]), [])

    def test_the_read_takes_only_active_products(self):
        class Rows:
            def rows(self, sql):
                self.sql = sql
                return [{"pricing_tiers": product("16 x 20")}, {"pricing_tiers": None}]
        pg = Rows()
        self.assertEqual(len(tl.read(pg)), 1)
        self.assertIn("status = 'active'", pg.sql)


LADDER = {"size": "16x20", "label": "16 × 20 in", "based_on": 7, "of": 13, "original_stock": 1,
          "tiers": [{"type": "Print", "size": "16 x 20 inches", "price": 185, "description": "Limited Edition Print.", "stock": 100},
                    {"type": "Canvas Print", "size": "16 x 20 inches", "price": 300, "description": "", "stock": 100}]}


class Confirm(unittest.TestCase):
    def build(self, choices, old=None):
        return ob.build_mapping("storefront-c", dict(SNAP, tier_ladders=[LADDER]), choices, old, "2026-11-09")

    def test_a_ticked_ladder_is_kept_with_when_it_was_confirmed(self):
        m = self.build(dict(CHOICES, tier_ladders=["16x20"]))
        self.assertEqual(m["tier_ladders"]["16x20"]["tiers"], LADDER["tiers"])
        self.assertEqual(m["tier_ladders"]["16x20"]["confirmed"], "2026-11-09")

    def test_only_ladders_the_store_showed(self):
        with self.assertRaises(ob.SetupError):
            self.build(dict(CHOICES, tier_ladders=["99x99"]))
        with self.assertRaises(ob.SetupError):
            self.build(dict(CHOICES, tier_ladders="16x20"))

    def test_unticking_removes_it_and_leaving_it_out_keeps_it(self):
        kept = self.build(dict(CHOICES, tier_ladders=["16x20"]))
        self.assertEqual(self.build(dict(CHOICES, tier_ladders=[]), kept)["tier_ladders"], {})
        self.assertIn("16x20", self.build(CHOICES, kept)["tier_ladders"], "an older page that doesn't send it changes nothing")

    def test_nothing_is_added_without_confirming(self):
        self.assertEqual(self.build(CHOICES)["tier_ladders"], {})


def tiers_of(cs):
    return cs["operations"][0]["fields"]["pricing_tiers"]["value"]


class OnTheListing(unittest.TestCase):
    CONFIRMED = dict(MAPPING, tier_ladders={"16x20": {k: LADDER[k] for k in ("tiers", "original_stock", "based_on")}})

    def test_an_original_gets_the_ladder_for_its_size(self):
        cs, _ = build(mapping=self.CONFIRMED)
        got = tiers_of(cs)
        self.assertEqual([(t["type"], t["price"], t.get("stock")) for t in got],
                         [("Original", 450, 1), ("Print", 185, 100), ("Canvas Print", 300, 100)])
        self.assertEqual(got[1]["description"], "Limited Edition Print.")
        self.assertEqual(len({t["id"] for t in got}), 3, "every tier has its own id")
        self.assertNotIn("pricing_tiers[].stock", cs["not_touched"])

    def test_every_tier_has_a_description(self):
        got = tiers_of(build(mapping=self.CONFIRMED)[0])
        self.assertEqual([t["description"] for t in got],
                         ["16 × 20 in original", "Limited Edition Print.", "16 × 20 in canvas print"],
                         "the store refuses to save a product when any tier's description is blank")
        self.assertEqual(tiers_of(build()[0])[0]["description"], "16 × 20 in original", "a lone original too")

    def test_a_description_is_its_own_unless_blank_or_the_placeholder(self):
        d = tl.describe
        self.assertEqual(d({"type": "Print", "size": "16 x 20", "description": " Signed. "}), "Signed.")
        self.assertEqual(d({"type": "Print", "size": "16 x 20", "description": "Enter description"}), "16 × 20 in print")
        self.assertEqual(d({"type": "Original", "size": "Large", "description": None}), "Large original")
        self.assertEqual(d({"type": "Original"}), "Original")
        self.assertEqual(d({}), "Piece")

    def test_the_same_listing_gives_the_same_tiers_every_time(self):
        self.assertEqual(build(mapping=self.CONFIRMED)[0]["change_set_hash"], build(mapping=self.CONFIRMED)[0]["change_set_hash"])

    def test_no_ladder_without_confirming_or_for_another_size(self):
        cs, _ = build()
        self.assertEqual(len(tiers_of(cs)), 1)
        self.assertIn("pricing_tiers[].stock", cs["not_touched"])
        other = approved_entry(dict(FACTS, dimensions="30 x 30 in"))
        self.assertEqual(len(tiers_of(build(entry=other, mapping=self.CONFIRMED)[0])), 1)

    def test_a_print_gets_no_ladder(self):
        entry = approved_entry(dict(FACTS, sold_as="Print", edition="print"))
        self.assertEqual(len(tiers_of(build(entry=entry, mapping=self.CONFIRMED)[0])), 1)


class Wiring(unittest.TestCase):
    def test_the_store_check_saves_the_proposals(self):
        self.assertIn('"tier_ladders": tier_ladders.propose(tier_ladders.read(pg))', read(REPO / "packages/adapters/catalog.py"))

    def test_getting_started_offers_them_and_sends_the_ticks(self):
        src = read(REPO / "apps/review-dashboard/src/pages/GettingStarted.tsx")
        self.assertIn("<legend>Usual pricing tiers</legend>", src)
        self.assertIn("tier_ladders: ladders", src)
        server = read(REPO / "services/local_api/server.py")
        self.assertIn('"tier_ladders": snap.get("tier_ladders") or []', server)
        self.assertIn('"tier_ladders": sorted(mapping.get("tier_ladders") or {})', server)


if __name__ == "__main__":
    unittest.main()
