"""The dashboard's Photos page (B-062): each photo's stage and dated history, and accepting, rejecting
or rotating it through the same decisions file and rules as the image review page. No network, no images."""
import json
import unittest

from packages.image_pipeline import stages
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, record_for, tmp

PHOTO = {"id": "img-1-abc", "source": "IMG_0001.JPG", "kind": "photo", "status": "flagged", "art_file": "x.png",
         "photo": "img/img-1-abc.photo.jpg", "photo_size": [1000, 1200], "framed": "img/img-1-abc.framed.jpg",
         "cropped": "img/img-1-abc.crop.jpg", "crop": {"ok": False, "method": "auto", "reasons": ["edges unclear"]},
         "processed_at": "2026-10-27T10:00:00Z", "applied": {"corners": None, "rotate": 0}}
ART = {"id": "art-1-def", "source": "Fox.jpg", "kind": "artwork", "status": "ready", "art_file": "Fox.jpg",
       "original": "img/art-1-def.source.jpg", "processed_at": "2026-10-27T11:00:00Z",
       "applied": {"corners": None, "rotate": 0}}


class Stages(unittest.TestCase):
    def st(self, item, decision=None, pending=False, drafted=False, approved=False):
        return stages.stage(item, decision or {}, pending, drafted, approved)

    def test_a_phone_photo_waits_for_review_and_a_ready_cut_file_does_not(self):
        self.assertEqual(self.st(PHOTO), "to-review")
        self.assertEqual(self.st(PHOTO, {"decision": "accept"}), "ready")
        self.assertEqual(self.st(PHOTO, {"decision": "fix"}), "ready")
        self.assertEqual(self.st(ART), "ready")
        self.assertEqual(self.st(dict(ART, status="error", art_file=None)), "to-review")

    def test_the_most_urgent_stage_wins(self):
        self.assertEqual(self.st(ART, {"decision": "reject"}, pending=True, drafted=True), "rejected")
        self.assertEqual(self.st(ART, {"decision": "accept"}, pending=True, drafted=True), "not-applied")
        self.assertEqual(self.st(ART, drafted=True), "drafted")
        self.assertEqual(self.st(ART, drafted=True, approved=True), "approved")
        self.assertEqual(self.st(PHOTO, drafted=True), "to-review", "a drafted photo nobody reviewed still needs review")

    def test_timeline_is_dated_and_in_order(self):
        src = tmp()
        (src / "Fox.jpg").write_bytes(b"x")
        rec = record_for("art-1-def")
        rec["drafted_at"] = "2026-10-28T09:00:00Z"
        ev = stages.timeline(ART, {"decision": "accept", "decided_at": "2026-10-27T12:00:00Z"}, rec,
                             {"approved": {"at": "2026-10-29T08:00:00Z"}}, src, src)
        self.assertEqual([e["event"] for e in ev], ["added", "processed", "accept", "drafted", "approved"])
        self.assertTrue(ev[0]["at"])
        self.assertEqual(ev[1]["label"], "Framed")
        self.assertTrue(ev[3]["label"].startswith("Drafted (r"))
        old = stages.timeline(ART, {"decision": "accept"}, None, {}, tmp(), tmp())
        self.assertIsNone(old[2]["at"], "a decision made before times were recorded has no time, not a made-up one")

    def test_rows(self):
        rows = stages.photo_rows([PHOTO, ART], {"art-1-def": {"decision": "reject", "decided_at": "2026-10-28T00:00:00Z"}},
                                 {}, {}, set(), tmp(), tmp())
        self.assertEqual([r["stage"] for r in rows], ["to-review", "rejected"])
        self.assertTrue(rows[0]["crop_flagged"])
        self.assertEqual(rows[1]["updated_at"], "2026-10-28T00:00:00Z")


class Stamps(unittest.TestCase):
    def setUp(self):
        self.ri = load_server().ri

    def test_only_a_changed_decision_gets_a_new_time(self):
        old = {"a": {"decision": "accept", "decided_at": "2026-10-01T00:00:00Z"}, "b": {"decision": None}}
        new = {"a": {"decision": "accept", "note": "fine"}, "b": {"decision": None, "rotate": 90}, "c": {"decision": "reject"}}
        out = self.ri.stamp_changes(old, new, "2026-10-29T00:00:00Z")
        self.assertEqual(out["a"]["decided_at"], "2026-10-01T00:00:00Z", "a note alone doesn't move the time")
        self.assertEqual(out["b"]["decided_at"], "2026-10-29T00:00:00Z")
        self.assertEqual(out["c"]["decided_at"], "2026-10-29T00:00:00Z")

    def test_times_are_validated(self):
        self.assertEqual(self.ri.validate_decisions({"a": {"decision": None, "decided_at": "2026-10-29T00:00:00Z"}})
                         ["a"]["decided_at"], "2026-10-29T00:00:00Z")
        with self.assertRaises(ValueError):
            self.ri.validate_decisions({"a": {"decision": None, "decided_at": "yesterday"}})


