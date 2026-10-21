#!/usr/bin/env python3
"""Reintroduce each known defect in a throwaway copy and confirm the suite catches it."""
import shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
P = "plugins/commerce-os"

# (description, file, find, replace, test module that must fail)
MUTANTS = [
 ("manifest versions drift", ".claude-plugin/marketplace.json",
  '"version": "0.1.0"', '"version": "0.0.9"', "tests.test_manifests"),
 ("an agent gains a shell", f"{P}/agents/catalog-draft.md",
  "tools: Read, Grep, Glob, Write", "tools: Read, Grep, Glob, Write, Bash", "tests.test_guardrails"),
 ("an agent gains a storefront MCP tool", f"{P}/agents/review-publishing.md",
  "tools: Read, Grep, Glob, Write", "tools: Read, Write, mcp__supabase__execute_sql", "tests.test_guardrails"),
 ("plugin starts shipping MCP servers", f"{P}/.claude-plugin/plugin.json",
  '"license": "UNLICENSED"', '"license": "UNLICENSED", "mcpServers": "./.mcp.json"', "tests.test_guardrails"),
 ("sibling repo referenced from a skill", f"{P}/skills/publishing/SKILL.md",
  "# Publishing\n", "# Publishing\n\nSee ../zaidyn-pm-os for the publish flow.\n", "tests.test_guardrails"),
 ("real-looking secret in .env.example", ".env.example",
  "OPS_DB_SERVICE_ROLE_KEY=fake-ops-service-role-key", "OPS_DB_SERVICE_ROLE_KEY=s3cr3t-value", "tests.test_guardrails"),
 ("publish command stops saying it isn't approval", f"{P}/commands/publish.md",
  "Running this command is not approval", "Running this command approves the change set", "tests.test_guardrails"),
 ("skill loses its Forbidden actions section", f"{P}/skills/catalog-retrieval/SKILL.md",
  "## Forbidden actions", "## Notes", "tests.test_frontmatter"),
 ("skill routed by the wrong specialist", f"{P}/agents/catalog-draft.md",
  "`${CLAUDE_PLUGIN_ROOT}/skills/destination-mapping/SKILL.md`",
  "`${CLAUDE_PLUGIN_ROOT}/skills/destination-mapping/SKILL.md` and `${CLAUDE_PLUGIN_ROOT}/skills/publishing/SKILL.md`",
  "tests.test_frontmatter"),
 ("bare skills/ path in a command", f"{P}/commands/review.md",
  "`${CLAUDE_PLUGIN_ROOT}/skills/", "`skills/", "tests.test_frontmatter"),
 ("evidence status dropped from the policy", f"{P}/shared/evidence-policy.md",
  "| `conflicting` | Two or more sources disagree. | No. Creates a blocking issue. |\n", "", "tests.test_consistency"),
 ("workflow loses OUTCOME_UNKNOWN", f"{P}/shared/WORKFLOW.md",
  "`FAILED` · `OUTCOME_UNKNOWN` ·", "`FAILED` ·", "tests.test_consistency"),
 ("AGENTS.md drops a commercial fact", "AGENTS.md",
  "safety/certification and rights", "safety/certification", "tests.test_consistency"),
 ("table row loses a column", f"{P}/shared/CONNECTORS.md",
  "| Operational database | `~~ops-db` | Separate Commerce OS database | None directly | Not built |",
  "| Operational database | `~~ops-db` | Separate Commerce OS database | Not built |", "tests.test_markdown"),
 ("broken relative link", f"{P}/skills/review-packaging/SKILL.md",
  "(../../shared/templates/review-package.md)", "(../../shared/templates/review.md)", "tests.test_markdown"),
 ("PRD open question untracked", "BACKLOG.md",
  "| B-013 |", "| B-099 |", "tests.test_backlog"),
]


def run(module: str, root: Path) -> bool:
    r = subprocess.run([sys.executable, "-m", "unittest", module, "-q"], cwd=root,
                       capture_output=True, text=True)
    return r.returncode == 0


def main() -> int:
    survivors = 0
    for desc, rel, find, replace, module in MUTANTS:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            shutil.copytree(REPO, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            target = root / rel
            text = target.read_text(encoding="utf-8")
            if find not in text:
                print(f"✗ STALE  {desc}: pattern not found in {rel}")
                survivors += 1
                continue
            target.write_text(text.replace(find, replace, 1), encoding="utf-8")
            if run(module, root):
                print(f"✗ SURVIVED  {desc} ({module} still passes)")
                survivors += 1
            else:
                print(f"✓ caught  {desc}")
    print(f"\n{len(MUTANTS) - survivors}/{len(MUTANTS)} mutants caught")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
