"""Room views (B-063): the room library and its licence rule, sizes from the listing, hanging a framed piece
on a wall in perspective, and the dashboard's Rooms pages. No network; rendering tests need Pillow."""
import importlib.util
import json
import unittest
from pathlib import Path

from packages.image_pipeline import rooms
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, tmp

HAS_PIL = importlib.util.find_spec("PIL") is not None
WALL = [[100.0, 100.0], [900.0, 100.0], [900.0, 500.0], [100.0, 500.0]]   # 800 x 400 px, square-on
ROOM = {"id": "room-x-abc123", "name": "Test", "file": "files/room-x-abc123.jpg", "size": [1000, 800],
        "licence": "own", "credit": "", "url": "", "note": "", "wall": WALL, "wall_width_cm": 200.0,
        "light": 0.95, "shadow": 0.3, "enabled": True, "updated_at": "2026-10-29T00:00:00Z"}


class Sizes(unittest.TestCase):
    def test_sizes_with_a_unit(self):
        self.assertEqual(rooms.parse_size("16 x 20 in"), (40.64, 50.8))
        self.assertEqual(rooms.parse_size('12" x 16"'), (30.48, 40.64))
        self.assertEqual(rooms.parse_size("40×50 cm"), (40.0, 50.0))
        self.assertEqual(rooms.parse_size("Approx. 30 by 40 inches, unframed"), (76.2, 101.6))
        self.assertEqual(rooms.parse_size("400 x 500 mm"), (40.0, 50.0))

    def test_no_unit_no_size(self):
        for text in ("16x20", "", None, "large", "16 inches"):
            self.assertIsNone(rooms.parse_size(text), text)


class Geometry(unittest.TestCase):
    def test_homography_maps_the_corners(self):
        dst = [[10, 20], [300, 40], [320, 260], [5, 240]]
        h = rooms.homography([[0, 0], [1, 0], [1, 1], [0, 1]], dst)
        for (x, y), (u, v) in zip([[0, 0], [1, 0], [1, 1], [0, 1]], dst):
            got = rooms.apply_h(h, x, y)
            self.assertAlmostEqual(got[0], u, 6); self.assertAlmostEqual(got[1], v, 6)
        with self.assertRaises(ValueError):
            rooms.homography([[0, 0], [1, 1], [2, 2], [3, 3]], dst)

    def test_real_size(self):
        p = rooms.placement(ROOM, (600, 700), (400, 500), (40.64, 50.8))
        self.assertFalse(p["guessed"]); self.assertFalse(p["fitted"])
        self.assertEqual(p["frame_cm"][0], 61.0)                     # 40.64 cm of art in 400 of 600 px
        (x0, y0), (x1, _), _, (_, y3) = p["corners"]
        self.assertAlmostEqual((x1 - x0) / 800, 61.0 / 200, 2, "the frame's share of the wall is its real share")
        self.assertAlmostEqual((x0 + x1) / 2, 500, 0, "centred")
        self.assertAlmostEqual((y0 + y3) / 2, 300, 0)

    def test_size_written_height_first(self):
        a = rooms.placement(ROOM, (600, 700), (400, 500), (40.64, 50.8))
        b = rooms.placement(ROOM, (600, 700), (400, 500), (50.8, 40.64))
        self.assertEqual(a["frame_cm"], b["frame_cm"])

    def test_guessed_and_fitted(self):
        g = rooms.placement(ROOM, (700, 400), (500, 200), None)          # a wide piece: fits the 100 cm height
        self.assertTrue(g["guessed"]); self.assertFalse(g["fitted"])
        self.assertAlmostEqual(g["frame_cm"][0], rooms.GUESS_FILL * 200, 0)
        tall = rooms.placement(ROOM, (600, 700), (400, 500), None)               # guessed: shrunk to fit
        self.assertTrue(tall["fitted"])
        self.assertLessEqual(tall["frame_cm"][1], rooms.MAX_FILL * rooms.wall_height_cm(ROOM) + 0.1)

    def test_a_real_size_is_never_shrunk(self):
        huge = rooms.placement(ROOM, (600, 700), (400, 500), (100.0, 125.0))     # frame 150 x 175 cm
        self.assertFalse(huge["fitted"])
        self.assertTrue(huge["overflows"], "bigger than the marked area, and flagged")
        self.assertEqual(huge["frame_cm"], [150.0, 175.0])
        self.assertFalse(rooms.placement(ROOM, (600, 700), (400, 500), (40.64, 50.8))["overflows"])

    def test_wall_height_follows_the_photo(self):
        self.assertEqual(rooms.wall_height_cm(ROOM), 100.0)


