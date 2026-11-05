"""One status per piece, in one place (B-074), and the guard that the redesign kept every feature."""
import re
import unittest
from pathlib import Path

from packages import journey
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, record_for, tmp
from tests.test_storefront_preview import FACTS, ITEM, MAPPING
import json

PRICE = {"severity": "blocking", "target": "product.price", "question": "What does it sell for?"}
SOLD = {"severity": "blocking", "target": "product.sold_as", "question": "Original or print?"}
LATER = {"severity": "blocking", "target": "assets.delivery", "question": "Images aren't uploaded yet."}
COPY = {"severity": "blocking", "target": "copy.approval", "question": "Approve the copy first."}
MATCH = {"severity": "blocking", "target": "catalog.match", "question": "Is this the same piece?"}
SRC = REPO / "apps/review-dashboard/src"


def status(stage="approved", drafted=True, copy_approved=True, publish_state=None, store_state="ready", **kw):
    return journey.status(stage=stage, drafted=drafted, copy_approved=copy_approved, publish_state=publish_state,
                          store_state=store_state, **kw)


class Status(unittest.TestCase):
    def test_the_journey_in_order(self):
        self.assertEqual(status(stage="to-review", drafted=False, copy_approved=False, store_state=None)["id"], "review-photo")
        self.assertEqual(status(stage="ready", drafted=False, copy_approved=False, store_state=None)["id"], "ready-to-draft")
        self.assertEqual(status(stage="drafted", copy_approved=False, store_state="blocked")["id"], "review-copy")
        self.assertEqual(status(store_state="blocked", blockers=[PRICE])["id"], "add-details")
        self.assertEqual(status(store_state="ready")["id"], "approve-for-store")
        self.assertEqual(status(store_state="approved")["id"], "ready-to-publish")
        self.assertEqual(status(store_state="approved", publish_state="QUEUED")["id"], "publishing")
        self.assertEqual(status(store_state="approved", publish_state="WRITING")["id"], "publishing")
        self.assertEqual(status(store_state="approved", publish_state="SUCCEEDED")["id"], "published")

    def test_approved_copy_is_not_called_ready_when_the_store_is_blocked(self):
        s = status(store_state="blocked", blockers=[COPY, SOLD, PRICE, LATER])
        self.assertEqual(s["id"], "add-details")
        self.assertEqual(s["detail"], "Needs price and sold as")
        self.assertEqual([b["target"] for b in s["blockers"]], ["product.sold_as", "product.price"])

    def test_the_real_blocker_is_named(self):
        self.assertEqual(status(store_state="blocked", blockers=[MATCH])["detail"], "Is this the same piece?")
        self.assertEqual(status(store_state="blocked", blockers=[PRICE, MATCH])["detail"], "2 things to resolve")
        self.assertEqual(status(store_state="blocked", blockers=[PRICE])["detail"], "Needs price")

    def test_a_warning_is_not_a_blocker(self):
        s = status(store_state="blocked", blockers=[dict(PRICE, severity="warning"), SOLD])
        self.assertEqual(s["detail"], "Needs sold as")

    def test_copy_comes_before_details(self):
        s = status(stage="drafted", copy_approved=False, store_state="blocked", blockers=[COPY, PRICE])
        self.assertEqual(s["id"], "review-copy")
        self.assertEqual(s["detail"], "Needs price", "what's also missing is still shown")

    def test_what_happened_comes_first(self):
        self.assertEqual(status(store_state="out_of_date", publish_state="SUCCEEDED")["id"], "published")
        self.assertEqual(status(store_state="out_of_date", publish_state="OUTCOME_UNKNOWN")["id"], "needs-look")
        unknown = status(store_state="approved", publish_state="OUTCOME_UNKNOWN")
        self.assertEqual(unknown["id"], "needs-look", "never ready to publish: publishing again could add it twice")
        self.assertIn("Check the store", unknown["next"])
        self.assertEqual(status(stage="to-review", publish_state="SUCCEEDED")["id"], "published")

    def test_problems_need_a_look(self):
        self.assertEqual(status(store_state="approved", publish_state="FAILED")["id"], "needs-look")
        s = status(store_state="out_of_date", changes=["price"])
        self.assertEqual(s["id"], "needs-look")
        self.assertIn("price", s["next"])
        self.assertEqual(status(store_state="out_of_date", publish_state="FAILED")["id"], "needs-look")

    def test_a_rejected_photo_stays_rejected(self):
        self.assertEqual(status(stage="rejected", publish_state="SUCCEEDED")["id"], "rejected")

    def test_saved_changes_not_applied_are_named(self):
        s = status(stage="not-applied")
        self.assertEqual(s["id"], "review-photo")
        self.assertEqual(s["detail"], "Saved changes not applied")

    def test_no_store_never_says_ready_to_publish(self):
        self.assertEqual(status(store_state=None)["id"], "approve-for-store")

    def test_every_status_has_one_word_for_it(self):
        self.assertEqual(len({s["label"] for s in journey.STATUSES}), len(journey.STATUSES))
        for sid in journey.PIPELINE:
            self.assertIn(sid, journey.LABELS)


