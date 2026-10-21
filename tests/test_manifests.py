"""The plugin and marketplace manifests: valid, matched, and pointing at real things."""
import re
import unittest

from tests._helpers import PLUGIN, REPO, load_json, read, repo_files

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class Manifests(unittest.TestCase):
    def setUp(self):
        self.plugin = load_json(PLUGIN / ".claude-plugin" / "plugin.json")
        self.market = load_json(REPO / ".claude-plugin" / "marketplace.json")

    def test_plugin_has_required_fields(self):
        for key in ("name", "version", "description"):
            self.assertIn(key, self.plugin, f"plugin.json missing '{key}'")
        self.assertEqual(self.plugin["name"], "commerce-os")

    def test_versions_are_semver(self):
        self.assertRegex(self.plugin["version"], SEMVER)
        self.assertRegex(self.market["version"], SEMVER)

    def test_plugin_and_marketplace_versions_match(self):
        self.assertEqual(self.plugin["version"], self.market["version"],
                         "plugin.json and marketplace.json versions drifted — bump both together")

    def test_marketplace_lists_the_plugin_and_its_source_resolves(self):
        entries = {p["name"]: p for p in self.market.get("plugins", [])}
        self.assertIn("commerce-os", entries)
        src = (REPO / entries["commerce-os"]["source"]).resolve()
        self.assertEqual(src, PLUGIN.resolve(), "marketplace 'source' does not point at the plugin directory")

    def test_changelog_top_entry_matches_version(self):
        changelog = read(PLUGIN / "CHANGELOG.md")
        m = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
        self.assertIsNotNone(m, "CHANGELOG.md has no '## [x.y.z]' entry")
        self.assertEqual(m.group(1), self.plugin["version"],
                         "CHANGELOG's newest entry is not the current version")

    def test_every_json_file_parses(self):
        bad = []
        for p in repo_files({".json"}):
            try:
                load_json(p)
            except Exception as e:  # noqa: BLE001 — report every failure, not the first
                bad.append(f"{p.relative_to(REPO)}: {e}")
        self.assertEqual(bad, [], "invalid JSON:\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