class Library(unittest.TestCase):
    def test_status(self):
        self.assertEqual(rooms.status(ROOM), "ready")
        self.assertEqual(rooms.status(dict(ROOM, licence=None)), "needs-licence")
        self.assertEqual(rooms.status(dict(ROOM, licence="other")), "needs-licence", "'other' says which licence")
        self.assertEqual(rooms.status(dict(ROOM, licence="other", note="CC BY 4.0, credit J. Doe")), "ready")
        self.assertEqual(rooms.status(dict(ROOM, wall=None)), "needs-wall")
        self.assertEqual(rooms.status(dict(ROOM, wall_width_cm=None)), "needs-wall")
        self.assertEqual(rooms.status(dict(ROOM, enabled=False)), "off")
        self.assertEqual(rooms.ready({"rooms": [ROOM, dict(ROOM, id="room-y", licence=None)]}), [ROOM])

    def test_image_url_changes_with_the_file(self):
        import os
        root = tmp() / "rooms"
        self.assertEqual(rooms.image_url(ROOM, root), "rooms/files/room-x-abc123.jpg")
        f = root / ROOM["file"]
        f.parent.mkdir(parents=True)
        f.write_bytes(b"x")
        os.utime(f, (1_700_000_000, 1_700_000_000))
        self.assertEqual(rooms.image_url(ROOM, root), "rooms/files/room-x-abc123.jpg?v=1700000000",
                         "a cleaned or replaced photo gets a new address, so the browser doesn't show the old one")
        self.assertEqual(rooms.public(ROOM, root)["image"], rooms.image_url(ROOM, root))
        self.assertEqual(rooms.options({"rooms": [ROOM]}, root)[0]["image"], rooms.image_url(ROOM, root))

    def test_update(self):
        r = rooms.update(ROOM, {"wall": [[900, 500], [100, 100], [900, 100], [100, 500]], "wall_width_cm": 180})
        self.assertEqual(r["wall"], WALL, "corners are put in order")
        self.assertEqual(r["wall_width_cm"], 180.0)
        self.assertNotEqual(r["updated_at"], ROOM["updated_at"], "a change makes old room views out of date")
        self.assertEqual(ROOM["wall_width_cm"], 200.0, "the room passed in is not changed")
        for bad in ({}, {"price": 1}, {"wall_width_cm": 5}, {"wall_width_cm": True}, {"licence": "found-it"},
                    {"url": "javascript:alert(1)"}, {"name": " "}, {"light": 3}, {"enabled": "yes"},
                    {"wall": [[0, 0], [1, 0], [1, 1]]}):
            with self.assertRaises(ValueError, msg=bad):
                rooms.update(ROOM, bad)

    def test_auto_room_suits_the_piece(self):
        wide = dict(ROOM, id="room-wide")                                    # 200 x 100 cm
        tall = dict(ROOM, id="room-tall", wall=[[100.0, 100.0], [500.0, 100.0], [500.0, 700.0], [100.0, 700.0]],
                    wall_width_cm=100.0)                                     # 100 x 150 cm
        both = [wide, tall]
        self.assertEqual(rooms.auto_room({"id": "a", "art_size": [800, 1000]}, both, None)["id"], "room-tall")
        self.assertEqual(rooms.auto_room({"id": "a", "art_size": [1200, 600]}, both, None)["id"], "room-wide")
        small = dict(tall, id="room-small", wall_width_cm=40.0)              # 40 x 60 cm
        self.assertEqual(rooms.auto_room({"id": "a", "art_size": [800, 1000]}, [small, wide], "16 x 20 in")["id"],
                         "room-wide", "a room it fits at its real size comes first")
        self.assertIsNone(rooms.auto_room({"id": "a"}, [], None))
        picks = {rooms.auto_room({"id": f"p{i}", "art_size": [1000, 1000]}, [wide, dict(wide, id="room-wide2")], None)["id"]
                 for i in range(20)}
        self.assertEqual(len(picks), 2, "rooms that suit a piece equally are shared out")

    def test_choice_and_fallback(self):
        out = tmp()
        a, b = dict(ROOM, id="room-a", name="A"), dict(ROOM, id="room-b", name="B")
        lib = {"rooms": [a, b]}
        item = {"id": "p", "art_size": [1000, 500]}
        room, auto, lost = rooms.chosen(item, lib, out, None)
        self.assertTrue(auto); self.assertIsNone(lost)
        other = "room-b" if room["id"] == "room-a" else "room-a"
        rooms.save_choice(out, "p", other)
        self.assertEqual(rooms.chosen(item, lib, out, None)[:2], (rooms.get(lib, other), False))
        lib = {"rooms": [dict(r, licence=None) if r["id"] == other else r for r in lib["rooms"]]}
        room, auto, lost = rooms.chosen(item, lib, out, None)
        self.assertNotEqual(room["id"], other, "a chosen room that stopped being ready is never used")
        self.assertTrue(auto); self.assertEqual(lost, rooms.get(lib, other)["name"])
        rooms.save_choice(out, "p", None)
        self.assertEqual(rooms.load_choices(out), {})

    def test_stale(self):
        v = {"room_updated_at": ROOM["updated_at"], "processed_at": "p1", "dimensions": "16 x 20 in"}
        item = {"processed_at": "p1"}
        self.assertFalse(rooms.is_stale(v, ROOM, item, "16 x 20 in"))
        self.assertTrue(rooms.is_stale(v, dict(ROOM, updated_at="later"), item, "16 x 20 in"))
        self.assertTrue(rooms.is_stale(v, ROOM, {"processed_at": "p2"}, "16 x 20 in"), "re-cropped")
        self.assertTrue(rooms.is_stale(v, ROOM, item, "12 x 16 in"), "the size changed")