class NextStep(unittest.TestCase):
    def pieces(self, *ids, **kw):
        return [{"id": f"p{n}", "status": status(**kw) if not i else dict(journey.LABELS[i], next="Do it", detail=kw.get("detail", ""), blockers=[])}
                for n, i in enumerate(ids)]

    def test_setup_comes_first(self):
        self.assertEqual(journey.next_step([], setup_done=False, can_draft=True)["href"], "#/start")

    def test_nothing_waiting(self):
        self.assertIsNone(journey.next_step([], setup_done=True, can_draft=True))
        self.assertIsNone(journey.next_step(self.pieces("published", "rejected", "publishing"), setup_done=True, can_draft=True))

    def test_your_situation_in_one_line(self):
        pieces = [{"id": "a", "status": status(store_state="blocked", blockers=[PRICE, SOLD])},
                  {"id": "b", "status": status(store_state="blocked", blockers=[PRICE, SOLD])},
                  {"id": "c", "status": status(stage="ready", drafted=False, copy_approved=False, store_state=None)}]
        n = journey.next_step(pieces, setup_done=True, can_draft=True)
        self.assertEqual(n["headline"], "2 pieces need a price and sold as")
        self.assertEqual(n["href"], "#/listings/a")

    def test_problems_outrank_everything(self):
        n = journey.next_step(self.pieces("ready-to-draft", "add-details", "needs-look"), setup_done=True, can_draft=True)
        self.assertEqual(n["href"], "#/listings/p2")

    def test_finishing_comes_before_starting(self):
        order = [("ready-to-publish", "#/publish"), ("approve-for-store", "#/listings/p0"), ("add-details", "#/listings/p0"),
                 ("review-copy", "#/listings/p0"), ("review-photo", "#/photos"), ("ready-to-draft", "#/listings")]
        for k, (sid, href) in enumerate(order):
            rest = [x for x, _ in order[k + 1:]]
            self.assertEqual(journey.next_step(self.pieces(sid, *rest), setup_done=True, can_draft=True)["href"], href, sid)

    def test_drafting_without_a_key_says_so(self):
        self.assertEqual(journey.next_step(self.pieces("ready-to-draft"), setup_done=True, can_draft=False)["href"], "#/start")

    def test_singular(self):
        self.assertIn("1 piece is", journey.next_step(self.pieces("ready-to-publish"), setup_done=True, can_draft=True)["headline"])


