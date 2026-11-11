"""Size and place a piece in its room (B-079): its size by hand for this piece in this room, and where art hangs
for every piece in the room. All data is invented; rendering needs Pillow."""
import json
import unittest

from packages.image_pipeline import rooms
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, tmp
from tests.test_rooms import ROOM, WALL

REAL = (40.64, 50.8)          # 16 x 20 in


def centre(p):
    xs, ys = [c[0] for c in p["corners"]], [c[1] for c in p["corners"]]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


class Placement(unittest.TestCase):
    def test_a_piece_sized_by_hand_keeps_its_shape_and_says_so(self):
        real = rooms.placement(ROOM, (600, 700), (400, 500), REAL)
        big = rooms.placement(ROOM, (600, 700), (400, 500), REAL, 1.5)
        self.assertEqual((real["scale"], big["scale"]), (1.0, 1.5))
        self.assertAlmostEqual(big["frame_cm"][0], real["frame_cm"][0] * 1.5, 0)
        self.assertAlmostEqual(big["frame_cm"][1] / big["frame_cm"][0], real["frame_cm"][1] / real["frame_cm"][0], 2)
        self.assertAlmostEqual(centre(big)[0], centre(real)[0], 0, "resizing keeps it where it was")

    def test_a_hand_size_can_overflow_the_wall(self):
        self.assertTrue(rooms.placement(ROOM, (600, 700), (400, 500), REAL, 4.0)["overflows"])
        self.assertFalse(rooms.placement(ROOM, (600, 700), (400, 500), REAL, 1.2)["overflows"])

    def test_the_rooms_spot_moves_every_piece(self):
        moved = dict(ROOM, hang=[0.25, 0.75])
        for size in (REAL, None):
            x, y = centre(rooms.placement(moved, (600, 700), (400, 500), size))
            self.assertAlmostEqual(x, 100 + 0.25 * 800, 0)            # WALL is 800 x 400 px from (100, 100)
            self.assertAlmostEqual(y, 100 + 0.75 * 400, 0)
        self.assertAlmostEqual(centre(rooms.placement(ROOM, (600, 700), (400, 500), REAL))[0], 500, 0, "centred by default")

    def test_a_point_on_the_view_becomes_a_spot_on_the_wall(self):
        self.assertEqual(rooms.centre_on_wall(ROOM, (0.5, 0.375)), [0.5, 0.5])   # (500, 300) of a 1000 x 800 photo
        self.assertEqual(rooms.centre_on_wall(ROOM, (0.0, 0.0)), [0.0, 0.0], "kept inside the hanging area")
        self.assertEqual(rooms.centre_on_wall(ROOM, (1.0, 1.0)), [1.0, 1.0])


class Stored(unittest.TestCase):
    def test_the_size_is_per_piece_and_per_room(self):
        out = tmp()
        rooms.save_size(out, "fox", "room-a", 1.5)
        self.assertEqual((rooms.size_for(out, "fox", "room-a"), rooms.size_for(out, "fox", "room-b"),
                          rooms.size_for(out, "owl", "room-a")), (1.5, 1.0, 1.0))
        rooms.save_size(out, "fox", "room-a", None)
        self.assertEqual(json.loads(rooms.sizes_path(out).read_text()), {}, "back to real size leaves nothing behind")
        for bad in (0.1, 5, True, "2"):
            with self.assertRaises(ValueError, msg=bad):
                rooms.save_size(out, "fox", "room-a", bad)

    def test_the_spot_is_checked(self):
        self.assertEqual(rooms.update(ROOM, {"hang": [0.2, 0.8]})["hang"], [0.2, 0.8])
        self.assertIsNone(rooms.update(dict(ROOM, hang=[0.2, 0.8]), {"hang": None})["hang"])
        for bad in ([0.5], [1.5, 0.5], "middle", [True, 0.5]):
            with self.assertRaises(ValueError, msg=bad):
                rooms.update(ROOM, {"hang": bad})

    def test_a_view_is_out_of_date_when_its_size_changes(self):
        view = {"room_updated_at": ROOM["updated_at"], "processed_at": None, "dimensions": "16 x 20 in", "scale": 1.5}
        self.assertFalse(rooms.is_stale(view, ROOM, {}, "16 x 20 in", 1.5))
        self.assertTrue(rooms.is_stale(view, ROOM, {}, "16 x 20 in", 1.0))
        self.assertFalse(rooms.is_stale(dict(view, scale=1.0), ROOM, {}, "16 x 20 in"), "older views were real size")