@unittest.skipUnless(HAS_PIL, "Pillow not installed (use the project .venv)")
class Rendering(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.root = tmp() / "rooms"
        (self.root / "inbox").mkdir(parents=True)
        Image.new("RGB", (1000, 800), (210, 200, 190)).save(self.root / "inbox" / "Living room.jpg")
        self.art = tmp() / "art.png"
        Image.new("RGB", (400, 500), (200, 30, 30)).save(self.art)

    def test_inbox_import_and_no_duplicates(self):
        added = rooms.scan_inbox(self.root)
        self.assertEqual(len(added), 1)
        r = added[0]
        self.assertEqual((r["name"], r["licence"], r["wall"]), ("Living room", None, None))
        self.assertEqual(rooms.status(r), "needs-licence", "an imported room is never used until its licence is set")
        self.assertTrue((self.root / r["file"]).exists())
        self.assertTrue((self.root / "inbox" / "imported" / "Living room.jpg").exists())
        again, new = rooms.import_file(self.root / "inbox" / "imported" / "Living room.jpg", self.root)
        self.assertFalse(new); self.assertEqual(again["id"], r["id"])

    def test_upload(self):
        data = (self.root / "inbox" / "Living room.jpg").read_bytes()
        r, new = rooms.import_upload(data, "../../Living room.jpg", self.root, licence="own", credit="Me")
        self.assertTrue(new)
        self.assertEqual((r["name"], r["licence"], r["credit"]), ("Living room", "own", "Me"))
        kept = self.root / "inbox" / "imported" / "Living-room.jpg"
        self.assertTrue(kept.exists(), "the original is kept, inside the library, whatever path it was sent with")
        again, new = rooms.import_upload(data, "copy.jpg", self.root)
        self.assertFalse(new); self.assertEqual(again["id"], r["id"])
        for bad, name in ((b"not a photo", "x.jpg"), (data, "x.exe"), (b"", "x.jpg")):
            with self.assertRaises(ValueError, msg=name):
                rooms.import_upload(bad, name, self.root)
        self.assertFalse((self.root / "inbox" / "imported" / "x.jpg").exists(), "a refused file isn't left behind")
        self.assertEqual(len(rooms.load(self.root)["rooms"]), 1)

    def test_render_a_view(self):
        from PIL import Image
        r, _ = rooms.import_file(self.root / "inbox" / "Living room.jpg", self.root, licence="own")
        r = rooms.update(r, {"wall": WALL, "wall_width_cm": 200})
        out = tmp() / "view.jpg"
        before = self.art.read_bytes()
        rec = rooms.render_view(r, self.root, self.art, "16 x 20 in", out)
        self.assertEqual(self.art.read_bytes(), before, "the artwork is never changed")
        self.assertFalse(rec["guessed"])
        im = Image.open(out)
        self.assertEqual(im.size, (1000, 800))
        red = im.getpixel((500, 300))
        self.assertGreater(red[0], 120); self.assertLess(red[1], 90, "the piece is on the wall's centre")
        self.assertEqual(im.getpixel((20, 20))[:2], (210, 200), "the room around it is unchanged")

    def test_listing_views_need_a_ready_room(self):
        lib = {"rooms": []}
        r, _ = rooms.import_file(self.root / "inbox" / "Living room.jpg", self.root)
        r = rooms.update(r, {"wall": WALL, "wall_width_cm": 200})
        out = tmp()
        item = {"id": "a", "art_file": str(self.art), "processed_at": "p"}
        with self.assertRaises(ValueError):
            rooms.render_item(item, lib, self.root, out, None, [r])          # no licence
        recs = rooms.render_item(item, lib, self.root, out, None, [dict(r, licence="pexels")])
        self.assertTrue(recs[0]["guessed"])
        self.assertIn("a", rooms.load_views(out))


class Api(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        self.out = tmp() / "review"
        self.out.mkdir()
        (self.out / "items.json").write_text(json.dumps([{"id": "art-1", "source": "Fox.jpg", "kind": "artwork",
                                                           "status": "ready", "art_file": "x.png"}]))
        self.root = tmp() / "rooms"
        rooms.save({"rooms": [dict(ROOM, licence=None, wall=None)]}, self.root)
        self.app = self.srv.App(out=self.out, brand_root=self.out / "brand", learning_root=self.out / "learning",
                                config=self.out / "none.json", source=tmp(), rooms_root=self.root)

    def test_rooms_doc(self):
        d = self.app.rooms_doc()
        self.assertEqual(d["rooms"][0]["status"], "needs-licence")
        self.assertEqual(d["rooms"][0]["image"], "rooms/files/room-x-abc123.jpg")
        self.assertIn("pexels", [l["id"] for l in d["licences"]])
        self.assertEqual(d["pieces"], [{"id": "art-1", "source": "Fox.jpg"}])

    def test_edit_room(self):
        r = self.app.edit_room("room-x-abc123", {"licence": "pexels", "credit": "A. Photographer", "wall": WALL,
                                                 "wall_width_cm": 210})
        self.assertEqual(r["status"], "ready")
        self.assertEqual(rooms.load(self.root)["rooms"][0]["credit"], "A. Photographer")
        for bad in ({"wall_width_cm": 1}, {"file": "../../x"}, {"size": [1, 1]}):
            with self.assertRaises(self.srv.ApiError, msg=bad) as e:
                self.app.edit_room("room-x-abc123", bad)
            self.assertEqual(e.exception.code, 400)
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.edit_room("room-nope", {"name": "x"})
        self.assertEqual(e.exception.code, 404)

    def test_nothing_ready(self):
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.preview_room("room-x-abc123", {})
        self.assertEqual(e.exception.code, 400, "no wall yet")
        for fn in (lambda: self.app.photo_room("art-1", {}), self.app.render_all_rooms):
            with self.assertRaises(self.srv.ApiError) as e:
                fn()
            self.assertEqual(e.exception.code, 400)

    def test_photo_room(self):
        from PIL import Image
        d = self.app.photo("art-1")
        self.assertIsNone(d["room"]); self.assertEqual([o["status"] for o in d["room_options"]], ["needs-licence"])
        self.app.edit_room("room-x-abc123", {"licence": "own", "wall": WALL, "wall_width_cm": 200})
        rooms.save({"rooms": rooms.load(self.root)["rooms"] + [dict(ROOM, id="room-y-def456", name="Unready", licence=None)]},
                   self.root)
        v = self.app.photo("art-1")["room"]
        self.assertEqual((v["room"], v["auto"], v["image"], v["stale"]), ("room-x-abc123", True, None, True))
        self.assertEqual([o["id"] for o in self.app.photo("art-1")["room_options"]], ["room-x-abc123", "room-y-def456"],
                         "ready rooms first")
        rooms.save({"rooms": rooms.load(self.root)["rooms"] + [dict(ROOM, id="room-z-0", wall=None, enabled=False)]}, self.root)
        self.assertEqual([o["status"] for o in self.app.photo("art-1")["room_options"]], ["ready", "needs-licence", "off"],
                         "a room that's switched off says so, and comes last")
        rooms.save({"rooms": [r for r in rooms.load(self.root)["rooms"] if r["id"] != "room-z-0"]}, self.root)
        for body, code in (({"room": "room-y-def456"}, 400), ({"room": "room-nope"}, 404), ({"room": 3}, 404),
                           ({"x": 1}, 400)):
            with self.assertRaises(self.srv.ApiError, msg=body) as e:
                self.app.photo_room("art-1", body)
            self.assertEqual(e.exception.code, code, body)
        self.assertEqual(rooms.load_choices(self.out), {}, "a refused choice isn't saved")
        art = tmp() / "art.png"
        Image.new("RGB", (400, 500), (200, 30, 30)).save(art)
        (self.root / "files").mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1000, 800), (210, 200, 190)).save(self.root / "files" / "room-x-abc123.jpg")
        (self.out / "items.json").write_text(json.dumps([{"id": "art-1", "source": "Fox.jpg", "kind": "artwork",
                                                           "status": "ready", "art_file": str(art), "art_size": [400, 500]}]))
        v = self.app.photo_room("art-1", {"room": "room-x-abc123"})["room"]
        self.assertEqual((v["room"], v["auto"], v["stale"]), ("room-x-abc123", False, False))
        self.assertTrue(v["image"].startswith("img/art-1.room-room-x-abc123.jpg"))
        self.assertTrue(self.app.photo_room("art-1", {"room": None})["room"]["auto"], "null goes back to the automatic pick")

    def test_photo_page_carries_about_this_piece(self):
        self.app.edit_room("room-x-abc123", {"licence": "own", "wall": WALL, "wall_width_cm": 200})
        d = self.app.photo("art-1")
        self.assertEqual((d["facts"], d["series"], d["dimensions"]), ({}, "", None))
        self.assertTrue(d["room"]["guessed"])
        self.app.update_listing("art-1", {"facts": {"dimensions": "16 x 20 in", "medium": "ink"}, "series": "Wild"})
        d = self.app.photo("art-1")
        self.assertEqual((d["facts"]["dimensions"], d["series"], d["dimensions"]), ("16 x 20 in", "Wild", "16 x 20 in"),
                         "one source: the listing's facts are what the photo page shows and the room view uses")
        self.assertFalse(d["room"]["guessed"])
        self.assertEqual(d["room"]["fits_elsewhere"], [], "there's no other room")
        self.assertTrue(rooms.too_big(ROOM, (200.0, 50.0)))                    # framed 260 cm on a 200 cm wall
        self.assertFalse(rooms.too_big(ROOM, (40.64, 50.8)))
        self.assertFalse(rooms.too_big(ROOM, None), "an unknown size is never too big")

    def test_upload_room(self):
        from PIL import Image
        import io
        buf = io.BytesIO(); Image.new("RGB", (900, 600), (200, 200, 200)).save(buf, "PNG")
        r = self.app.upload_room(buf.getvalue(), {"filename": ["Hall.png"], "licence": ["pexels"], "credit": ["Someone"]})
        self.assertTrue(r["added"]); self.assertEqual((r["name"], r["status"]), ("Hall", "needs-wall"))
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.upload_room(buf.getvalue(), {"filename": ["Hall2.png"], "licence": ["made-up"]})
        self.assertEqual(e.exception.code, 400, "an unknown licence is refused")
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.upload_room(b"<html>", {"filename": ["a.png"]})
        self.assertEqual(e.exception.code, 400)

    def test_routes(self):
        routes = [(m, p.pattern) for m, p, _ in self.srv.ROUTES]
        for r in [("GET", "^/api/rooms$"), ("POST", "^/api/rooms/scan$"), ("POST", "^/api/rooms/render$"),
                  ("GET", r"^/api/rooms/(room-[\w.-]+)$"), ("PUT", r"^/api/rooms/(room-[\w.-]+)$"),
                  ("POST", r"^/api/rooms/(room-[\w.-]+)/preview$"),
                  ("POST", "^/api/rooms/suggest$"), ("POST", r"^/api/rooms/(room-[\w.-]+)/suggest$"), ("POST", r"^/api/photos/([\w.-]+)/room$")]:
            self.assertIn(r, routes)
        server = read(REPO / "services/local_api/server.py")
        self.assertIn('if method == "POST" and path == "/api/rooms/upload":', server)
        self.assertIn("if length > rooms.MAX_UPLOAD:", server)
        self.assertIn('if path.startswith("/rooms/files/") or path.startswith("/rooms/previews/"):', server,
                      "only room photos and previews are served, never rooms.json or the inbox")


