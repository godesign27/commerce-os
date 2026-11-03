"""Listing copy around the model (B-056, B-057): brand context, repetition checks, local state, the
learning loop, and the local dashboard API. No network: the model is a stand-in function."""
import copy
import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from packages.drafting import brand, checks, learning, service
from packages.drafting.store import LockedError, Store
from tests._helpers import REPO, load_json
from tests.test_drafting import CLEAN, CTX, TAGS, TYPES

HAS_PIL = importlib.util.find_spec("PIL") is not None


def tmp(prefix="cos-"):
    return Path(tempfile.mkdtemp(prefix=prefix))


def copy_of(item, title, short="", long=""):
    return {"item": item, "title": title, "short_description": short, "collector_description": long}


class BrandContext(unittest.TestCase):
    def test_fixture_and_template_validate(self):
        self.assertEqual(brand.violations(CTX), [])

    def test_meanings_apply_only_in_scope(self):
        ctx = copy.deepcopy(CTX)
        ctx["meanings"].append({"id": "mean-3", "scope": {"kind": "artwork", "ref": "img-9"}, "subject": "the fox",
                                "meaning": "adaptability", "recorded_by": {"kind": "human", "id": "owner-1"},
                                "recorded_at": "2026-10-28T10:00:00Z"})
        ids = lambda *a: [m["id"] for m in brand.meanings_in_scope(ctx, *a)]  # noqa: E731
        self.assertEqual(ids("img-1", None), ["mean-2"], "only the catalog-wide meaning")
        self.assertEqual(ids("img-9", None), ["mean-2", "mean-3"])
        self.assertEqual(ids("img-1", "harbour"), ["mean-1", "mean-2"], "series match ignores case")
        self.assertEqual(ids("img-1", "Harbor"), ["mean-2"], "a different series is not the same series")

    def test_save_versions_and_archives_never_overwriting(self):
        root = tmp()
        ctx = copy.deepcopy(CTX)
        first = brand.save(ctx, {"kind": "human", "id": "owner-1"}, root)
        self.assertEqual(first["version"], 3)
        second = brand.save(dict(first, philosophy="Changed."), {"kind": "human", "id": "owner-1"}, root)
        self.assertEqual(second["version"], 4)
        self.assertEqual([h["version"] for h in brand.history("storefront-a", root)], [3])
        self.assertEqual(brand.load("storefront-a", root)["philosophy"], "Changed.")

    def test_invalid_context_is_not_saved(self):
        root = tmp()
        bad = dict(copy.deepcopy(CTX), site_kind="shop")
        with self.assertRaises(brand.BrandContextError):
            brand.save(bad, {"kind": "human", "id": "owner-1"}, root)
        self.assertIsNone(brand.load("storefront-a", root))

    def test_duplicate_ids_are_refused(self):
        ctx = copy.deepcopy(CTX)
        ctx["lessons"][0]["id"] = "mean-1"
        self.assertTrue(any("unique" in e for e in brand.violations(ctx)))

    def test_product_site_renders_as_a_brand(self):
        ctx = dict(copy.deepcopy(CTX), site_kind="product")
        self.assertIn("site kind: product", brand.render(ctx))
        self.assertIn("The brand's own words", brand.render(ctx))


