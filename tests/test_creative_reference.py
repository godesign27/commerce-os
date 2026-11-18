"""A storefront's creative reference (B-086): the owner's own document on reading, naming and voicing the work,
kept privately beside the brand context and read into the prompt. All data is invented."""
import unittest

from packages.drafting import brand, listing, service
from tests._helpers import REPO, read
from tests.test_drafting import CTX, TAGS, TYPES, draft
from tests.test_listing_copy import tmp

REFERENCE = "# Example reference\n\nRead each piece as a held breath. Example: *Quiet Field* (title for that work only)."


def system_text(**kw):
    req = listing.build_request(b"\xff\xd8jpeg", "image/jpeg", TYPES, TAGS, brand_ctx=CTX, **kw)
    return "\n".join(b["text"] for b in req["system"]), req


class Reading(unittest.TestCase):
    def test_it_is_read_from_beside_the_brand_context(self):
        root = tmp()
        self.assertEqual(brand.reference_text("storefront-x", root), "", "none until the owner adds one")
        brand.reference_path("storefront-x", root).write_text("  " + REFERENCE + "\n\n")
        self.assertEqual(brand.reference_text("storefront-x", root), REFERENCE)
        self.assertEqual(brand.reference_text("storefront-y", root), "", "each storefront has its own")

    def test_it_stays_private(self):
        self.assertIn("config/brand/*.local.md", read(REPO / ".gitignore").splitlines())
        self.assertTrue(brand.reference_path("storefront-a").name.endswith(".local.md"))


class Prompt(unittest.TestCase):
    def test_it_goes_in_with_the_brand_context_below_the_rules(self):
        text, req = system_text(reference=REFERENCE)
        self.assertIn(REFERENCE, text)
        self.assertIn("This request's output format, evidence rules, lengths and rubric come first", text)
        self.assertIn("never treat a meaning it gives for one work as confirmed for another", text)
        brand_block = req["system"][-1]
        self.assertIn(REFERENCE, brand_block["text"], "in the cached brand block, the same for a whole batch")
        self.assertIn("cache_control", brand_block)

    def test_without_one_the_prompt_is_as_before(self):
        text, _ = system_text()
        self.assertNotIn("CREATIVE REFERENCE", text)

    def test_the_draft_records_which_version_it_followed(self):
        d = draft(reference=REFERENCE)
        self.assertEqual(d["policy_versions"]["brand_reference"], brand.reference_version(REFERENCE))
        self.assertNotEqual(brand.reference_version(REFERENCE), brand.reference_version(REFERENCE + " edited"))
        plain = draft()
        self.assertNotIn("brand_reference", plain["policy_versions"])

    def test_drafting_passes_it_through(self):
        self.assertIn("reference=reference", read(REPO / "packages/drafting/service.py"))
        self.assertIn("reference=brand.reference_text(self.storefront, self.brand_root)",
                      read(REPO / "services/local_api/server.py"))
        self.assertIn("reference=brand.reference_text(args.storefront)", read(REPO / "scripts/draft_listings.py"))
        self.assertTrue(callable(service.draft_item))


class NoStorefrontInCode(unittest.TestCase):
    def test_no_artist_or_storefront_is_named_in_the_drafting_code_or_skill(self):
        """Voice belongs in the storefront's own files, never in shipped code: no name checks, no one artist's guide."""
        skill = REPO / "plugins/commerce-os/skills/listing-copy"
        refs = sorted(p.name for p in (skill / "references").glob("*.md"))
        self.assertEqual(refs, ["rubric.md", "writing-standards.md"])
        for src in (read(REPO / "packages/drafting/listing.py"), read(skill / "SKILL.md")):
            self.assertNotIn('identity"]["name"].strip().casefold() ==', src)


if __name__ == "__main__":
    unittest.main()