class Suggestions(unittest.TestCase):
    """A new room's suggested name, hanging area and width (room_suggest.py)."""
    OUT = {"name": "Tan sofa and bookshelf", "area": {"left": 0.25, "top": 0.1, "right": 0.75, "bottom": 0.4},
           "width_cm": 150, "reference": "the sofa", "confidence": "medium"}

    def setUp(self):
        from packages.image_pipeline import room_suggest
        self.rs = room_suggest
        self.room = dict(ROOM, name="Screenshot 2026 10 30 at 3.37.26 pm", source_file="Screenshot 2026-10-30 at 3.37.26 pm.png",
                         wall=None, wall_width_cm=None)

    def test_name_applied_wall_only_suggested(self):
        r = self.rs.apply(self.room, self.OUT, "m", 0.01)
        self.assertEqual((r["name"], r["named_by"]), ("Tan sofa and bookshelf", "suggestion"))
        self.assertEqual(r["suggested"]["wall"], [[250.0, 80.0], [750.0, 80.0], [750.0, 320.0], [250.0, 320.0]])
        self.assertEqual(r["suggested"]["wall_width_cm"], 150.0)
        self.assertIsNone(r["wall"]); self.assertIsNone(r["wall_width_cm"])
        self.assertEqual(rooms.status(r), "needs-wall", "a suggested wall is never used until the owner saves it")

    def test_owner_name_kept(self):
        typed = rooms.update(self.room, {"name": "Our reading corner"})
        self.assertEqual(self.rs.apply(typed, self.OUT, "m", 0)["name"], "Our reading corner")
        self.assertTrue(self.rs.named_from_file(self.room), "an older room named from its file still counts")

    def test_checks(self):
        for bad in ({"left": 0.5, "top": 0.1, "right": 0.52, "bottom": 0.4}, {"left": "x"}, {}):
            self.assertIsNone(self.rs.clean_area(bad, (1000, 800)), bad)
        self.assertEqual(self.rs.clean_area({"left": -1, "top": 0, "right": 2, "bottom": 0.5}, (100, 100))[2], [100.0, 50.0])
        r = self.rs.apply(self.room, dict(self.OUT, width_cm=5000), "m", 0)
        self.assertIsNone(r["suggested"]["wall_width_cm"], "a width outside 20-2000 cm isn't kept")
        r = self.rs.apply(self.room, dict(self.OUT, name="Screenshot 2026 photo"), "m", 0)
        self.assertEqual(r["name"], self.room["name"], "a name that looks like a file name isn't used")

    def test_api(self):
        from PIL import Image
        srv = load_server()
        out, root = tmp() / "review", tmp() / "rooms"
        out.mkdir()
        (root / "files").mkdir(parents=True)
        Image.new("RGB", (1000, 800), (210, 200, 190)).save(root / "files" / "room-x-abc123.jpg")
        rooms.save({"rooms": [self.room]}, root)
        seen = []

        def call(client, req):
            seen.append(req)
            if len(seen) == 2:                         # the owner renames the room while the model is looking
                lib = rooms.load(root)
                lib["rooms"] = [rooms.update(lib["rooms"][0], {"name": "Typed meanwhile"})]
                rooms.save(lib, root)
            return {"output": self.OUT, "model": "m", "usage": {"input_tokens": 1000, "output_tokens": 100}}
        app = srv.App(out=out, brand_root=out / "brand", learning_root=out / "learning", config=out / "none.json",
                      source=tmp(), rooms_root=root, client_factory=lambda: object(), call=call)
        r = app.suggest_room("room-x-abc123")
        self.assertEqual((r["name"], r["status"]), ("Tan sofa and bookshelf", "needs-wall"))
        self.assertEqual(seen[0]["messages"][0]["content"][0]["type"], "image")
        self.assertEqual(seen[0]["output_config"]["format"]["schema"], self.rs.SCHEMA)
        rooms.save({"rooms": [dict(self.room, named_by="file")]}, root)
        self.assertEqual(app.suggest_room("room-x-abc123")["name"], "Typed meanwhile",
                         "a name typed while the suggestion was running is kept")
        with self.assertRaises(srv.ApiError) as e:
            app.suggest_rooms({"rooms": ["room-nope"]})
        self.assertEqual(e.exception.code, 404)


