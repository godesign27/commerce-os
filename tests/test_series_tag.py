"""The owner's series adds the store tag it names (B-091): a series of "Animal" puts the piece under the store's
Animal tag. A series that isn't a tag adds nothing. All data is invented."""
import unittest

from packages.adapters import artstore_map as am
from tests._helpers import REPO, read
from tests.test_storefront_preview import MAPPING, approved_entry, build

CALM = am.test_id("tag", "calm")
BOLD = am.test_id("tag", "bold")


def tags(series):
    cs, _ = build(entry=dict(approved_entry(), series=series))
    return cs["operations"][0]["fields"]["tags"]["value"]


class SeriesTag(unittest.TestCase):
    def test_a_series_that_names_a_tag_adds_it(self):
        self.assertEqual(tags("Calm"), [BOLD, CALM], "after the copy's own tags")

    def test_capitals_spaces_and_a_plural_still_match(self):
        for series in ("calm", "  CALM ", "Calms"):
            self.assertEqual(tags(series), [BOLD, CALM], series)

    def test_never_twice(self):
        self.assertEqual(tags("Bold"), [BOLD], "the copy already has it")

    def test_a_series_that_is_not_a_tag_adds_nothing(self):
        for series in ("Nautical 1", "", None, "Abastract"):
            self.assertEqual(tags(series), [BOLD], series)
        cs, _ = build(entry=dict(approved_entry(), series="Nautical 1"))
        self.assertEqual([b for b in cs["blockers"] if b["target"] == "product.tags"], [], "and doesn't warn")

    def test_it_is_the_mapping_s_tags_that_count(self):
        self.assertIn({"key": "calm", "name": {"production": "Calm"}, "slug": "calm", "status": "in_scope"}, MAPPING["tags"])
        self.assertIn("series_tag = _series_tag(entry.get(\"series\"), store)", read(REPO / "packages/adapters/artstore_map.py"))


if __name__ == "__main__":
    unittest.main()
