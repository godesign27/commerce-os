"""Collector descriptions as small human stories (B-060): the creative direction in the writing standards,
the `human_story` rubric criterion, the metallic-surface claim, and the voice warnings. No network."""
import copy
import unittest

from packages.drafting import brand, checks, editing, listing
from packages.drafting.store import Store
from tests._helpers import REPO
from tests.test_drafting import CTX
from tests.test_listing_copy import record_for, tmp

STANDARDS = (brand.SKILL_REFS / "writing-standards.md").read_text()
RUBRIC_MD = (brand.SKILL_REFS / "rubric.md").read_text()
CRITERION = ("Does this read like a small human story grounded in this particular piece, or like a visual "
             "inventory or generic art advertisement?")
CLEAN = ("The first thing you notice is how little the hare is bothered by any of it. Ears up, one eye on you, "
         "it sits in the lower corner while loops of colour crowd the sky above. Spend a while with it and the "
         "stillness starts to feel like a decision. It has heard everything and chosen to stay.")
BG = {"id": "mean-bg", "scope": {"kind": "catalog", "ref": None}, "subject": "the layered, textured backgrounds",
      "meaning": "Reality breaking down into particles and energy, and the emotion of that particular moment."}


def found(text, ctx=None):
    return {f["check"] for f in checks.voice_findings(text, ctx)}


class Direction(unittest.TestCase):
    def test_the_standards_carry_the_creative_direction(self):
        for line in ("Open on a moment, a feeling or an encounter.", "Ground it in two or three visible details",
                     "Interpretation is welcome; attribution is not.", "Trust the reader.",
                     "End on a resonant thought or image.", "Keep the storytelling understated.",
                     "Descriptive storytelling is welcome; fabricated facts are not.", CRITERION.split("?")[0][9:]):
            self.assertIn(line, " ".join(STANDARDS.split()), line)
        self.assertIn("for tone only; never a template", STANDARDS)
        self.assertNotIn("Otto", STANDARDS)

    def test_the_example_is_read_from_the_standards(self):
        ex = checks.example_texts()
        self.assertEqual(len(ex), 1)
        self.assertTrue(ex[0].startswith("There's something familiar about being met with a look like this."))
        self.assertTrue(ex[0].endswith("whatever kind of day you bring to the painting."))

    def test_the_rubric_asks_the_human_story_question(self):
        self.assertIn("human_story", listing.RUBRIC)
        self.assertIn(" ".join(CRITERION.split()), " ".join(listing.RUBRIC_TEXT.split()))
        self.assertIn(CRITERION, RUBRIC_MD)
        self.assertIn("12 of 14", RUBRIC_MD)
        schema = listing.response_schema(["painting"], ["Animals"], ["animal"])
        self.assertIn("human_story", schema["properties"]["self_review"]["required"])
        self.assertEqual(listing.PROMPT_VERSION, "listing-draft@4")

    def test_the_prompt_sends_the_direction(self):
        req = listing.build_request(b"x", "image/jpeg", {"painting": {"display_name": "Painting"}}, ["Animals"],
                                    brand_ctx=CTX)
        system = " ".join(b["text"] for b in req["system"])
        self.assertIn("a small human story grounded in this particular piece", system)
        self.assertIn("End on a resonant thought or image.", system)
        self.assertIn("shimmering", system)

    def test_self_review_bar_scales_with_the_rubric(self):
        full = {k: 2 for k in listing.RUBRIC}
        ok = dict(full, human_story=1, distinctiveness=1)                   # 12 of 14
        low = dict(full, human_story=0, distinctiveness=1)                  # 11 of 14
        self.assertNotIn("self_review", {f["check"] for f in checks.check_copy({"item": "a"}, [], None, ok)})
        msg = [f["message"] for f in checks.check_copy({"item": "a"}, [], None, low) if f["check"] == "self_review"]
        self.assertEqual(msg, ["Self-review 11/14 (below 2: distinctiveness, human_story)."])


