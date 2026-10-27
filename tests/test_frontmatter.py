"""Skills, agents and commands: present, well-formed, and wired to each other."""
import re
import unittest

from tests._helpers import (ADMIN_SKILLS, AGENTS, COMMANDS, PLUGIN, ROUTER, SKILL_OWNERS, SKILL_SECTIONS, SKILLS,
                            SPECIALISTS, body, frontmatter, headings, read)

PLUGIN_ROOT_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)")


class Skills(unittest.TestCase):
    def test_exactly_the_prd_skills_exist(self):
        found = {d.name for d in SKILLS.iterdir() if d.is_dir()}
        self.assertEqual(found, set(SKILL_OWNERS) | ADMIN_SKILLS,
                         "skills/ must be the PRD §6.1 list plus the administrator skills")

    def test_skill_name_matches_folder_and_has_description(self):
        for d in SKILLS.iterdir():
            if d.is_dir():
                fm = frontmatter(d / "SKILL.md")
                self.assertEqual(fm.get("name"), d.name, d)
                self.assertTrue(fm.get("description"), f"{d.name}: empty description")

    def test_every_skill_has_the_required_sections_in_order(self):
        for d in SKILLS.iterdir():
            if d.is_dir():
                h = headings(d / "SKILL.md")
                present = [s for s in h if s in SKILL_SECTIONS]
                self.assertEqual(present, SKILL_SECTIONS, f"{d.name}: sections missing or out of order")

    def test_every_skill_links_the_commerce_context(self):
        for d in SKILLS.iterdir():
            if d.is_dir():
                self.assertIn("(../../shared/COMMERCE-CONTEXT.md)", read(d / "SKILL.md"), d.name)


class Agents(unittest.TestCase):
    def test_expected_agents_exist(self):
        found = {f.stem for f in AGENTS.glob("*.md")}
        self.assertEqual(found, set(SPECIALISTS) | {ROUTER})

    def test_agents_have_name_description_and_tools(self):
        for f in AGENTS.glob("*.md"):
            fm = frontmatter(f)
            self.assertEqual(fm.get("name"), f.stem, f)
            self.assertTrue(fm.get("description"), f)
            self.assertTrue(fm.get("tools"), f"{f.stem}: agents must declare an explicit tool list")

    def test_each_skill_is_routed_by_exactly_its_owner(self):
        for skill, owner in SKILL_OWNERS.items():
            ref = f"${{CLAUDE_PLUGIN_ROOT}}/skills/{skill}/SKILL.md"
            routed_by = [f.stem for f in AGENTS.glob("*.md") if ref in read(f)]
            self.assertEqual(routed_by, [owner], f"{skill} should be routed only by {owner}")

    def test_admin_skills_are_routed_by_no_agent_and_have_a_command(self):
        for skill in ADMIN_SKILLS:
            ref = f"${{CLAUDE_PLUGIN_ROOT}}/skills/{skill}/SKILL.md"
            self.assertEqual([f.stem for f in AGENTS.glob("*.md") if ref in read(f)], [],
                             f"{skill} is an administrator skill; no agent should route it")
            self.assertTrue(any(ref in read(c) for c in COMMANDS.glob("*.md")), f"no command runs {skill}")

    def test_router_table_covers_every_skill(self):
        text = read(AGENTS / f"{ROUTER}.md")
        for skill in set(SKILL_OWNERS) | ADMIN_SKILLS:
            self.assertRegex(text, rf"\b{re.escape(skill)}\b", f"{ROUTER} routing table omits {skill}")
        for spec in SPECIALISTS:
            self.assertIn(f"`{spec}`", text, f"{ROUTER} never dispatches {spec}")


class Commands(unittest.TestCase):
    def test_commands_have_description_and_no_name(self):
        for f in COMMANDS.glob("*.md"):
            fm = frontmatter(f)
            self.assertTrue(fm.get("description"), f)
            self.assertNotIn("name", fm, f)

    def test_commands_point_at_skills_via_plugin_root(self):
        for f in COMMANDS.glob("*.md"):
            text = body(f)
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/skills/", text, f"{f.name}: must use ${{CLAUDE_PLUGIN_ROOT}}/skills/")
            self.assertNotRegex(text, r"(?<![}/])`skills/", f"{f.name}: bare skills/ path")


class PluginRootPaths(unittest.TestCase):
    def test_every_plugin_root_path_exists(self):
        missing = []
        for f in PLUGIN.rglob("*.md"):
            for rel in PLUGIN_ROOT_PATH.findall(read(f)):
                if not (PLUGIN / rel).exists():
                    missing.append(f"{f.relative_to(PLUGIN)} → {rel}")
        self.assertEqual(missing, [], "dangling ${CLAUDE_PLUGIN_ROOT} paths:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
