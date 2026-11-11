"""Draft the pieces you tick on the Listings page (B-081). No model is called: drafting itself is stubbed."""
import json
import unittest

from tests._helpers import REPO, read
from tests.test_taskbar import make_app

PAGE = "apps/review-dashboard/src/pages/Listings.tsx"


class Api(unittest.TestCase):
    def setUp(self):
        self.app = make_app()                      # fox has a draft; owl doesn't
        items = json.loads((self.app.out / "items.json").read_text())
        for it in items:
            it["art_file"] = f"{it['id']}.png"         # both framed
        (self.app.out / "items.json").write_text(json.dumps(items))
        self.calls = []
        self.app.draft = lambda ids, label: self.calls.append((ids, label)) or {"job": "j"}

    def test_the_ticked_pieces_are_drafted_once_each(self):
        self.assertEqual(self.app.draft_selected({"ids": ["owl", "owl"]}), {"job": "j"})
        self.assertEqual(self.calls, [(["owl"], "Draft 1 selected piece(s)")])

    def test_only_pieces_not_drafted_yet(self):
        for body in ({"ids": ["fox"]}, {"ids": ["nope"]}, {"ids": []}, {"ids": "owl"}, {}, {"ids": [1]},
                     {"ids": ["owl"] * 61}):
            with self.assertRaises(Exception) as e:          # the server's ApiError, from its own module copy
                self.app.draft_selected(body)
            self.assertEqual(getattr(e.exception, "code", None), 400, body)
        self.assertEqual(self.calls, [], "nothing is drafted when the request is refused")

    def test_it_is_reachable(self):
        self.assertIn('@route("POST", "/api/draft-selected")', read(REPO / "services/local_api/server.py"))


class Page(unittest.TestCase):
    def test_undrafted_cards_can_be_ticked(self):
        src = read(REPO / PAGE)
        self.assertIn("{!i.drafted && (\n              <label className={`card-pick", src)
        self.assertIn("aria-label={`Draft ${i.source}`}", src)

    def test_the_button_drafts_what_is_ticked(self):
        src = read(REPO / PAGE)
        self.assertIn("onClick={() => draft(ticked)}>Draft {ticked.length} selected</button>", src)
        self.assertIn('draftSelected: (ids: string[]) => call<{ job: string }>("POST", "/api/draft-selected", { ids })',
                      read(REPO / "apps/review-dashboard/src/api.ts"))

    def test_the_page_says_how_to_start(self):
        self.assertIn("Tick the pieces you want drafted, then press Draft selected.", read(REPO / PAGE))


if __name__ == "__main__":
    unittest.main()