class Repetition(unittest.TestCase):
    def check(self, mine, others, ctx=CTX, **kw):
        return {f["check"]: f for f in checks.check_copy(mine, others, ctx, **kw)}

    def test_duplicate_title_blocks(self):
        f = self.check(copy_of("a", "Low Tide"), [copy_of("b", "low tide")])
        self.assertEqual(f["duplicate_title"]["severity"], "blocking")

    def test_a_title_word_in_two_other_titles_is_flagged(self):
        others = [copy_of("b", "The Moment Before"), copy_of("c", "A Moment in Motion")]
        self.assertIn("moment", self.check(copy_of("a", "Moment of Rest"), others)["title_word_reused"]["message"])
        self.assertNotIn("title_word_reused", self.check(copy_of("a", "Moment of Rest"), others[:1]))

    def test_title_options_sharing_their_main_word(self):
        f = self.check(copy_of("a", "Kept Ember"), [], title_options=["Kept Ember", "Ember Held", "Last Ember"])
        self.assertIn("options_share_word", f)

    def test_watch_phrase_limits(self):
        ctx = copy.deepcopy(CTX)
        ctx["watch_phrases"] = [{"phrase": "invites viewers", "max_share": 0.0}, {"phrase": "energy", "max_share": 0.3}]
        others = [copy_of(f"o{i}", f"T{i}", long="Calm water." if i else "Raw energy here.") for i in range(9)]
        f = self.check(copy_of("a", "X", long="It invites viewers in."), others, ctx)
        self.assertIn("watch_phrase", f, "a 0% phrase is flagged on first use")
        self.assertNotIn("watch_phrase", self.check(copy_of("a", "X", long="Pure energy."), others, ctx),
                         "2 of 10 is within 30%")
        crowded = [copy_of(f"o{i}", f"T{i}", long="Raw energy.") for i in range(9)]
        self.assertIn("watch_phrase", self.check(copy_of("a", "X", long="Pure energy."), crowded, ctx))

    def test_first_use_of_a_limited_phrase_in_a_small_catalog_is_fine(self):
        ctx = copy.deepcopy(CTX)
        ctx["watch_phrases"] = [{"phrase": "a single moment", "max_share": 0.05}]
        others = [copy_of(f"o{i}", f"T{i}") for i in range(4)]
        self.assertNotIn("watch_phrase", self.check(copy_of("a", "X", long="Held for a single moment."), others, ctx))

    def test_shared_phrasing_and_same_opening(self):
        a = "Everything about this hare is listening, ears up and still."
        b = "Everything about this wolf is waiting; ears up and still in the rain."
        f = self.check(copy_of("a", "X", long=a), [copy_of("b", "Y", long=b)])
        self.assertIn("same_opening", f)
        self.assertNotIn("shared_phrasing", f, "four shared words in a row is fine")
        f = self.check(copy_of("a", "X", long="reality breaking into particles and light"),
                       [copy_of("b", "Y", long="the ground is reality breaking into particles and energy")])
        self.assertIn("reality breaking into particles and", f["shared_phrasing"]["message"])

    def test_length_and_rejected_style_words(self):
        f = self.check(copy_of("a", "X", short="Too short.", long="Also short, and naive."), [])
        self.assertEqual(sum(1 for x in checks.check_copy(copy_of("a", "X", short="Too short.", long="x"), [], CTX)
                             if x["check"] == "length"), 2)
        self.assertIn("rejected_style_word", f)

    def test_low_self_review_is_flagged(self):
        f = self.check(copy_of("a", "X"), [], self_review={"brand_alignment": 1, "distinctiveness": 0})
        self.assertIn("self_review", f)

    def test_own_listing_is_never_compared_with_itself(self):
        self.assertNotIn("duplicate_title", self.check(copy_of("a", "Low Tide"), [copy_of("a", "Low Tide")]))


def record_for(item, revision=1, output=None):
    from tests.test_drafting import draft
    d = draft(output or CLEAN)
    d["revision"] = revision
    return {"item": item, "source": f"{item}.jpg", "art_file": "x", "drafted_at": "2026-10-28T10:00:00Z",
            "model": "claude-opus-5-5", "request_id": "r", "usage": {}, "cost_usd": 0.1,
            "model_output": output or CLEAN, "draft": d, "policy_violations": []}