class Api(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        self.out = tmp() / "review"
        self.out.mkdir()
        (self.out / "items.json").write_text(json.dumps([PHOTO, ART]))
        self.app = self.srv.App(out=self.out, brand_root=self.out / "brand", learning_root=self.out / "learning",
                                config=self.out / "none.json", source=tmp())

    def saved(self):
        return json.loads((self.out / "decisions.json").read_text())

    def test_accept_reject_rotate_and_note(self):
        row = self.app.decide_photo("img-1-abc", {"decision": "accept"})
        self.assertEqual(row["stage"], "ready")
        self.assertTrue(self.saved()["img-1-abc"]["decided_at"])
        row = self.app.decide_photo("art-1-def", {"rotate": 90})
        self.assertEqual(row["stage"], "not-applied")
        self.assertEqual(self.app.photos()["pending"], 1)
        self.app.decide_photo("art-1-def", {"note": "check the signature"})
        self.assertEqual(self.saved()["art-1-def"]["rotate"], 90, "a note keeps the rotation")
        self.assertEqual(self.app.decide_photo("art-1-def", {"decision": "reject"})["stage"], "rejected")
        self.assertEqual(self.app.decide_photo("art-1-def", {"decision": None})["decision"], None)

    def test_corrected_corners_are_kept_by_other_changes(self):
        corners = [[1.0, 1.0], [900.0, 1.0], [900.0, 900.0], [1.0, 900.0]]
        (self.out / "decisions.json").write_text(json.dumps({"img-1-abc": {"decision": "fix", "corners": corners}}))
        self.app.decide_photo("img-1-abc", {"note": "looks right"})
        self.assertEqual(self.saved()["img-1-abc"]["decision"], "fix")
        self.assertEqual(self.saved()["img-1-abc"]["corners"], corners)

    def test_saving_corners_marks_the_photo_corrected_and_pending(self):
        dragged = [[950, 1100], [40, 30], [960, 20], [30, 1150]]          # any order, as dragged
        row = self.app.decide_photo("img-1-abc", {"corners": dragged})
        saved = self.saved()["img-1-abc"]
        self.assertEqual(saved["decision"], "fix")
        self.assertEqual(saved["corners"], [[40.0, 30.0], [960.0, 20.0], [950.0, 1100.0], [30.0, 1150.0]])
        self.assertEqual(row["stage"], "not-applied", "saved corners wait for Apply")
        self.assertTrue(saved["decided_at"])
        self.app.decide_photo("img-1-abc", {"corners": None})
        self.assertNotIn("corners", self.saved()["img-1-abc"])
        self.assertIsNone(self.saved()["img-1-abc"]["decision"], "back to the outline the crop found")

    def test_corner_refusals(self):
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.decide_photo("art-1-def", {"corners": [[0, 0], [9, 0], [9, 9], [0, 9]]})
        self.assertEqual(e.exception.code, 400, "a ready-cut file has no corners")
        for bad in ([[0, 0], [1, 0], [1, 1]], [[0, 0], [5, 0], [5, 5], [0, 5]], "x", [[0, 0], [9, 0], [9, 9], ["a", 9]]):
            with self.assertRaises(self.srv.ApiError, msg=bad):
                self.app.decide_photo("img-1-abc", {"corners": bad})
        self.assertFalse((self.out / "decisions.json").exists(), "nothing written on a refusal")

    def test_the_detail_has_what_the_editor_needs(self):
        d = self.app.photo("img-1-abc")
        self.assertEqual(d["photo_size"], [1000, 1200])
        self.assertEqual(d["photo"], "img/img-1-abc.photo.jpg?v=2026-10-27T10:00:00Z", "re-cropped files bust the cache")
        self.assertEqual(d["detected"]["reasons"], ["edges unclear"])
        self.assertEqual((d["prev"], d["next"]), (None, "art-1-def"))
        self.assertIsNone(d["listing_title"])

    def test_bad_photo_requests(self):
        for bad in ({}, {"decision": "fix"}, {"rotate": 45}, {"decision": "publish"}, {"price": 1}):
            with self.assertRaises(self.srv.ApiError, msg=bad) as e:
                self.app.decide_photo("img-1-abc", bad)
            self.assertEqual(e.exception.code, 400)
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.decide_photo("nope", {"decision": "accept"})
        self.assertEqual(e.exception.code, 404)

    def test_apply_with_nothing_pending(self):
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.apply_photos()
        self.assertEqual(e.exception.code, 400)

    def test_routes(self):
        routes = [(m, p.pattern) for m, p, _ in self.srv.ROUTES]
        for r in [("GET", "^/api/photos$"), ("GET", r"^/api/photos/([\w.-]+)$"), ("PUT", r"^/api/photos/([\w.-]+)$"),
                  ("POST", "^/api/photos/apply$")]:
            self.assertIn(r, routes)


class Wiring(unittest.TestCase):
    def test_photos_is_first_in_the_nav_and_has_a_page(self):
        main = read(REPO / "apps/review-dashboard/src/main.tsx")
        self.assertIn('["photos", "Photos"]', main)
        page = read(REPO / "apps/review-dashboard/src/pages/Photos.tsx")
        for s in ("api.decidePhoto", "api.applyPhotos", 'className="timeline"', "time not recorded",
                  '<a className="photo-open" href={`#/photos/${p.id}`}'):
            self.assertIn(s, page)
        detail = read(REPO / "apps/review-dashboard/src/pages/PhotoDetail.tsx")
        for s in ("send({ corners: pts })", "send({ corners: null })", "<CornerEditor", "beforeunload"):
            self.assertIn(s, detail)
        editor = read(REPO / "apps/review-dashboard/src/components/CornerEditor.tsx")
        for s in ('role="slider"', "onKeyDown"):
            self.assertIn(s, editor)
        self.assertIn('section === "photos" && id', main)


if __name__ == "__main__":
    unittest.main()
