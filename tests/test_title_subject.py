"""Titles name the animal or character shown, so a search for it finds the piece (B-061). No network."""
import copy
import unittest

from packages.drafting import brand, checks, editing, listing
from packages.drafting.store import Store
from tests.test_drafting import CLEAN, CTX, draft
from tests.test_listing_copy import record_for, tmp


def found(title, name, others=(), options=None):
    return {f["check"]: f for f in checks.check_copy({"item": "a", "title": title}, list(others), None,
                                                     title_options=options, subject_name=name)}


class NameInTitle(unittest.TestCase):
    def test_matches(self):
        for title, name in [("Unhurried Lion", "lion"), ("Two Lions Resting", "lion"), ("The Snow Leopard", "snow leopard"),
                            ("Leopard at Dusk", "snow leopard"), ("Wolf-Moon", "wolf"), ("Anything", "")]:
            self.assertTrue(checks.name_in_title(title, name), (title, name))
        for title, name in [("Unhurried Reign", "lion"), ("Lioness", "lion"), ("Before the Crow", "rooster")]:
            self.assertFalse(checks.name_in_title(title, name), (title, name))

    def test_a_title_without_the_name_is_flagged(self):
        f = found("Unhurried Reign", "lion")
        self.assertEqual(f["subject_missing_from_title"]["severity"], "warning")
        self.assertIn("'Lion'", f["subject_missing_from_title"]["message"])
        self.assertNotIn("subject_missing_from_title", found("Unhurried Lion", "lion"))
        self.assertNotIn("subject_missing_from_title", found("Second Thought", ""), "abstracts are exempt")

    def test_the_name_is_never_a_reused_or_shared_word(self):
        others = [{"item": f"o{i}", "title": t} for i, t in enumerate(["Wolf Moon", "Steady Wolf", "Lone Wolves"])]
        self.assertNotIn("title_word_reused", found("The Wolf Who Stays", "wolf", others))
        self.assertNotIn("options_share_word", found("Wolf Moon", "wolf", options=["Wolf Moon", "Steady Wolf", "Wolf at Rest"]))
        self.assertIn("options_share_word", found("Wolf Moon", "", options=["Wolf Moon", "Steady Wolf", "Wolf at Rest"]),
                      "without a subject name the shared word still counts")


class Drafting(unittest.TestCase):
    def test_the_prompt_and_schema_ask_for_it(self):
        schema = listing.response_schema(["painting"], ["Animals"], ["animal"])
        self.assertIn("subject_name", schema["required"])
        self.assertEqual(listing.PROMPT_VERSION, "listing-draft@4")
        self.assertIn("When subject_name is set, every option contains it.", " ".join(listing.SYSTEM.split()))
        self.assertIn("**Name the subject.**", brand.standards_text())

    def test_the_draft_records_the_name_and_flags_a_missing_one(self):
        out = copy.deepcopy(CLEAN)
        out["subject_name"] = "Heron "
        d = draft(out)
        self.assertEqual(d["product"]["attributes"]["subject_name"]["value"], "heron")
        msgs = [i["question"] for i in d["review_issues"]]
        has_name = checks.name_in_title(out["recommended_title"], "heron")
        self.assertEqual(any("doesn't name the heron" in m for m in msgs), not has_name)

    def test_owner_titles_are_checked_too_but_saved(self):
        store = Store(tmp())
        rec = record_for("a")
        rec["draft"]["product"]["attributes"]["subject_name"] = {"value": "heron", "status": "observed"}
        store.save_draft("a", rec)
        res = editing.save(store, "a", {"title": "Grey Patience"}, CTX)
        self.assertEqual(res["copy"]["title"], "Grey Patience")
        self.assertIn("subject_missing_from_title", [c["check"] for c in res["checks"]])
        res = editing.save(store, "a", {"title": "Patient Heron"}, CTX)
        self.assertNotIn("subject_missing_from_title", [c["check"] for c in res["checks"]])


if __name__ == "__main__":
    unittest.main()
