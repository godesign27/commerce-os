"""The framed listing image recipe (B-050).

Layout tests are stdlib-only. Rendering tests need Pillow (the project .venv) and are skipped without it.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from packages.image_pipeline import framing
from tests._helpers import REPO

RECIPE = framing.load_recipe()
HAS_PIL = importlib.util.find_spec("PIL") is not None

# Measured from the owner's framed example (1024 x 1536, artwork 624 x 818 as displayed).
MEASURED_FRAME = (80, 197, 943, 1306)
MEASURED_ART = (200, 319, 824, 1137)


def inside(inner, outer):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


class Recipe(unittest.TestCase):
    def test_recipe_is_versioned_and_not_consequential(self):
        self.assertEqual(RECIPE["id"], "framed-oak-white-mat")
        self.assertIsInstance(RECIPE["version"], int)
        self.assertIs(RECIPE["consequential"], False)   # the artwork is only resized, never edited

    def test_recipe_filename_matches_id(self):
        for p in (REPO / "resources" / "image-recipes").glob("*.json"):
            self.assertEqual(json.loads(p.read_text())["id"], p.stem)

    def test_no_texture_asset_is_committed(self):
        committed = list((REPO / "resources" / "image-recipes").rglob("*.png"))
        self.assertEqual(committed, [], "frame textures are local assets (.commerce-os/assets/)")


class Layout(unittest.TestCase):
    def test_reproduces_the_owners_example(self):
        lay = framing.layout((624, 818), RECIPE)
        self.assertEqual(lay.canvas, (1024, 1536))
        for got, want in zip(lay.frame + lay.art, MEASURED_FRAME + MEASURED_ART):
            self.assertLessEqual(abs(got - want), 2, (lay.frame, lay.art))

    def test_mat_is_bottom_weighted(self):
        lay = framing.layout((800, 1000), RECIPE)
        top = lay.art[1] - lay.opening[1]
        bottom = lay.opening[3] - lay.art[3]
        side = lay.art[0] - lay.opening[0]
        self.assertGreater(bottom, top)
        self.assertLessEqual(abs(side - (lay.opening[2] - lay.art[2])), 1, "sides are equal")

    def test_any_aspect_fits_on_the_canvas(self):
        for size in ((600, 750), (1000, 1000), (2000, 1000), (500, 2000), (5712, 4284)):
            with self.subTest(size=size):
                lay = framing.layout(size, RECIPE)
                canvas = (0, 0) + lay.canvas
                self.assertTrue(inside(lay.frame, canvas))
                self.assertTrue(inside(lay.opening, lay.frame))
                self.assertTrue(inside(lay.art, lay.opening))
                aw, ah = lay.art[2] - lay.art[0], lay.art[3] - lay.art[1]
                self.assertAlmostEqual(ah / aw, size[1] / size[0], delta=0.01)

    def test_frame_is_centred_horizontally(self):
        lay = framing.layout((1000, 1250), RECIPE)
        self.assertLessEqual(abs(lay.frame[0] - (lay.canvas[0] - lay.frame[2])), 1)

    def test_canvas_follows_the_artworks_shape(self):
        for size, shape, canvas in (((800, 1000), "portrait", (1024, 1536)), ((1000, 1000), "square", (1280, 1280)),
                                    ((1000, 1030), "square", (1280, 1280)), ((1500, 1000), "landscape", (1536, 1024))):
            with self.subTest(size=size):
                lay = framing.layout(size, RECIPE)
                self.assertEqual((lay.orientation, lay.canvas), (shape, canvas))

    def test_square_tolerance(self):
        self.assertEqual(framing.orientation((1000, 1049), RECIPE), "square")
        self.assertEqual(framing.orientation((1000, 1100), RECIPE), "portrait")
        self.assertEqual(framing.orientation((1100, 1000), RECIPE), "landscape")

    def test_every_orientation_fills_its_canvas_similarly(self):
        # the frame should take a similar share of the canvas whatever the artwork's shape
        shares = []
        for size in ((800, 1000), (1000, 1000), (1500, 1000)):
            lay = framing.layout(size, RECIPE)
            fw, fh = lay.frame[2] - lay.frame[0], lay.frame[3] - lay.frame[1]
            shares.append(fw * fh / (lay.canvas[0] * lay.canvas[1]))
        self.assertLess(max(shares) - min(shares), 0.15, shares)

    def test_scales_with_canvas_width(self):
        small, big = framing.layout((800, 1000), RECIPE, 1024), framing.layout((800, 1000), RECIPE, 2048)
        self.assertEqual(big.canvas, (2048, 3072))
        self.assertAlmostEqual(big.frame_px / small.frame_px, 2, delta=0.1)

    def test_rejects_empty_artwork(self):
        with self.assertRaises(ValueError):
            framing.layout((0, 100), RECIPE)


@unittest.skipUnless(HAS_PIL, "Pillow not installed (use the project .venv)")
class Render(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp = Path(tempfile.mkdtemp(prefix="cos-frame-"))
        self.src = self.tmp / "art.png"
        Image.new("RGB", (400, 500), (20, 40, 200)).save(self.src)

    def test_writes_a_new_file_and_never_touches_the_original(self):
        before = self.src.read_bytes()
        record = framing.frame_artwork(self.src, self.tmp / "out.png")
        self.assertEqual(self.src.read_bytes(), before)
        self.assertEqual(record["source_sha256"], framing.sha256_file(self.src))
        self.assertTrue((self.tmp / "out.png").exists())
        self.assertEqual((record["recipe"], record["recipe_version"]), (RECIPE["id"], RECIPE["version"]))

    def test_refuses_to_overwrite_the_original(self):
        with self.assertRaises(ValueError):
            framing.frame_artwork(self.src, self.src)

    def test_artwork_pixels_are_placed_unchanged(self):
        from PIL import Image
        framing.frame_artwork(self.src, self.tmp / "out.png")
        out = Image.open(self.tmp / "out.png").convert("RGB")
        lay = framing.layout((400, 500), RECIPE)
        cx, cy = (lay.art[0] + lay.art[2]) // 2, (lay.art[1] + lay.art[3]) // 2
        self.assertEqual(out.getpixel((cx, cy)), (20, 40, 200))
        mx = (lay.opening[0] + lay.art[0]) // 2
        self.assertEqual(out.getpixel((mx, cy)), tuple(RECIPE["mat"]["rgb"]))
        self.assertEqual(out.getpixel((5, 5)), tuple(RECIPE["canvas"]["background_rgb"]))

    def test_follows_exif_rotation(self):
        from PIL import Image
        rotated = self.tmp / "phone.jpg"
        exif = Image.Exif()
        exif[0x0112] = 6                          # "rotate 90° clockwise to display"
        Image.new("RGB", (500, 400), (200, 30, 30)).save(rotated, exif=exif)
        record = framing.frame_artwork(rotated, self.tmp / "out.png")
        art = record["layout"]["art"]
        self.assertGreater(art[3] - art[1], art[2] - art[0], "displayed portrait, as the phone showed it")

    def test_frame_uses_the_house_oak_tone_or_the_fallback(self):
        from PIL import Image, ImageStat
        record = framing.frame_artwork(self.src, self.tmp / "out.png")
        out = Image.open(self.tmp / "out.png").convert("RGB")
        l, t, r, _ = record["layout"]["frame"]
        f = record["layout"]["frame_px"]
        mean = ImageStat.Stat(out.crop((l + f * 3, t + 2, r - f * 3, t + f - 2))).mean
        target = (RECIPE["frame"]["texture"]["tone_rgb"] if record["texture"] == "asset"
                  else RECIPE["frame"]["fallback_rgb"])
        for got, want in zip(mean, target):
            self.assertLessEqual(abs(got - want), 12, (mean, target))


if __name__ == "__main__":
    unittest.main()
