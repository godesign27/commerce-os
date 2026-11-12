"""The white mat, on or off per piece (B-080): canvases are framed with the oak frame against the artwork.
All data is invented; rendering needs Pillow."""
import importlib.util
import json
import unittest

from packages.image_pipeline import framing, rooms, stages
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, tmp
from tests.test_photos import ART, PHOTO

spec = importlib.util.spec_from_file_location("review_images", REPO / "scripts" / "review_images.py")
ri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ri)


class Recipe(unittest.TestCase):
    def test_no_mat_floats_the_art_in_the_frame_and_keeps_everything_else(self):
        mat, bare = framing.load_recipe(ri.MAT_RECIPE), framing.load_recipe(ri.NO_MAT_RECIPE)
        self.assertEqual(bare["id"], ri.NO_MAT_RECIPE)
        for k in ("canvas", "frame", "shadow", "output"):
            self.assertEqual(bare[k], mat[k], k)
        lay = framing.layout((400, 500), bare)
        art_w = lay.art[2] - lay.art[0]
        gaps = (lay.art[0] - lay.opening[0], lay.art[1] - lay.opening[1],
                lay.opening[2] - lay.art[2], lay.opening[3] - lay.art[3])
        for g in gaps:                                       # a narrow gap all round, like a floater frame (B-084)
            self.assertTrue(0.01 * art_w <= g <= 0.03 * art_w, gaps)
        m = framing.layout((400, 500), mat)
        self.assertGreater(m.art[0] - m.opening[0], 4 * gaps[0], "much narrower than a mat")

    def test_the_gap_is_a_shadow_not_a_mat(self):
        gap, white = framing.load_recipe(ri.NO_MAT_RECIPE)["mat"], framing.load_recipe(ri.MAT_RECIPE)["mat"]
        self.assertLess(sum(gap["rgb"]), sum(white["rgb"]) * 0.7, "darker than the white mat")
        self.assertGreater(gap["inner_shadow"]["opacity"], 0)

    def test_a_piece_framed_with_an_older_recipe_waits_to_be_applied(self):
        v = framing.load_recipe(ri.NO_MAT_RECIPE)["version"]
        old = {"id": "a", "frame": {"recipe": ri.NO_MAT_RECIPE, "recipe_version": v - 1}}
        new = {"id": "b", "frame": {"recipe": ri.NO_MAT_RECIPE, "recipe_version": v}}
        self.assertEqual(ri.pending({}, [old, new, {"id": "c"}, {"id": "d", "frame": {"recipe": "gone", "recipe_version": 1}}]),
                         {"a"})
        self.assertTrue(framing.outdated(old["frame"]))
        self.assertFalse(framing.outdated(new["frame"]))

    def test_the_art_is_bigger_without_a_mat(self):
        a = framing.layout((400, 500), framing.load_recipe(ri.MAT_RECIPE)).art
        b = framing.layout((400, 500), framing.load_recipe(ri.NO_MAT_RECIPE)).art
        self.assertGreater(b[2] - b[0], a[2] - a[0])


class Decisions(unittest.TestCase):
    def test_only_no_mat_is_stored(self):
        self.assertEqual(ri.validate_decisions({"a": {"decision": None, "mat": False}})["a"].get("mat"), False)
        self.assertNotIn("mat", ri.validate_decisions({"a": {"decision": None, "mat": True}})["a"])
        with self.assertRaises(ValueError):
            ri.validate_decisions({"a": {"decision": None, "mat": "no"}})

    def test_a_changed_mat_waits_to_be_applied(self):
        items = [{"id": "a", "applied": {"corners": None, "rotate": 0}},
                 {"id": "b", "applied": {"corners": None, "rotate": 0, "mat": False}},
                 {"id": "c", "applied": {"corners": None, "rotate": 0, "mat": False}}]
        decisions = {"a": {"decision": None, "mat": False}, "b": {"decision": None, "mat": False}, "c": {"decision": None}}
        self.assertEqual(ri.pending(decisions, items), {"a", "c"})
        self.assertEqual(ri.pending({}, [{"id": "d"}]), set(), "older pieces had the mat")

    def test_turning_it_off_is_a_dated_change(self):
        out = ri.stamp_changes({"a": {"decision": None}}, {"a": {"decision": None, "mat": False}}, "2026-11-10T00:00:00Z")
        self.assertEqual(out["a"]["decided_at"], "2026-11-10T00:00:00Z")


