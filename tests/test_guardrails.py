"""Safety properties of the scaffold: no write path, no secrets, no dependency on the sibling repo."""
import re
import unittest

from tests._helpers import AGENTS, PLUGIN, REPO, SKILLS, frontmatter, load_json, read, repo_files

# Folders that must never reference the sibling repository (AC-01).
INDEPENDENT_DIRS = ["plugins", "apps", "services", "packages", "database", "resources", ".cursor", "tests"]
# Tools no agent may hold in Phase 0a: shell, network, or any MCP server.
FORBIDDEN_TOOLS = re.compile(r"\b(Bash|WebFetch|WebSearch|mcp__\w+)\b")
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"sb_secret_[A-Za-z0-9]{10,}"),
]
# These two files name the sibling repo on purpose: one to forbid it, one to plant it as a mutant.
SELF_REFERENCING = {"test_guardrails.py", "mutants.py"}
FAKE_VALUE = re.compile(r"fake|localhost|^\./|^(true|false|development|test)$", re.I)


class NoWritePath(unittest.TestCase):
    def test_plugin_ships_no_mcp_servers(self):
        self.assertFalse((PLUGIN / ".mcp.json").exists(), "no MCP servers in Phase 0a")
        self.assertNotIn("mcpServers", load_json(PLUGIN / ".claude-plugin" / "plugin.json"))

    def test_agents_hold_no_shell_network_or_mcp_tools(self):
        for f in AGENTS.glob("*.md"):
            tools = frontmatter(f).get("tools", "")
            self.assertNotRegex(tools, FORBIDDEN_TOOLS, f"{f.stem} holds a forbidden tool")

    def test_every_agent_loads_the_commerce_context(self):
        for f in AGENTS.glob("*.md"):
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/shared/COMMERCE-CONTEXT.md", read(f), f.stem)

    def test_every_skill_has_forbidden_actions_content(self):
        for d in SKILLS.iterdir():
            if d.is_dir():
                text = read(d / "SKILL.md")
                section = text.split("## Forbidden actions", 1)[1].split("\n## ", 1)[0]
                self.assertGreaterEqual(section.count("\n- "), 2, f"{d.name}: forbidden actions too thin")

    def test_publish_command_is_not_approval(self):
        text = read(PLUGIN / "commands" / "publish.md")
        self.assertIn("not approval", text)
        self.assertIn("Gate 4", text)


class NoSecrets(unittest.TestCase):
    def test_no_secret_patterns_anywhere(self):
        hits = []
        for p in repo_files():
            try:
                text = read(p)
            except UnicodeDecodeError:
                continue
            for pat in SECRET_PATTERNS:
                if pat.search(text):
                    hits.append(f"{p.relative_to(REPO)}: {pat.pattern}")
        self.assertEqual(hits, [], "possible secrets:\n" + "\n".join(hits))

    def test_env_example_values_are_fake(self):
        for line in read(REPO / ".env.example").splitlines():
            if line.strip() and not line.startswith("#"):
                key, value = line.split("=", 1)
                self.assertRegex(value, FAKE_VALUE, f".env.example: {key} does not look fake")

    def test_real_env_is_ignored(self):
        self.assertRegex(read(REPO / ".gitignore"), r"(?m)^\.env$")


def real_storefront_names():
    """Real names from the gitignored discovery index, so the test itself never contains them."""
    index = REPO / "discovery" / "raw" / "README.md"
    if not index.exists():
        return []
    return [m.group(1).strip() for m in re.finditer(r"^\| Storefront [A-Z] \| ([^|]+) \|", read(index), re.M)]


class NoRealNames(unittest.TestCase):
    def test_tracked_files_never_name_a_real_storefront(self):
        names = real_storefront_names()
        if not names:
            self.skipTest("no discovery index on this machine")
        ignored = ("discovery/raw/", "config/mappings/", "config/storefronts.local.json")
        hits = []
        for p in repo_files():
            rel = str(p.relative_to(REPO))
            if rel.startswith(ignored) or ".local." in p.name:
                continue
            try:
                text = read(p).lower()
            except UnicodeDecodeError:
                continue
            for n in names:
                if n.lower() in text or n.lower().replace(" ", "") in text:
                    hits.append(f"{rel}: {n[0]}…")
        self.assertEqual(hits, [], "real storefront names in tracked files:\n" + "\n".join(hits))


class Independence(unittest.TestCase):
    def test_no_reference_to_the_sibling_repo(self):
        hits = []
        for p in repo_files():
            if p.relative_to(REPO).parts[0] not in INDEPENDENT_DIRS or p.name in SELF_REFERENCING:
                continue
            try:
                if "zaidyn" in read(p).lower():
                    hits.append(str(p.relative_to(REPO)))
            except UnicodeDecodeError:
                continue  # binary fixtures (images) can't carry a path reference we'd act on
        self.assertEqual(hits, [], "sibling-repo references found:\n" + "\n".join(hits))

    def test_no_relative_path_out_of_the_repo(self):
        hits = [str(p.relative_to(REPO)) for p in repo_files()
                if p.suffix in {".md", ".json", ".mdc", ".py", ".sh"} and p.name not in SELF_REFERENCING
                and "../zaidyn" in read(p)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