class Server(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        self.dir = tmp()
        out = self.dir / "review"
        (out / "img").mkdir(parents=True)
        from PIL import Image
        Image.new("RGB", (600, 800), (120, 90, 60)).save(out / "img" / "fox.framed.jpg")
        (out / "items.json").write_text(json.dumps([dict(ITEM, status="ready", art_file="img/fox.framed.jpg")]))
        (self.dir / "mapping.json").write_text(json.dumps(MAPPING))
        self.app = self.srv.App(out=out, brand_root=self.dir / "brand", learning_root=self.dir / "learning",
                                config=self.dir / "none.json", source=tmp(), rooms_root=self.dir / "rooms",
                                mapping=self.dir / "mapping.json")
        self.out = out
        self.app.store.save_draft("fox", record_for("fox", 1))

    def row(self):
        return self.app.state()["items"][0]

    def test_every_page_gets_the_same_status(self):
        self.app.store.approve("fox", "owner")
        want = self.row()["status"]
        self.assertEqual(want["id"], "add-details")
        self.assertEqual(self.app.detail("fox")["status"], want)
        self.assertEqual(self.app.photos()["photos"][0]["status"], want)
        self.assertEqual(self.app.photo("fox")["status"], want)
        self.assertEqual(self.app.publish_queue()["waiting"][0]["status"], want)
        self.assertEqual(self.app.home()["pieces"][0]["status"], want)

    def test_saving_only_the_details_moves_it_on(self):
        self.app.store.approve("fox", "owner")
        self.app.update_listing("fox", {"facts": FACTS})
        self.assertEqual(self.row()["status"]["id"], "approve-for-store")
        self.assertEqual(self.app.store.listing("fox")["facts"]["medium"], FACTS["medium"], "the other facts stay")

    def test_the_start_page_says_what_to_do(self):
        self.app.store.approve("fox", "owner")
        home = self.app.home()
        self.assertEqual(home["next"]["href"] if home["onboarding"]["complete"] else "#/listings/fox",
                         "#/listings/fox")
        self.assertEqual([s["id"] for s in home["pipeline"]], journey.PIPELINE)
        self.assertEqual(home["listings"]["drafted"], 1, "the old counts are all still there")

    def test_a_thumbnail_is_small_and_remade_when_the_piece_changes(self):
        import os
        from PIL import Image
        path = self.row()["thumb"].split("?")[0]
        thumb = self.out / path
        with Image.open(thumb) as im:
            self.assertLessEqual(max(im.size), 240)
        before = thumb.read_bytes()
        Image.new("RGB", (600, 800), (10, 200, 60)).save(self.out / "img" / "fox.framed.jpg")
        future = thumb.stat().st_mtime + 10
        os.utime(self.out / "img" / "fox.framed.jpg", (future, future))
        self.row()
        self.assertNotEqual(thumb.read_bytes(), before)

    def test_a_broken_image_never_stops_the_page(self):
        (self.out / "img" / "fox.framed.jpg").write_bytes(b"not an image")
        self.assertEqual(self.row()["thumb"], "img/fox.framed.jpg")

    def test_a_status_changes_nothing_in_a_change_set(self):
        self.app.store.approve("fox", "owner")
        self.app.update_listing("fox", {"facts": FACTS})
        hash_ = self.app.change_set("fox")[0]["change_set_hash"]
        self.app.state(); self.app.home(); self.app.detail("fox")
        self.assertEqual(self.app.change_set("fox")[0]["change_set_hash"], hash_)


class KeptFeatures(unittest.TestCase):
    """The redesign moved things and removed none. Each of these does something on a page today."""
    CALLS = ["addMeaning", "answerMatch", "applyPhotos", "approve", "approveStorefront", "brand", "decide", "decidePhoto", "distil", "draftPending", "home", "inbox", "item", "killSwitch", "learning", "nameSizes", "onboarding", "onboardingCheck", "onboardingKey", "onboardingLogin", "onboardingMapping", "onboardingStore", "photo", "photoRoom", "photos", "previewRoom", "publish", "publishMany", "publishQueue", "publishRecheck", "redraft", "refreshCatalog", "renderRooms", "room", "rooms", "saveBrand", "saveCopy", "saveListing", "saveNameSizes", "saveRoom", "scanInbox", "scanRooms", "setup", "state", "storefront", "suggestRoom", "suggestRooms", "unlock", "uploadRoom"]
    PLACES = {
        "pages/Listings.tsx": ["<NameSizes", "Draft next", '"to-draft"', '"edited"', '"blocking"', '"approved"'],
        "pages/ListingDetail.tsx": ["Unlock to edit", "Redraft with my note", "Approve copy", "<AboutPiece", "<ReviewTabs",
                                    "<MeaningPanel", "<StorefrontPanel", "Show", "Previous", "beforeunload", "Save note", "Record meaning"],
        "pages/Photos.tsx": ["Look for new photos", "Rotate", "Accept", "Reject", "Crop & corners", "Listing →", "Latest activity", "File name", "imported"],
        "pages/PhotoDetail.tsx": ["Save corners", "Whole photo", "Back to the outline", "Apply changes", "Change room", "Make it again", "History", "<AboutPiece", "Rotate", "Reject", "Accept"],
        "pages/Rooms.tsx": ["Add a room", "Look for new rooms", "Hang every piece in its room"],
        "pages/RoomDetail.tsx": ["Save room", "Suggest again", "Use the suggested area", "Preview", "Use this room for listings", "Source link"],
        "pages/Publish.tsx": ["Stop all writing", "Select all", "Publish again", "Check again"],
        "pages/Learning.tsx": ["Learn from my edits", "Retire", "Words you keep removing", "Decided lessons", "latest 10"],
        "pages/Brand.tsx": ["Save as new version", "Add phrase", "Confirmed meanings", "Versions", "#/setup"],
        "pages/Home.tsx": ["No store connected yet", "Finish connecting", "Finish getting started", "new in the inbox", "worker isn't running"],
        "main.tsx": ["<NewPhotos", "<UserMenu", "Getting started", "Voice setup", "drafting is off"],
    }

    def test_every_server_call_is_still_used(self):
        files = list(SRC.glob("pages/*.tsx")) + list(SRC.glob("components/*.tsx")) + [SRC / "main.tsx"]
        used = set(re.findall(r"\bapi\.(\w+)\(", "".join(read(f) for f in files)))
        self.assertEqual(sorted(set(self.CALLS) - used), [])

    def test_every_control_is_still_there(self):
        for rel, needles in self.PLACES.items():
            src = read(SRC / rel)
            for needle in needles:
                self.assertIn(needle, src, rel)

    def test_voice_setup_stays_reachable_once_a_voice_exists(self):
        self.assertIn('menu.filter(([k]) => k !== "setup" || !state.brand)', read(SRC / "main.tsx"))
        self.assertIn('href="#/setup"', read(SRC / "pages/Brand.tsx"))


class Words(unittest.TestCase):
    def test_pages_show_the_one_status(self):
        for rel in ("pages/Listings.tsx", "pages/Photos.tsx", "pages/PhotoDetail.tsx", "pages/ListingDetail.tsx", "pages/Publish.tsx"):
            self.assertIn("StatusBadge", read(SRC / rel), rel)

    def test_a_green_outline_means_published(self):
        self.assertIn('i.status.id === "published" ? "is-published"', read(SRC / "pages/Listings.tsx"))
        self.assertNotIn("is-approved", read(SRC / "pages/Listings.tsx"))

    def test_a_bar_save_reads_back_before_about_this_piece_remounts(self):
        self.assertIn("await load(); setFactsRev((n) => n + 1);", read(SRC / "pages/ListingDetail.tsx"))

    def test_the_font_is_stored_locally(self):
        self.assertIn('"@fontsource/ibm-plex-sans"', read(REPO / "apps/review-dashboard/package.json"))
        self.assertNotIn("fonts.googleapis", read(REPO / "apps/review-dashboard/index.html"))

    def test_start_installs_new_dashboard_dependencies(self):
        self.assertIn("package-lock.json -nt", read(REPO / "start.sh"))