class Rendering(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.dir = tmp()
        self.src = self.dir / "Canvas.png"
        Image.new("RGB", (400, 500), (30, 90, 200)).save(self.src)

    def test_the_framed_image_follows_the_choice(self):
        on = ri.process(self.src, self.dir / "a")
        off = ri.process(self.src, self.dir / "b", mat=False)
        self.assertEqual((on["frame"]["recipe"], off["frame"]["recipe"]), (ri.MAT_RECIPE, ri.NO_MAT_RECIPE))
        self.assertEqual((on["applied"]["mat"], off["applied"]["mat"]), (True, False))

    def test_applying_uses_the_saved_choice(self):
        out = self.dir / "review"
        out.mkdir()
        sid = ri.slug(self.src.name)
        (out / ri.DECISIONS).write_text(json.dumps({sid: {"decision": None, "mat": False}}))
        items = ri.build(self.dir, out, log=lambda *_: None)
        self.assertEqual(next(i for i in items if i["id"] == sid)["frame"]["recipe"], ri.NO_MAT_RECIPE)

    def test_the_room_view_uses_the_same_frame(self):
        self.assertEqual(rooms.recipe_of({"frame": {"recipe": ri.NO_MAT_RECIPE}}), ri.NO_MAT_RECIPE)
        self.assertEqual(rooms.recipe_of({}), ri.MAT_RECIPE)
        piece, lay = rooms.framed_piece(self.src, ri.NO_MAT_RECIPE)
        bare = framing.layout((400, 500), framing.load_recipe(ri.NO_MAT_RECIPE), lay.canvas[0])
        self.assertEqual((lay.opening, lay.art), (bare.opening, bare.art), "the room view floats it the same way")

    def test_hanging_a_piece_uses_its_frame(self):
        from tests.test_rooms import ROOM
        from PIL import Image
        root = self.dir / "rooms"
        (root / "files").mkdir(parents=True)
        Image.new("RGB", (1000, 800), (210, 200, 190)).save(root / "files" / f"{ROOM['id']}.jpg")
        seen = []
        real = rooms.framed_piece
        rooms.framed_piece = lambda art, recipe_id="framed-oak-white-mat": (seen.append(recipe_id), real(art, recipe_id))[1]
        try:
            item = {"id": "c", "art_file": str(self.src), "frame": {"recipe": ri.NO_MAT_RECIPE}}
            rooms.render_item(item, {"rooms": [ROOM]}, root, self.dir / "out", "16 x 20 in", [ROOM])
        finally:
            rooms.framed_piece = real
        self.assertEqual(seen, [ri.NO_MAT_RECIPE])


class Api(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        self.out = tmp() / "review"
        self.out.mkdir()
        (self.out / "items.json").write_text(json.dumps([PHOTO, ART]))
        self.app = self.srv.App(out=self.out, brand_root=self.out / "brand", learning_root=self.out / "learning",
                                config=self.out / "none.json", source=tmp())

    def test_turning_the_mat_off_and_on(self):
        row = self.app.decide_photo("art-1-def", {"mat": False})
        self.assertEqual(row["stage"], "not-applied")
        saved = json.loads((self.out / "decisions.json").read_text())["art-1-def"]
        self.assertIs(saved["mat"], False)
        self.assertFalse(self.app.photo("art-1-def")["mat"])
        self.assertTrue(self.app.photo("art-1-def")["applied"]["mat"], "the framed image still has its mat")
        self.app.decide_photo("art-1-def", {"note": "canvas"})
        self.assertIs(json.loads((self.out / "decisions.json").read_text())["art-1-def"]["mat"], False, "a note keeps it")
        self.app.decide_photo("art-1-def", {"mat": True})
        self.assertNotIn("mat", json.loads((self.out / "decisions.json").read_text())["art-1-def"])
        self.assertNotEqual(self.app.photo("art-1-def")["stage"], "not-applied")

    def test_only_true_or_false(self):
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.decide_photo("art-1-def", {"mat": "off"})
        self.assertEqual(e.exception.code, 400)


class Wiring(unittest.TestCase):
    def test_the_photo_page_has_the_switch(self):
        page = read(REPO / "apps/review-dashboard/src/pages/PhotoDetail.tsx")
        self.assertIn("onChange={(e) => send({ mat: e.target.checked })}", page)
        self.assertIn("White mat", page)

    def test_the_stage_shows_both_sides(self):
        self.assertIn('"mat": decision.get("mat", True)', read(REPO / "packages/image_pipeline/stages.py"))


if __name__ == "__main__":
    unittest.main()