class MetallicSurface(unittest.TestCase):
    def test_a_photo_cannot_supply_leaf_or_shimmer(self):
        v = checks.claim_violations("its chest gives way to shimmering silver and glinting copper bolts")
        self.assertIn("surface or finish: 'shimmering'", v)
        self.assertIn("surface or finish: 'glinting'", v)
        self.assertEqual(checks.claim_violations("pale gold bolts on a silver-grey coat"), [], "colours are fine")

    def test_a_supplied_medium_allows_it(self):
        self.assertEqual(checks.claim_violations("shimmering gold leaf", {"medium": "acrylic and gold leaf on panel"}),
                         [])
        self.assertTrue(checks.claim_violations("shimmering", {"medium": "acrylic on canvas"}))


class VoiceWarnings(unittest.TestCase):
    def test_a_good_story_passes(self):
        self.assertEqual(found(CLEAN, {"meanings": [BG]}), set())

    def test_closing_question(self):
        self.assertIn("closing_question", found(CLEAN + " What would you call that?"))
        self.assertNotIn("closing_question", found("Is it waiting? It is. " + CLEAN))

    def test_stock_phrases(self):
        f = checks.voice_findings("A captivating piece, a testament to patience, that will elevate your space.")
        msg = next(x["message"] for x in f if x["check"] == "stock_phrase")
        self.assertIn("'elevate your space'", msg)
        self.assertIn("'a testament to'", msg)
        self.assertNotIn("'testament to'", msg, "only the longest form is reported")

    def test_stacked_hedges(self):
        self.assertNotIn("hedge_stack", found("It seems calm. Perhaps it is. " + CLEAN))
        self.assertIn("hedge_stack", found("Perhaps it waits, as if listening, as though it seems to know. " + CLEAN))

    def test_catalog_meaning_restated(self):
        bad = "In this work the layered grounds stand for reality breaking into energy, one particular moment."
        self.assertIn("catalog_meaning_restated", found(CLEAN + " " + bad, {"meanings": [BG]}))
        animals = {"id": "mean-animals", "scope": {"kind": "catalog", "ref": None},
                   "subject": "animals that recur across the catalog",
                   "meaning": "The artist returns to the same animals because the need to call on their "
                              "characteristics keeps coming back."}
        self.assertNotIn("catalog_meaning_restated", found("The band keeps coming back to that ember, and what "
                                                           "a call it makes.", {"meanings": [animals]}),
                         "ordinary words shared by chance are not a restatement")
        self.assertIn("catalog_meaning_restated", found("These animals keep coming back because their "
                                                        "characteristics are needed.", {"meanings": [animals]}))
        series = dict(BG, scope={"kind": "series", "ref": "Storm"})
        self.assertNotIn("catalog_meaning_restated", found(bad, {"meanings": [series]}),
                         "series and artwork meanings are the heart of the copy, not background")

    def test_copies_the_example(self):
        self.assertIn("copies_example", found("There's something familiar about being met with a look like this. "
                                              "A hare sits low."))

    def test_check_copy_reports_them_on_the_collector_description(self):
        c = {"item": "a", "title": "X", "short_description": "", "collector_description": CLEAN + " Why?"}
        f = [x for x in checks.check_copy(c, [], None) if x["check"] == "closing_question"]
        self.assertEqual([(x["severity"], x["target"]) for x in f], [("warning", "product.description")])

    def test_owner_saves_see_them_but_are_never_blocked(self):
        store = Store(tmp())
        store.save_draft("a", record_for("a"))
        res = editing.save(store, "a", {"collector": CLEAN + " Would you?"}, CTX)
        self.assertEqual(res["copy"]["collector_description"], CLEAN + " Would you?")
        self.assertIn(("warning", "collector_description", "closing_question"),
                      [(c["severity"], c["field"], c["check"]) for c in res["checks"]])


class Docs(unittest.TestCase):
    def test_the_skill_and_docs_point_at_the_direction(self):
        skill = (REPO / "plugins/commerce-os/skills/listing-copy/SKILL.md").read_text()
        self.assertIn("listing-draft@4", skill)
        self.assertIn(" ".join(CRITERION.split()), " ".join(skill.split()))
        self.assertIn("B-060", (REPO / "docs/listing-copy.md").read_text())
        page = (REPO / "apps/review-dashboard/src/pages/ListingDetail.tsx").read_text()
        self.assertIn('human_story: "Human story"', page)


if __name__ == "__main__":
    unittest.main()
