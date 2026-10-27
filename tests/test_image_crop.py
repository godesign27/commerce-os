"""Find, straighten and crop the artwork in a photo (B-053).

Geometry tests are stdlib-only. Detection tests build synthetic photos (a grey painted canvas on an
orange "floor") and need Pillow; they're skipped without it.
"""
import importlib.util
import math
import random
import tempfile
import unittest
from pathlib import Path

from packages.image_pipeline import crop

RECIPE = crop.load_recipe()
HAS_PIL = importlib.util.find_spec("PIL") is not None
SQUARE = [(0, 0), (100, 0), (100, 100), (0, 100)]


class Geometry(unittest.TestCase):
    def test_recipe_is_consequential(self):
        self.assertIs(RECIPE["consequential"], True)

    def test_paper_is_tried_before_canvas(self):
        # on a paper photo the canvas method would find the whole sheet, not the painted area
        methods = RECIPE["detection"]["methods"]
        self.assertLess(methods.index("paper"), methods.index("canvas"))

    def test_paper_crops_are_inset_more(self):
        inset = RECIPE["output"]["inset_ratio"]
        self.assertGreater(inset["paper"], inset["canvas"])
        self.assertEqual(inset["manual"], 0)

    def test_otsu_splits_two_groups(self):
        hist = [0] * 256
        for v, n in ((30, 500), (35, 400), (150, 300), (160, 600)):
            hist[v] = n
        self.assertTrue(35 <= crop.otsu(hist) < 150)

    def test_fit_line_ignores_outliers(self):
        pts = [(u, 2 * u + 5) for u in range(50)] + [(10, 300), (20, -200)]
        a, b = crop.fit_line(pts)
        self.assertAlmostEqual(a, 2, delta=0.01)
        self.assertAlmostEqual(b, 5, delta=0.5)

    def test_intersect(self):
        x, y = crop.intersect((0.0, 10.0), (0.0, 20.0))        # x = 10, y = 20
        self.assertEqual((round(x), round(y)), (10, 20))
        with self.assertRaises(ValueError):
            crop.intersect((1.0, 0.0), (1.0, 0.0))

    def test_output_size_and_inset(self):
        self.assertEqual(crop.output_size(SQUARE), (100, 100))
        inner = crop.inset(SQUARE, 0.1)
        self.assertEqual([tuple(round(c) for c in p) for p in inner], [(5, 5), (95, 5), (95, 95), (5, 95)])

    def test_confidence_check(self):
        ok = crop.check_quad(SQUARE, (120, 120), 9800, RECIPE)
        self.assertTrue(ok.ok, ok.reasons)
        bowtie = [(0, 0), (100, 100), (100, 0), (0, 100)]
        self.assertIn("outline is not convex", crop.check_quad(bowtie, (120, 120), 9800, RECIPE).reasons)
        hollow = crop.check_quad(SQUARE, (120, 120), 2000, RECIPE)
        self.assertTrue(any("fills only" in r for r in hollow.reasons))
        tiny = crop.check_quad([(0, 0), (10, 0), (10, 10), (0, 10)], (1000, 1000), 100, RECIPE)
        self.assertTrue(any("covers" in r for r in tiny.reasons))
        skewed = crop.check_quad([(0, 0), (100, 0), (80, 100), (20, 100)], (120, 120), 7900, RECIPE)
        self.assertTrue(any("perspective" in r for r in skewed.reasons))