class Wiring(unittest.TestCase):
    def test_pages(self):
        main = read(REPO / "apps/review-dashboard/src/main.tsx")
        self.assertIn('["rooms", "Rooms"]', main)
        self.assertIn('section === "rooms" && id', main)
        editor = read(REPO / "apps/review-dashboard/src/components/CornerEditor.tsx")
        for s in ('role="slider"', "onKeyDown", "setPointerCapture"):
            self.assertIn(s, editor)
        for page in ("PhotoDetail.tsx", "RoomDetail.tsx"):
            self.assertIn("<CornerEditor", read(REPO / "apps/review-dashboard/src/pages" / page), page)
        room = read(REPO / "apps/review-dashboard/src/pages/RoomDetail.tsx")
        for s in ("Not recorded: this room won't be used", "beforeunload", "api.previewRoom", "api.suggestRoom",
                  "Set up this room", "Suggested from the photo", "Save and use this room", "Still to do:"):
            self.assertIn(s, room)
        self.assertIn("<li className={pts && !isStarter ?", room, "the untouched starting box never shows as a done step")
        self.assertIn("if (now && now !== mine) location.reload();", read(REPO / "apps/review-dashboard/src/main.tsx"),
                      "a tab left open across a rebuild picks up the new page on the next move")
        rooms_page = read(REPO / "apps/review-dashboard/src/pages/Rooms.tsx")
        self.assertIn('r.wall && !r.wall_width_cm ? "Needs its width"', read(REPO / "apps/review-dashboard/src/api.ts"),
                      "a room with its wall but no width says what it's missing")
        for s in ("api.uploadRoom", "<Drawer", "api.suggestRooms", "b.added_at.localeCompare(a.added_at)", "roomLabel(r"):
            self.assertIn(s, rooms_page)
        self.assertIn('"X-Commerce-OS": "1" }, body: file', read(REPO / "apps/review-dashboard/src/api.ts"))
        photo = read(REPO / "apps/review-dashboard/src/pages/PhotoDetail.tsx")
        for s in ("api.photoRoom", "Size guessed", "Change room", "<Drawer", "Pick for me", "disabled={!ok}"):
            self.assertIn(s, photo)
        self.assertIn("<AboutPiece", photo)
        self.assertIn("${v.room}:${p.dimensions", photo, "the piece is hung again when its size changes")
        about = read(REPO / "apps/review-dashboard/src/components/AboutPiece.tsx")
        self.assertIn("api.saveListing(itemId", about, "both pages save to the same listing record")
        self.assertIn('return w.trim() && h.trim() && unit ? `${+w} x ${+h} ${unit}` : "";', about,
                      "a size is only written with its unit")
        self.assertIn("<AboutPiece", read(REPO / "apps/review-dashboard/src/pages/ListingDetail.tsx"))
        drawer = read(REPO / "apps/review-dashboard/src/components/Drawer.tsx")
        for s in ('role="dialog" aria-modal="true"', 'e.key === "Escape"', "opener?.focus()"):
            self.assertIn(s, drawer, "a drawer you can close and leave with the keyboard")

    def test_room_photos_are_never_committed(self):
        self.assertIn(".commerce-os/", read(REPO / ".gitignore"))
        self.assertEqual(rooms.ROOMS, REPO / ".commerce-os" / "rooms")


if __name__ == "__main__":
    unittest.main()
