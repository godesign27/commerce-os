"""Saving the owner's own copy one field at a time (B-059): the store, the shared editing module, the local
API's per-section save, the /listing-edit script, and the skill's wiring. No network, no model."""
import io
import importlib.util
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from packages.drafting import editing
from packages.drafting.store import LockedError, Store
from tests._helpers import REPO, read
from tests.test_drafting import CTX
from tests.test_listing_copy import load_server, record_for, tmp


def load_script():
    spec = importlib.util.spec_from_file_location("listing_edit", REPO / "scripts" / "listing_edit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SetFields(unittest.TestCase):
    def setUp(self):
        self.store = Store(tmp())
        self.store.save_draft("a", record_for("a"))

    def test_only_the_named_field_changes(self):
        self.store.set_fields("a", {"short_description": "Mine, short."})
        self.store.set_fields("a", {"title": "The Heron's Gaze"})
        eff = self.store.effective("a")
        self.assertEqual(eff["short_description"], "Mine, short.", "saving the title kept the short description")
        self.assertEqual(eff["title"], "The Heron's Gaze")
        self.assertEqual(eff["collector_description"], Store.proposed(self.store.draft("a"))["collector_description"])

    def test_none_reverts_and_the_draft_value_is_no_edit(self):
        self.store.set_fields("a", {"short_description": "Mine."})
        self.store.set_fields("a", {"short_description": None})
        self.assertNotIn("edits", self.store.listing("a"))
        proposed = Store.proposed(self.store.draft("a"))
        self.store.set_fields("a", {"title": proposed["title"]})
        self.assertNotIn("edits", self.store.listing("a"), "saving the draft's own text is not an edit")

    def test_a_saved_title_replaces_the_chosen_option(self):
        self.store.update("a", chosen_title="Grey Patience")
        self.store.set_fields("a", {"title": "One Leg Down"})
        self.assertNotIn("chosen_title", self.store.listing("a"))
        self.assertEqual(self.store.effective("a")["title"], "One Leg Down")

    def test_refusals(self):
        with self.assertRaises(ValueError):
            self.store.set_fields("a", {"title": "  "})
        with self.assertRaises(ValueError):
            self.store.set_fields("a", {"price": "10"})
        with self.assertRaises(ValueError):
            self.store.set_fields("a", {"store_tags": "Animals"})
        with self.assertRaises(ValueError):
            self.store.set_fields("missing", {"title": "X"})
        self.store.approve("a", "owner")
        with self.assertRaises(LockedError):
            self.store.set_fields("a", {"title": "After approval"})


class Editing(unittest.TestCase):
    def setUp(self):
        self.store = Store(tmp())
        for i in ("heron-1", "heron-2", "fox-1"):
            self.store.save_draft(i, record_for(i))
        self.items = [{"id": "heron-1", "source": "Heron one.jpg"}, {"id": "heron-2", "source": "Heron two.jpg"},
                      {"id": "fox-1", "source": "Fox.jpg"}, {"id": "undrafted", "source": "Wolf.jpg"}]

    def test_field_names(self):
        self.assertEqual(editing.field_name("Short"), "short_description")
        self.assertEqual(editing.field_name("long-description"), "collector_description")
        self.assertEqual(editing.field_name("tags"), "store_tags")
        with self.assertRaises(ValueError):
            editing.field_name("price")

    def test_finding_listings(self):
        self.assertEqual(editing.find_items(self.items, self.store, "fox"), ["fox-1"])
        self.assertEqual(editing.find_items(self.items, self.store, "HERON-2"), ["heron-2"])
        self.assertEqual(len(editing.find_items(self.items, self.store, "heron")), 2)
        self.assertEqual(editing.find_items(self.items, self.store, "wolf"), [], "only drafted listings can be edited")
        self.store.set_fields("fox-1", {"title": "Russet Hour"})
        self.assertEqual(editing.find_items(self.items, self.store, "russet"), ["fox-1"], "matches the current title")

    def test_checks_run_on_what_was_saved_but_never_block_the_save(self):
        res = editing.save(self.store, "fox-1", {"short": "An acrylic fox at dusk."}, CTX)
        self.assertEqual(res["copy"]["short_description"], "An acrylic fox at dusk.")
        self.assertIn("unsupported_claim", [c["check"] for c in res["checks"] if c["severity"] == "blocking"])
        self.store.update("fox-1", facts={"medium": "acrylic on canvas"})
        res = editing.save(self.store, "fox-1", {"short": "An acrylic fox at dusk, again."}, CTX)
        self.assertNotIn("unsupported_claim", [c["check"] for c in res["checks"]])
        self.store.set_fields("heron-1", {"title": "Russet Hour"})
        res = editing.save(self.store, "fox-1", {"title": "Russet Hour"}, CTX)
        self.assertEqual([c["check"] for c in res["checks"] if c["severity"] == "blocking"], ["duplicate_title"])
        self.assertEqual(res["copy"]["title"], "Russet Hour", "the owner's choice is saved and flagged, not refused")

    def test_title_checks_only_when_the_title_changed(self):
        self.store.set_fields("heron-1", {"title": "Same"})
        self.store.set_fields("fox-1", {"title": "Same"})
        res = editing.save(self.store, "fox-1", {"keywords": ["fox"]}, CTX)
        self.assertEqual(res["checks"], [])


class Api(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        out = tmp() / "review"
        out.mkdir()
        (out / "items.json").write_text(json.dumps([{"id": "a", "source": "a.jpg", "kind": "artwork"}]))
        self.app = self.srv.App(out=out, brand_root=out / "brand", learning_root=out / "learning",
                                config=out / "none.json")
        self.app.store.save_draft("a", record_for("a"))

    def test_save_one_section(self):
        res = self.app.save_copy("a", {"fields": {"store_tags": ["Animals", " Birds "]}})
        self.assertEqual(res["copy"]["store_tags"], ["Animals", "Birds"])
        self.assertEqual(res["saved"], ["store_tags"])
        res = self.app.save_copy("a", {"fields": {"store_tags": None}})
        self.assertNotIn("edits", self.app.store.listing("a"))

    def test_bad_requests_and_the_lock(self):
        for bad in ({}, {"fields": "x"}, {"fields": {}}, {"fields": {"price": 1}}, {"fields": {"title": "x"}, "more": 1}):
            with self.assertRaises(self.srv.ApiError, msg=bad) as e:
                self.app.save_copy("a", bad)
            self.assertEqual(e.exception.code, 400)
        self.app.store.approve("a", "owner")
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.save_copy("a", {"fields": {"title": "Late"}})
        self.assertEqual(e.exception.code, 409)

    def test_route_exists(self):
        self.assertIn(("PUT", r"^/api/items/([\w.-]+)/copy$"), [(m, p.pattern) for m, p, _ in self.srv.ROUTES])


class Script(unittest.TestCase):
    def setUp(self):
        self.mod = load_script()
        self.out = tmp() / "review"
        self.out.mkdir()
        (self.out / "items.json").write_text(json.dumps([{"id": "wolf-1", "source": "Wolf.jpg"},
                                                         {"id": "heron-1", "source": "Heron.jpg"},
                                                         {"id": "heron-2", "source": "Heron 2.jpg"}]))
        self.store = Store(self.out)
        for i in ("wolf-1", "heron-1", "heron-2"):
            self.store.save_draft(i, record_for(i))

    def run_cli(self, *argv, stdin=""):
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            code = self.mod.main(list(argv), out=self.out, brand_root=self.out / "brand", stdin=io.StringIO(stdin))
        return code, o.getvalue(), e.getvalue()

    def test_set_saves_the_exact_text(self):
        text = 'The wolf doesn\'t blink. "Hold steady," it says.'
        code, out, _ = self.run_cli("set", "wolf", "collector", "--file", "-", stdin=text + "\n")
        self.assertEqual(code, 0)
        self.assertEqual(self.store.effective("wolf-1")["collector_description"], text)
        self.assertIn("Saved collector description", out)
        code, _, _ = self.run_cli("set", "wolf", "title", "The Wolf's Gaze")
        self.assertEqual(self.store.effective("wolf-1")["title"], "The Wolf's Gaze")
        self.run_cli("set", "wolf", "tags", "Animals, Bold")
        self.assertEqual(self.store.effective("wolf-1")["store_tags"], ["Animals", "Bold"])

    def test_choose_and_revert(self):
        self.assertEqual(self.run_cli("choose", "wolf", "2")[0], 0)
        self.assertEqual(self.store.effective("wolf-1")["title"], "Grey Patience")
        self.assertEqual(self.run_cli("choose", "wolf", "9")[0], 1)
        self.run_cli("set", "wolf", "short", "Mine.")
        self.assertEqual(self.run_cli("revert", "wolf", "all")[0], 0)
        self.assertNotIn("edits", self.store.listing("wolf-1"))

    def test_ambiguous_missing_and_locked(self):
        code, _, err = self.run_cli("set", "heron", "title", "X")
        self.assertEqual(code, 2)
        self.assertIn("heron-1", err)
        self.assertNotIn("edits", self.store.listing("heron-1"), "never guesses between listings")
        self.assertEqual(self.run_cli("show", "zebra")[0], 2)
        self.store.approve("wolf-1", "owner")
        code, _, err = self.run_cli("set", "wolf", "title", "Late")
        self.assertEqual(code, 1)
        self.assertIn("Unlock it on the dashboard", err)

    def test_show(self):
        self.run_cli("set", "wolf", "short", "Mine.")
        code, out, _ = self.run_cli("show", "wolf-1")
        self.assertEqual(code, 0)
        self.assertIn("Short description  [your edit]", out)
        self.assertIn("2. Grey Patience", out)


class Wiring(unittest.TestCase):
    SKILL = REPO / "plugins" / "commerce-os" / "skills" / "listing-edit" / "SKILL.md"

    def test_the_skill_saves_words_as_given_and_only_through_the_script(self):
        text = read(self.SKILL)
        self.assertIn("never rewrites", text)
        self.assertIn("scripts/listing_edit.py", text)
        self.assertIn("No Write\nor Edit", text)
        for forbidden in ("Unlocking approved copy", "Guessing between several matching listings", "Publishing"):
            self.assertIn(forbidden, text)

    def test_the_dashboard_saves_per_section(self):
        page = read(REPO / "apps" / "review-dashboard" / "src" / "pages" / "ListingDetail.tsx")
        self.assertIn("api.saveCopy", page)
        self.assertNotIn("setTimeout", page, "no autosave: each section has its own Save button")
        self.assertIn("Other", page)
        self.assertIn("beforeunload", page)

    def test_setup_and_artist_context_live_in_the_account_menu(self):
        main = read(REPO / "apps" / "review-dashboard" / "src" / "main.tsx")
        self.assertIn('const nav = [["photos", "Photos"], ["rooms", "Rooms"], ["listings", "Listings"], ["learning", "Learning"]];', main)
        self.assertIn('["setup", "Setup"]];', main)
        self.assertIn('aria-haspopup="menu"', main)

    def test_listing_layout(self):
        page = read(REPO / "apps" / "review-dashboard" / "src" / "pages" / "ListingDetail.tsx")
        left = page[page.index('<section className="art">'):page.index('<section className="copy">')]
        self.assertIn("<AboutPiece", left, "series, edition, medium and size sit under the image")
        self.assertIn("<ReviewTabs", left, "checks and evidence are tabs under the image")
        right = page[page.index('<section className="copy">'):]
        self.assertIn("<MeaningPanel d={d} questions={dr.ask_artist}", right, "the artist's questions sit with the meaning")
        self.assertIn('role="tablist"', page)


if __name__ == "__main__":
    unittest.main()
