"""Rules that live in more than one file haven't drifted from the PRD or from each other."""
import re
import unittest

from tests._helpers import PLUGIN, REPO, SHARED, SKILL_OWNERS, read


def prd_section(number: str) -> str:
    prd = read(REPO / "PRD.md")
    m = re.search(rf"^##+ {re.escape(number)}\b.*?(?=^##+ \d)", prd, re.M | re.S)
    assert m, f"PRD section {number} not found"
    return m.group(0)


def backticked(text: str) -> set:
    return set(re.findall(r"`([A-Z_]{3,}|[a-z_]{3,})`", text))


class PolicyMatchesPrd(unittest.TestCase):
    def test_evidence_statuses_match_prd_8_4(self):
        prd = backticked(prd_section("8.4"))
        table = read(SHARED / "evidence-policy.md").split("## Statuses", 1)[1].split("## Rules", 1)[0]
        policy = set(re.findall(r"^\| `(\w+)` \|", table, re.M))
        self.assertEqual(policy, prd, "evidence-policy statuses drifted from PRD §8.4")

    def test_workflow_states_match_prd_14(self):
        prd = set(re.findall(r"\b[A-Z][A-Z_]{4,}\b", prd_section("14")))
        workflow = set(re.findall(r"\b[A-Z][A-Z_]{4,}\b", read(SHARED / "WORKFLOW.md")))
        self.assertEqual(prd - workflow, set(), "WORKFLOW.md is missing PRD §14 states")
        self.assertEqual(workflow - prd, set(), "WORKFLOW.md has states the PRD doesn't define")

    def test_four_gates(self):
        gates = re.findall(r"^\| (\d)\. ", read(SHARED / "WORKFLOW.md"), re.M)
        self.assertEqual(gates, ["1", "2", "3", "4"])

    def test_prd_skill_list_matches_owners(self):
        prd = set(re.findall(r"^- `([a-z-]+)`:", prd_section("6.1"), re.M))
        self.assertEqual(prd, set(SKILL_OWNERS))


class DocsMatchFiles(unittest.TestCase):
    def test_plugin_readme_agent_table_matches_owners(self):
        readme = read(PLUGIN / "README.md")
        for skill, owner in SKILL_OWNERS.items():
            row = re.search(rf"^\| `{owner}` \|(.+)\|$", readme, re.M)
            self.assertIsNotNone(row, f"README has no row for {owner}")
            self.assertIn(skill, row.group(1), f"README row for {owner} omits {skill}")

    def test_commercial_fact_list_is_the_same_in_context_and_agents_md(self):
        """The commercial-fact list in AGENTS.md must not lose an item the evidence policy has."""
        policy = read(SHARED / "evidence-policy.md").lower()
        agents = read(REPO / "AGENTS.md").lower()
        for fact in ["price", "stock", "dimensions", "material", "brand", "sku", "gtin", "tax",
                     "shipping", "certification", "rights"]:
            self.assertIn(fact, policy, f"evidence-policy lost '{fact}'")
            self.assertIn(fact, agents, f"AGENTS.md lost '{fact}'")

    def test_pointer_files_point_at_the_canonical_policies(self):
        for f in [REPO / "AGENTS.md", REPO / ".cursor" / "rules" / "commerce-os.mdc"]:
            text = read(f)
            for name in ["COMMERCE-CONTEXT.md", "evidence-policy.md", "WORKFLOW.md"]:
                self.assertIn(f"plugins/commerce-os/shared/{name}", text, f"{f.name} lost pointer to {name}")
        self.assertIn("AGENTS.md", read(REPO / "CLAUDE.md"))


if __name__ == "__main__":
    unittest.main()