class LocalState(unittest.TestCase):
    def setUp(self):
        self.store = Store(tmp())

    def test_edits_sit_on_top_of_the_draft(self):
        self.store.save_draft("a", record_for("a"))
        self.store.update("a", edits={"title": "Mine"}, chosen_title="Grey Patience")
        eff = self.store.effective("a")
        self.assertEqual(eff["title"], "Mine", "an explicit edit beats the chosen option")
        self.assertEqual(eff["short_description"], CLEAN["short_description"])

    def test_revisions_are_archived(self):
        self.store.save_draft("a", record_for("a", 1))
        self.store.save_draft("a", record_for("a", 2))
        self.assertEqual(self.store.revisions("a"), [1])
        self.assertEqual(self.store.next_revision("a"), 3)

    def test_approved_copy_is_locked_until_unlocked(self):
        self.store.save_draft("a", record_for("a"))
        self.store.update("a", edits={"title": "Mine"})
        self.store.approve("a", "owner")
        with self.assertRaises(LockedError):
            self.store.save_draft("a", record_for("a", 2))
        with self.assertRaises(LockedError):
            self.store.update("a", edits={"title": "Again"})
        self.store.update("a", note="notes stay editable")
        entry = self.store.unlock("a", "owner")
        self.assertEqual(entry["edits"]["title"], "Mine", "unlocking keeps the approved copy as the starting point")
        self.assertEqual(entry["unlocked"][0]["by"], "owner")
        self.store.save_draft("a", record_for("a", 2))

    def test_input_validation(self):
        for bad in ({"facts": {"sku": "10"}}, {"facts": {"price": "ten"}}, {"facts": {"price": "10.999"}},
                    {"facts": {"edition": "deluxe"}}, {"edits": {"price": "1"}},
                    {"edits": {"store_tags": "Animals"}}):
            with self.assertRaises(ValueError, msg=bad):
                self.store.update("a", **bad)

    def test_corpus_prefers_approved_copy(self):
        self.store.save_draft("a", record_for("a"))
        self.store.update("a", edits={"title": "Final Title"})
        self.store.approve("a", "owner")
        self.store.save_draft("b", record_for("b"))
        corpus = {c["item"]: c for c in self.store.corpus(exclude="b")}
        self.assertEqual(list(corpus), ["a"])
        self.assertEqual(corpus["a"]["title"], "Final Title")
        self.assertTrue(corpus["a"]["approved"])


class LearningLoop(unittest.TestCase):
    def setUp(self):
        self.learn = learning.Learning(tmp())

    def test_diff(self):
        d = learning.diff("a bold looping gesture sweeps across", "a gesture sweeps across")
        self.assertEqual(d["removed"], ["bold looping"])
        self.assertEqual(d["length_change"], -2)
        self.assertLess(d["similarity"], 1)

    def test_records_changes_and_acceptances(self):
        recs = self.learn.record(item="a", proposed={"title": "A", "short_description": "same"},
                                 final={"title": "B", "short_description": "same"}, revision=1,
                                 versions={"brand_context": "s@1", "prompt": "p@2"}, event="approved")
        self.assertEqual([(r["field"], r["changed"]) for r in recs], [("title", True), ("short_description", False)])
        self.assertEqual(recs[0]["brand_context"], "s@1")
        self.assertEqual([e["id"] for e in self.learn.edits()], ["edit-1", "edit-2"])
        stats = self.learn.stats()
        self.assertEqual(stats["by_field"]["short_description"]["accepted_unchanged"], 1.0)
        self.assertEqual(stats["by_field"]["title"]["accepted_unchanged"], 0.0)

    def test_prompt_pairs_never_include_titles(self):
        self.learn.record(item="a", proposed={"title": "Old", "collector_description": "very bold looping energy"},
                          final={"title": "New", "collector_description": "quiet"}, revision=1, versions={},
                          event="approved")
        pairs = self.learn.prompt_pairs()
        self.assertEqual([p["field"] for p in pairs], ["collector_description"])
        self.assertIn("owner's version: quiet", learning.pairs_text(pairs))

    def test_repeated_removals_need_two_listings(self):
        for item in ("a", "b"):
            self.learn.record(item=item, proposed={"short_description": "a vibrant sweeping loop"},
                              final={"short_description": "a loop"}, revision=1, versions={}, event="approved")
        self.assertEqual({r["phrase"] for r in self.learn.repeated_removals()}, {"vibrant", "sweeping"})

    def test_lessons_are_proposals_that_must_cite_real_edits(self):
        new = learning.add_proposed_lessons(CTX, [
            {"text": "Cut adjectives in pairs.", "evidence": ["edit-1"]},
            {"text": "Invented.", "evidence": ["edit-99"]},
            {"text": "Prefer one strong verb over two adjectives.", "evidence": ["edit-1"]},   # already on record
        ], {"edit-1"})
        added = new["lessons"][len(CTX["lessons"]):]
        self.assertEqual([(x["text"], x["status"]) for x in added], [("Cut adjectives in pairs.", "proposed")])
        self.assertEqual(brand.violations(new), [])

    def test_lesson_request_is_strict_and_never_asks_for_meanings(self):
        req = learning.lesson_request([{"id": "edit-1", "field": "title", "proposed": "A", "final": "B"}], CTX, "m")
        self.assertIn("never a meaning", req["system"][0]["text"])
        self.assertIs(req["output_config"]["format"]["schema"]["additionalProperties"], False)