class Api(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.srv = load_server()
        self.out = tmp() / "review"
        self.out.mkdir()
        art = tmp() / "art.png"
        Image.new("RGB", (400, 500), (200, 30, 30)).save(art)
        items = [{"id": i, "source": f"{i}.jpg", "kind": "artwork", "status": "ready", "art_file": str(art),
                  "art_size": [400, 500]} for i in ("fox", "owl")]
        (self.out / "items.json").write_text(json.dumps(items))
        self.root = tmp() / "rooms"
        (self.root / "files").mkdir(parents=True)
        Image.new("RGB", (1000, 800), (210, 200, 190)).save(self.root / "files" / "room-x-abc123.jpg")
        rooms.save({"rooms": [ROOM]}, self.root)
        self.app = self.srv.App(out=self.out, brand_root=self.out / "brand", learning_root=self.out / "learning",
                                config=self.out / "none.json", source=tmp(), rooms_root=self.root)

    def test_resizing_is_for_this_piece_only(self):
        v = self.app.photo_room("fox", {"scale": 1.5})["room"]
        self.assertEqual((v["scale"], v["stale"], v["moved"]), (1.5, False, False))
        self.assertEqual(len(v["corners"]), 4)
        self.assertEqual(self.app.photo("owl")["room"]["scale"], 1.0)
        self.assertEqual(self.app.photo_room("fox", {"scale": None})["room"]["scale"], 1.0)

    def test_moving_is_for_every_piece_in_the_room(self):
        self.app.photo_room("owl", {})
        before = self.app.photo("owl")["room"]
        self.assertFalse(before["stale"])
        v = self.app.photo_room("fox", {"centre": [0.3, 0.5]})["room"]
        self.assertTrue(v["moved"])
        self.assertEqual(rooms.load(self.root)["rooms"][0]["hang"], rooms.centre_on_wall(ROOM, [0.3, 0.5]))
        self.assertAlmostEqual(sum(c[0] for c in v["corners"]) / 4, 0.3, 1)
        owl = self.app.photo("owl")["room"]
        self.assertTrue(owl["moved"] and owl["stale"], "the other piece in the room moves too, once it's hung again")
        self.assertFalse(self.app.photo_room("fox", {"centre": None})["room"]["moved"])

    def test_bad_requests_change_nothing(self):
        for body in ({"scale": 9}, {"centre": [2, 0]}, {"centre": "middle"}, {"room": None, "scale": 2}):
            with self.assertRaises(self.srv.ApiError, msg=body) as e:
                self.app.photo_room("fox", body)
            self.assertEqual(e.exception.code, 400, body)
        self.assertNotIn("hang", rooms.load(self.root)["rooms"][0])
        self.assertEqual(rooms.size_for(self.out, "fox", ROOM["id"]), 1.0)


class Wiring(unittest.TestCase):
    def test_the_photo_page_offers_it(self):
        page = read(REPO / "apps/review-dashboard/src/pages/PhotoDetail.tsx")
        self.assertIn(">Size and place</button>", page)
        self.assertIn("<RoomAdjust ", page)
        self.assertIn("Sized by hand:", page)

    def test_it_works_by_keyboard_and_says_what_moving_does(self):
        src = read(REPO / "apps/review-dashboard/src/components/RoomAdjust.tsx")
        self.assertIn('role="slider" tabIndex={0}', src)
        self.assertIn("onKeyDown={key}", src)
        self.assertIn("where it hangs is for every piece in {room}", src)
        self.assertIn("MIN_SCALE = 0.25, MAX_SCALE = 4", src)
        self.assertIn("MIN_SCALE, MAX_SCALE = 0.25, 4.0", read(REPO / "packages/image_pipeline/rooms.py"))


if __name__ == "__main__":
    unittest.main()