def synthetic_photo(path, size=(1200, 1600), quad=((180, 330), (1030, 300), (1050, 1190), (160, 1210)),
                    warm_corner=False, rotate_exif=False, canvas=(150, 148, 140), leak=False):
    """An orange wood-like floor with a grey painted canvas (and black strokes) lying on it."""
    from PIL import Image, ImageDraw
    rnd = random.Random(7)
    im = Image.new("RGB", size, (170, 110, 60))
    d = ImageDraw.Draw(im)
    for y in range(0, size[1], 6):                       # floorboard grain
        shade = rnd.randint(-18, 18)
        d.line((0, y, size[0], y), fill=(170 + shade, 110 + shade // 2, 60), width=3)
    if leak:                                             # a pale patch of floor touching one corner
        x, y = quad[3]
        d.ellipse((x - 90, y - 60, x + 40, y + 90), fill=(160, 150, 135))
    d.polygon(quad, fill=canvas)
    cx, cy = sum(p[0] for p in quad) / 4, sum(p[1] for p in quad) / 4
    for i in range(12):                                  # painted black strokes inside the canvas
        r = 60 + 25 * i
        d.arc((cx - r, cy - r * 0.8, cx + r, cy + r * 0.8), 20 * i, 20 * i + 200, fill=(15, 15, 15), width=18)
    if warm_corner:                                      # a slightly warmer patch at one corner of the canvas
        x, y = quad[1]
        d.polygon([(x - 150, y + 5), (x - 5, y), (x, y + 150)], fill=(175, 150, 120))
    extra = {}
    if rotate_exif:
        im = im.rotate(90, expand=True)                  # stored sideways...
        exif = Image.Exif()
        exif[0x0112] = 6                                 # ...with a flag to rotate it upright
        extra["exif"] = exif
    im.save(path, quality=95, **extra)
    return quad


def synthetic_paper_photo(path, size=(1200, 1600), sheet=((120, 140), (1080, 120), (1100, 1480), (100, 1500)),
                          painted=((220, 260), (980, 240), (995, 1300), (205, 1320)), runoff=False):
    """A white sheet on a dark desk, with a colourful painted area (and white strokes inside it)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, (58, 50, 44))
    d = ImageDraw.Draw(im)
    d.polygon(sheet, fill=(244, 243, 238))
    d.polygon(painted, fill=(40, 150, 170))
    cx, cy = sum(p[0] for p in painted) / 4, sum(p[1] for p in painted) / 4
    for i in range(6):                                   # orange and white strokes, like printed texture
        d.rectangle((cx - 300, cy - 400 + 140 * i, cx + 300, cy - 360 + 140 * i), fill=(230, 120, 40))
        d.rectangle((cx - 200, cy - 340 + 140 * i, cx + 100, cy - 330 + 140 * i), fill=(240, 240, 235))
    if runoff:                                           # dark bars painted right off the edges of the sheet
        for y in (500, 900):
            d.rectangle((0, y, size[0], y + 60), fill=(25, 25, 30))
    im.save(path, quality=95)
    return painted


def max_corner_error(found, want):
    return max(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(found, want))


@unittest.skipUnless(HAS_PIL, "Pillow not installed (use the project .venv)")
class Detection(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cos-crop-"))

    def detect(self, **kw):
        path = self.tmp / "photo.jpg"
        quad = synthetic_photo(path, **kw)
        return crop.detect(crop.open_photo(path), RECIPE), quad

    def test_finds_the_corners(self):
        proposal, quad = self.detect()
        self.assertTrue(proposal.check.ok, proposal.check.reasons)
        self.assertLess(max_corner_error(proposal.corners, quad), 15)

    def test_a_warm_corner_doesnt_drag_the_outline(self):
        proposal, quad = self.detect(warm_corner=True)
        self.assertLess(max_corner_error(proposal.corners, quad), 15)

    def test_a_warm_toned_canvas_is_still_found(self):
        # saturation well above a fixed cut-off, but far below the floor's: the threshold must adapt
        proposal, quad = self.detect(canvas=(178, 150, 118))
        self.assertLess(max_corner_error(proposal.corners, quad), 15)

    def test_a_floor_leak_at_a_corner_doesnt_drag_the_outline(self):
        proposal, quad = self.detect(leak=True)
        self.assertLess(max_corner_error(proposal.corners, quad), 15)

    def test_paper_photos_crop_to_the_painted_area(self):
        path = self.tmp / "paper.jpg"
        painted = synthetic_paper_photo(path)
        proposal = crop.detect(crop.open_photo(path), RECIPE)
        self.assertEqual(proposal.method, "paper")
        self.assertTrue(proposal.check.ok, proposal.check.reasons)
        self.assertLess(max_corner_error(proposal.corners, painted), 15)

    def test_paper_crop_contains_no_paper(self):
        from PIL import Image
        path = self.tmp / "paper.jpg"
        synthetic_paper_photo(path)
        out = Image.open(crop.crop_artwork(path, self.tmp / "out")["output"]).convert("RGB")
        w, h = out.size
        for x, y in ((2, 2), (w - 3, 2), (w - 3, h - 3), (2, h - 3)):
            self.assertLess(min(out.getpixel((x, y))), 200, f"paper at corner pixel {(x, y)}")

    def test_paint_running_off_the_sheet_is_flagged_not_guessed(self):
        path = self.tmp / "runoff.jpg"
        synthetic_paper_photo(path, runoff=True)
        record = crop.crop_artwork(path, self.tmp / "out")
        if record["needs_review"] == "manual_corners_required":
            self.assertIsNone(record["output"])
            self.assertTrue(record["reason"])
            self.assertIs(record["accepted"], False)
        else:
            self.assertFalse(record["proposal"]["check"]["ok"], "must be flagged, not passed as a paper crop")

    def test_canvas_on_a_floor_still_uses_the_canvas_method(self):
        proposal, _ = self.detect()
        self.assertEqual(proposal.method, "canvas")

    def test_follows_exif_rotation(self):
        proposal, quad = self.detect(rotate_exif=True)
        self.assertLess(max_corner_error(proposal.corners, quad), 15)

    def test_crop_writes_new_files_and_marks_them_unaccepted(self):
        path = self.tmp / "photo.jpg"
        synthetic_photo(path)
        before = path.read_bytes()
        record = crop.crop_artwork(path, self.tmp / "out")
        self.assertEqual(path.read_bytes(), before)
        self.assertIs(record["consequential"], True)
        self.assertIs(record["accepted"], False)
        self.assertTrue(Path(record["output"]).exists() and Path(record["review_image"]).exists())

    def test_cropped_image_contains_no_floor(self):
        from PIL import Image
        path = self.tmp / "photo.jpg"
        synthetic_photo(path)
        out = Image.open(crop.crop_artwork(path, self.tmp / "out")["output"]).convert("HSV")
        w, h = out.size
        sat = out.split()[1]
        for x, y in ((3, 3), (w - 4, 3), (w - 4, h - 4), (3, h - 4), (w // 2, 2), (2, h // 2)):
            self.assertLess(sat.getpixel((x, y)), 80, f"floor at edge pixel {(x, y)}")

    def test_manual_corners_override_detection(self):
        path = self.tmp / "photo.jpg"
        quad = synthetic_photo(path)
        record = crop.crop_artwork(path, self.tmp / "out", corners=[list(p) for p in quad])
        self.assertEqual(record["proposal"]["method"], "manual")
        self.assertEqual([tuple(c) for c in record["proposal"]["corners"]], [tuple(map(float, p)) for p in quad])

    def test_centre_off_the_artwork_is_refused(self):
        from PIL import Image
        path = self.tmp / "floor.jpg"
        Image.new("RGB", (800, 1000), (170, 110, 60)).save(path)
        with self.assertRaises(ValueError):
            crop.detect(crop.open_photo(path), RECIPE)


if __name__ == "__main__":
    unittest.main()