@unittest.skipUnless(HAS_PIL, "Pillow not installed (use the project .venv)")
class Service(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.dir = tmp()
        Image.new("RGB", (60, 80), (200, 100, 50)).save(self.dir / "art.png")
        self.item = {"id": "a", "source": "a.png", "art_file": str(self.dir / "art.png")}
        self.store, self.learn = Store(self.dir / "review"), learning.Learning(self.dir / "learning")
        self.requests = []

    def fake(self, output=CLEAN):
        def call(client, request):
            self.requests.append(request)
            return {"output": copy.deepcopy(output), "model": "claude-opus-5-5", "request_id": "req",
                    "usage": {"input_tokens": 1000, "output_tokens": 500}}
        return call

    def draft(self, **kw):
        return service.draft_item(None, self.item, store=self.store, ctx=CTX, product_types=TYPES, tags=TAGS,
                                  learn=self.learn, call=self.fake(), **kw)

    def test_note_facts_and_series_reach_the_prompt(self):
        self.store.update("a", note="The heron is my patience.", series="Harbour", facts={"medium": "acrylic"})
        rec = self.draft()
        text = self.requests[0]["messages"][0]["content"][1]["text"]
        self.assertIn("The heron is my patience.", text)
        self.assertIn("mean-1", text, "the series meaning is in scope")
        self.assertIn("medium: acrylic", text)
        self.assertEqual(rec["inputs"]["meanings"], ["mean-1", "mean-2"])
        self.assertEqual(rec["draft"]["product"]["material"]["status"], "supplied")

    def test_redraft_records_edits_before_replacing_them(self):
        self.draft()
        self.store.update("a", edits={"collector_description": "My own words."})
        rec = self.draft()
        self.assertEqual(rec["draft"]["revision"], 2)
        changed = self.learn.changed()
        self.assertEqual([(e["field"], e["event"]) for e in changed], [("collector_description", "redrafted")])
        self.assertIn("My own words.", self.requests[1]["messages"][0]["content"][1]["text"],
                      "the owner's edit is shown to the next draft")

    def test_approve_records_the_learning_input(self):
        self.draft()
        self.store.update("a", edits={"title": "Mine"})
        res = service.approve("a", "owner", store=self.store, learn=self.learn)
        self.assertEqual(res["edits_recorded"], 1)
        self.assertEqual(self.learn.stats()["approvals"], 1)

    def test_distil_adds_proposals_as_a_new_version(self):
        root = tmp()
        brand.save(copy.deepcopy(CTX), {"kind": "human", "id": "owner-1"}, root)
        self.learn.record(item="a", proposed={"title": "A"}, final={"title": "B"}, revision=1, versions={},
                          event="approved")
        res = service.distil_lessons(None, "storefront-a", {"kind": "agent", "id": "learning-loop"}, learn=self.learn,
                                     brand_root=root, call=self.fake({"lessons": [{"text": "Shorter titles.",
                                                                                  "evidence": ["edit-1"]}]}))
        self.assertEqual(res["proposed"], 1)
        ctx = brand.load("storefront-a", root)
        self.assertEqual(ctx["lessons"][-1]["status"], "proposed")
        self.assertEqual(ctx["version"], 4)


def load_server():
    spec = importlib.util.spec_from_file_location("local_api", REPO / "services" / "local_api" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LocalApi(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        self.dir = tmp()
        out = self.dir / "review"
        out.mkdir()
        (out / "items.json").write_text(json.dumps([{"id": "a", "source": "a.jpg", "kind": "artwork",
                                                     "art_file": "x", "original": "img/a.jpg"}]))
        cfg = load_json(REPO / "config" / "storefronts.example.json")
        (self.dir / "storefronts.json").write_text(json.dumps(cfg))
        self.app = self.srv.App(out=out, brand_root=self.dir / "brand", learning_root=self.dir / "learning",
                                config=self.dir / "storefronts.json")

    def setup_body(self, **kw):
        body = {"site_kind": "artist", "name": "Sample Artist", "categories": [{"name": "Birds"}]}
        body.update(kw)
        return body

    def test_setup_asks_artist_or_product_first(self):
        with self.assertRaises(self.srv.ApiError):
            self.app.setup(self.setup_body(site_kind=None))
        ctx = self.app.setup(self.setup_body(phrases="invites viewers\nvisual language"))
        self.assertEqual((ctx["site_kind"], ctx["version"], ctx["categories"][0]["id"]), ("artist", 1, "birds"))
        self.assertEqual(len(ctx["watch_phrases"]), 2)
        cfg = json.loads((self.dir / "storefronts.json").read_text())
        self.assertEqual(cfg["storefronts"][0]["site_kind"], "artist")
        with self.assertRaises(self.srv.ApiError, msg="setup never silently replaces an existing context"):
            self.app.setup(self.setup_body())

    def test_meanings_are_recorded_with_their_scope(self):
        self.app.setup(self.setup_body())
        with self.assertRaises(self.srv.ApiError):
            self.app.add_meaning("a", {"scope": "series", "subject": "the fox", "meaning": "adaptability"})
        ctx = self.app.add_meaning("a", {"scope": "series", "series": "Northern", "subject": "the fox",
                                         "meaning": "adaptability"})
        self.assertEqual(ctx["meanings"][-1]["scope"], {"kind": "series", "ref": "Northern"})
        ctx = self.app.add_meaning("a", {"scope": "artwork", "subject": "the fox", "meaning": "this one: courage"})
        self.assertEqual(ctx["meanings"][-1]["scope"], {"kind": "artwork", "ref": "a"})

    def test_stale_brand_saves_are_refused(self):
        ctx = self.app.setup(self.setup_body())
        self.app.save_brand(dict(ctx, philosophy="v2"))
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.save_brand(dict(ctx, philosophy="stale"))
        self.assertEqual(e.exception.code, 409)

    def test_lessons_need_a_human_decision(self):
        ctx = self.app.setup(self.setup_body())
        ctx["lessons"].append({"id": "lesson-1", "text": "Shorter.", "status": "proposed", "source": "edits",
                               "evidence": ["edit-1"], "created_at": brand.now()})
        self.app.save_brand(ctx)
        ctx = self.app.decide("lesson", "lesson-1", "approved", "Shorter sentences.")
        self.assertEqual((ctx["lessons"][0]["status"], ctx["lessons"][0]["text"]), ("approved", "Shorter sentences."))
        with self.assertRaises(self.srv.ApiError):
            self.app.decide("lesson", "lesson-1", "auto")

    def test_listing_updates_are_validated(self):
        with self.assertRaises(self.srv.ApiError):
            self.app.update_listing("a", {"price": 10})
        with self.assertRaises(self.srv.ApiError):
            self.app.update_listing("missing", {"note": "x"})
        self.assertEqual(self.app.update_listing("a", {"note": "mine"})["note"], "mine")

    def test_http_binds_locally_and_writes_need_the_header(self):
        httpd = self.srv.make_server(self.app, 0)
        self.assertEqual(httpd.server_address[0], "127.0.0.1")
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            state = json.load(urllib.request.urlopen(base + "/api/state"))
            self.assertEqual(state["items"][0]["id"], "a")
            req = urllib.request.Request(base + "/api/items/a/listing", data=b'{"note":"x"}', method="PUT")
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req)
            self.assertEqual(e.exception.code, 403)
            req.add_header("X-Commerce-OS", "1")
            self.assertEqual(json.load(urllib.request.urlopen(req))["note"], "x")
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(base + "/img/../items.json")
            self.assertEqual(e.exception.code, 404)
        finally:
            httpd.shutdown()


class Wiring(unittest.TestCase):
    def test_the_skill_and_the_service_share_one_set_of_standards(self):
        self.assertEqual(brand.SKILL_REFS, REPO / "plugins/commerce-os/skills/listing-copy/references")
        skill = (REPO / "plugins/commerce-os/skills/listing-copy/SKILL.md").read_text()
        for ref in ("references/writing-standards.md", "references/rubric.md"):
            self.assertIn(ref, skill)
            self.assertTrue((REPO / "plugins/commerce-os/skills/listing-copy" / ref).exists())

    def test_standards_stay_storefront_neutral(self):
        text = (brand.SKILL_REFS / "writing-standards.md").read_text() + (brand.SKILL_REFS / "rubric.md").read_text()
        self.assertNotIn("Otto", text)

    def test_brand_context_files_are_gitignored(self):
        gitignore = (REPO / ".gitignore").read_text()
        self.assertIn("config/brand/*.local.json", gitignore)
        self.assertIn("config/brand/history/", gitignore)


if __name__ == "__main__":
    unittest.main()
