"""scripts/review_images.py: the local review page for image conversions.

Pure helpers are stdlib-only. The build and server tests need Pillow (the project .venv) and are
skipped without it.
"""
import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from tests._helpers import REPO

spec = importlib.util.spec_from_file_location("review_images", REPO / "scripts" / "review_images.py")
ri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ri)
HAS_PIL = importlib.util.find_spec("PIL") is not None
GOOD = {"img-1-abc123": {"decision": "fix", "corners": [[0, 0], [10, 0], [10, 10], [0, 10]], "note": "tighter"}}


class Helpers(unittest.TestCase):
    def test_slug_is_stable_url_safe_and_unique(self):
        a, b = ri.slug("Animal Art 16x20_0000_Wolf.jpg"), ri.slug("Animal Art 16x20_0000_Wolf.png")
        self.assertEqual(a, ri.slug("Animal Art 16x20_0000_Wolf.jpg"))
        self.assertRegex(a, r"^[a-z0-9-]+$")
        self.assertNotEqual(a, b)

    def test_phone_photos_are_cropped_first(self):
        self.assertTrue(ri.is_photo("IMG_5411.JPG"))
        self.assertFalse(ri.is_photo("Animal Art 16x20_0000_Wolf.jpg"))

    def test_decisions_are_validated(self):
        self.assertEqual(ri.validate_decisions(GOOD)["img-1-abc123"]["decision"], "fix")
        for bad in ([], {"../x": {"decision": "accept"}}, {"a": {"decision": "publish"}},
                    {"a": {"decision": "fix", "corners": [[0, 0]]}}, {"a": {"decision": "fix", "corners": "x"}}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ri.validate_decisions(bad)

    def test_rotation_is_validated(self):
        self.assertEqual(ri.validate_decisions({"a": {"decision": None, "rotate": 270}})["a"]["rotate"], 270)
        with self.assertRaises(ValueError):
            ri.validate_decisions({"a": {"decision": None, "rotate": 45}})

    def test_pending_tracks_unapplied_corners_and_rotation(self):
        corners = [[0, 0], [1, 0], [1, 1], [0, 1]]
        items = [{"id": "a", "applied": {"corners": None, "rotate": 0}},
                 {"id": "b", "applied": {"corners": corners, "rotate": 90}},
                 {"id": "c"}, {"id": "d", "applied": {"corners": None, "rotate": 0}}]
        decisions = {"a": {"decision": "accept", "corners": corners},       # accept keeps corners: still pending
                     "b": {"decision": "fix", "corners": corners, "rotate": 90},  # already applied
                     "c": {"decision": None, "rotate": 180},
                     "d": {"decision": "accept"}}
        self.assertEqual(ri.pending(decisions, items), {"a", "c"})

    def test_listing_copy_is_not_edited_here(self):
        with self.assertRaises(ValueError):
            ri.validate_decisions({"a": {"decision": None, "listing": {"title": "New title"}}})

    def test_drafts_appear_on_their_card_with_a_dashboard_link(self):
        import tempfile
        from tests.test_drafting import draft, CLEAN
        out = Path(tempfile.mkdtemp(prefix="cos-drafts-"))
        (out / "drafts").mkdir()
        (out / "items.json").write_text(json.dumps([{"id": "img-1-abc", "source": "IMG_1.JPG", "kind": "photo",
                                                     "status": "auto"}]))
        evil = dict(CLEAN, recommended_title="</script><b>x</b>")
        (out / "drafts" / "img-1-abc.json").write_text(json.dumps(
            {"item": "img-1-abc", "draft": draft(evil), "model_output": evil, "model": "claude-opus-5-5",
             "policy_violations": []}))
        items = ri.render(out)
        self.assertEqual(items[0]["draft"]["title"], "</script><b>x</b>")
        self.assertEqual(items[0]["draft"]["link"], "http://127.0.0.1:8770/#/listings/img-1-abc")
        page = (out / "index.html").read_text()
        self.assertEqual(page.count("</script>"), 1, "draft text can't break out of the page's script")
        self.assertNotIn("draft", json.loads((out / "items.json").read_text())[0], "drafts aren't baked into items.json")

    def test_page_escapes_its_data(self):
        page = ri.render_page([{"id": "x", "source": "</script><script>alert(1)</script>", "kind": "artwork",
                                "status": "ready"}])
        self.assertNotIn("</script><script>alert(1)", page)
        self.assertEqual(page.count("</script>"), 1)

    def test_page_is_self_contained(self):
        page = ri.render_page([])
        self.assertNotRegex(page, r"(src|href)=\"https?://", "no external resources: the page stays local")
        self.assertIn("prefers-color-scheme: dark", page)

    def test_server_binds_to_this_computer_only(self):
        self.assertEqual(ri.HOST, "127.0.0.1")

    def test_accepting_here_is_not_an_approval(self):
        self.assertIn("isn't\nan approval", ri.__doc__)


@unittest.skipUnless(HAS_PIL, "Pillow not installed (use the project .venv)")
class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image
        from tests.test_image_crop import synthetic_paper_photo
        cls.tmp = Path(tempfile.mkdtemp(prefix="cos-review-"))
        cls.src, cls.out = cls.tmp / "src", cls.tmp / "out"
        cls.src.mkdir()
        synthetic_paper_photo(cls.src / "IMG_0001.JPG")
        Image.new("RGB", (400, 500), (30, 60, 160)).save(cls.src / "artwork.png")
        (cls.src / "notes.txt").write_text("not an image")
        cls.items = ri.build(cls.src, cls.out, log=lambda *a: None)

    def test_every_image_gets_a_card(self):
        self.assertEqual(sorted(i["source"] for i in self.items), ["IMG_0001.JPG", "artwork.png"])
        self.assertTrue((self.out / "index.html").exists())

    def test_photo_is_cropped_and_framed(self):
        photo = next(i for i in self.items if i["kind"] == "photo")
        self.assertEqual(photo["status"], "auto")
        for key in ("photo", "cropped", "framed"):
            self.assertTrue((self.out / photo[key]).exists(), key)

    def test_ready_cut_file_is_framed_directly(self):
        art = next(i for i in self.items if i["kind"] == "artwork")
        self.assertEqual(art["status"], "ready")
        self.assertNotIn("crop", art)
        self.assertEqual(art["frame"]["orientation"], "portrait")

    def test_originals_are_untouched(self):
        self.assertEqual(sorted(p.name for p in self.src.iterdir()), ["IMG_0001.JPG", "artwork.png", "notes.txt"])

    def test_rotation_turns_the_framed_image(self):
        art = next(i for i in self.items if i["kind"] == "artwork")
        (self.out / ri.DECISIONS).write_text(json.dumps({art["id"]: {"decision": "accept", "rotate": 90}}))
        try:
            items = ri.build(self.src, self.out, only={art["id"]}, log=lambda *a: None)
            turned = next(i for i in items if i["id"] == art["id"])
            self.assertEqual(turned["frame"]["orientation"], "landscape")   # 400 x 500 turned on its side
            self.assertEqual(turned["applied"]["rotate"], 90)
            self.assertEqual(ri.pending(ri.load_decisions(self.out), items), set())
        finally:
            (self.out / ri.DECISIONS).unlink()
            ri.build(self.src, self.out, only={art["id"]}, log=lambda *a: None)

    def test_fixed_corners_are_applied_on_rebuild(self):
        photo = next(i for i in self.items if i["kind"] == "photo")
        W, H = photo["photo_size"]
        (self.out / ri.DECISIONS).write_text(json.dumps(
            {photo["id"]: {"decision": "fix", "corners": [[0, 0], [W, 0], [W, H], [0, H]]}}))
        try:
            items = ri.build(self.src, self.out, only={photo["id"]}, log=lambda *a: None)
            fixed = next(i for i in items if i["id"] == photo["id"])
            self.assertEqual((fixed["status"], fixed["crop"]["method"]), ("fixed", "manual"))
        finally:
            (self.out / ri.DECISIONS).unlink()
            ri.build(self.src, self.out, only={photo["id"]}, log=lambda *a: None)


@unittest.skipUnless(HAS_PIL, "Pillow not installed (use the project .venv)")
class Server(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cos-serve-"))
        (self.tmp / "index.html").write_text("<p>ok</p>")
        self.old_out, ri.OUT = ri.OUT, self.tmp
        self.httpd = ri.make_server(0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        ri.OUT = self.old_out

    def post(self, body: bytes):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/decisions", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=5)

    def test_listens_on_localhost(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_serves_the_page(self):
        self.assertEqual(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5).read(), b"<p>ok</p>")

    def test_saves_valid_decisions(self):
        self.assertEqual(self.post(json.dumps(GOOD).encode()).status, 204)
        saved = json.loads((self.tmp / ri.DECISIONS).read_text())
        stamps = {k: saved[k].pop("decided_at") for k in saved}
        self.assertEqual(saved, ri.validate_decisions(GOOD))
        self.assertTrue(all(ri.STAMP.fullmatch(s) for s in stamps.values()), "each new decision is timestamped")

    def test_rejects_invalid_decisions_and_writes_nothing(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post(json.dumps({"a": {"decision": "publish"}}).encode())
        self.assertEqual(e.exception.code, 400)
        self.assertFalse((self.tmp / ri.DECISIONS).exists())

    def test_apply_with_nothing_pending(self):
        (self.tmp / "items.json").write_text("[]")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/apply", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual((r.status, json.loads(r.read())), (202, {"count": 0}))
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/apply-status", timeout=5) as r:
            status = json.loads(r.read())
        self.assertEqual((status["running"], status["finished"], status["total"]), (False, True, 0))

    def test_only_the_decisions_endpoint_accepts_posts(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/index.html", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 404)
        self.assertEqual((self.tmp / "index.html").read_text(), "<p>ok</p>")


if __name__ == "__main__":
    unittest.main()
