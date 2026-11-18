"""Crop a file that isn't the artwork alone (B-093): a framed piece on a wall, or a mock-up with a mat, is cropped
like a phone photo when the owner turns Crop it on. All data is invented; rendering needs Pillow."""
import json
import unittest

from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, tmp
from tests.test_mat import ri
from tests.test_photos import ART, PHOTO


class Decisions(unittest.TestCase):
    def test_only_crop_it_is_stored(self):
        self.assertIs(ri.validate_decisions({"a": {"decision": None, "crop": True}})["a"]["crop"], True)
        self.assertNotIn("crop", ri.validate_decisions({"a": {"decision": None, "crop": False}})["a"])
        with self.assertRaises(ValueError):
            ri.validate_decisions({"a": {"decision": None, "crop": "yes"}})

    def test_turning_it_on_waits_to_be_applied(self):
        items = [{"id": "a", "applied": {"corners": None, "rotate": 0}},
                 {"id": "b", "applied": {"corners": None, "rotate": 0, "crop": True}}]
        self.assertEqual(ri.pending({"a": {"decision": None, "crop": True}, "b": {"decision": None, "crop": True}}, items), {"a"})
        self.assertEqual(ri.pending({}, [{"id": "c"}]), set(), "older pieces were never cropped on request")


class Processing(unittest.TestCase):
    def test_a_file_asked_to_be_cropped_is_cropped_like_a_photo(self):
        from PIL import Image
        d = tmp()
        src = d / "Mockup-Framed.png"
        im = Image.new("RGB", (800, 900), (245, 245, 245))
        im.paste(Image.new("RGB", (500, 600), (30, 30, 30)), (150, 150))
        im.save(src)
        plain = ri.process(src, d / "a")
        cropped = ri.process(src, d / "b", force_crop=True)
        self.assertEqual((plain["kind"], cropped["kind"]), ("artwork", "photo"))
        self.assertEqual(cropped["photo_size"], [800, 900])
        self.assertIs(cropped["applied"]["crop"], True)
        self.assertLess(cropped["art_size"][0], 800, "the backdrop is cut away")


class Api(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        self.out = tmp() / "review"
        self.out.mkdir()
        (self.out / "items.json").write_text(json.dumps([PHOTO, ART]))
        self.app = self.srv.App(out=self.out, brand_root=self.out / "brand", learning_root=self.out / "learning",
                                config=self.out / "none.json", source=tmp())

    def test_turning_crop_on_and_off(self):
        row = self.app.decide_photo("art-1-def", {"crop": True})
        self.assertEqual(row["stage"], "not-applied")
        self.assertIs(json.loads((self.out / "decisions.json").read_text())["art-1-def"]["crop"], True)
        self.assertTrue(self.app.photo("art-1-def")["crop"])
        self.app.decide_photo("art-1-def", {"crop": False})
        self.assertNotIn("crop", json.loads((self.out / "decisions.json").read_text())["art-1-def"])
        with self.assertRaises(self.srv.ApiError):
            self.app.decide_photo("art-1-def", {"crop": "on"})

    def test_the_photo_page_offers_it_for_ready_cut_files(self):
        page = read(REPO / "apps/review-dashboard/src/pages/PhotoDetail.tsx")
        self.assertIn('{(p.kind === "artwork" || p.crop) && (', page)
        self.assertIn("onChange={(e) => send({ crop: e.target.checked })}", page)


if __name__ == "__main__":
    unittest.main()
