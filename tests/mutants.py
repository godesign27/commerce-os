#!/usr/bin/env python3
"""Reintroduce each known defect in a throwaway copy and confirm the suite catches it."""
import shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
P = "plugins/commerce-os"

# (description, file, find, replace, test module that must fail)
MUTANTS = [
 ("manifest versions drift", ".claude-plugin/marketplace.json",
  '"version": "0.3.0"', '"version": "0.0.9"', "tests.test_manifests"),
 ("an agent gains a shell", f"{P}/agents/catalog-draft.md",
  "tools: Read, Grep, Glob, Write", "tools: Read, Grep, Glob, Write, Bash", "tests.test_guardrails"),
 ("an agent gains a storefront MCP tool", f"{P}/agents/review-publishing.md",
  "tools: Read, Grep, Glob, Write", "tools: Read, Write, mcp__supabase__execute_sql", "tests.test_guardrails"),
 ("plugin starts shipping MCP servers", f"{P}/.claude-plugin/plugin.json",
  '"license": "UNLICENSED"', '"license": "UNLICENSED", "mcpServers": "./.mcp.json"', "tests.test_guardrails"),
 ("sibling repo referenced from a skill", f"{P}/skills/publishing/SKILL.md",
  "# Publishing\n", "# Publishing\n\nSee ../zaidyn-pm-os for the publish flow.\n", "tests.test_guardrails"),
 ("real-looking secret in .env.example", ".env.example",
  "OPS_DB_URL=postgresql://ops_user:fake-password@localhost:54322/commerce_os_dev", "OPS_DB_URL=s3cr3t-value", "tests.test_guardrails"),
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
  "| Operational database | `~~ops-db` | Separate Commerce OS database; provider set in config | None directly | Not built |",
  "| Operational database | `~~ops-db` | Separate Commerce OS database; provider set in config | Not built |", "tests.test_markdown"),
 ("broken relative link", f"{P}/skills/review-packaging/SKILL.md",
  "(../../shared/templates/review-package.md)", "(../../shared/templates/review.md)", "tests.test_markdown"),
 ("operational DB prefix doubles the suffix", "config/storefronts.example.json",
  '"env_prefix": "OPS"', '"env_prefix": "OPS_DB"', "tests.test_providers"),
 ("new storefront defaults to writes enabled", "config/storefronts.example.json",
  '"writes_enabled": false\n    },\n    {', '"writes_enabled": true\n    },\n    {', "tests.test_providers"),
 ("hidden status that isn't a real status", "resources/catalog-profiles/replit-artstore-v1.json",
  '"hidden_on_create": "draft"', '"hidden_on_create": "hidden"', "tests.test_providers"),
 ("provider missing from the connections doc", "docs/storefront-connections.md",
  "| `supabase` |", "| supabase |", "tests.test_providers"),
 ("setup skill routed to a specialist", "plugins/commerce-os/agents/catalog-draft.md",
  "## Boundaries", "Also `${CLAUDE_PLUGIN_ROOT}/skills/storefront-setup/SKILL.md`.\n\n## Boundaries", "tests.test_frontmatter"),
 ("artwork gains a color option", "resources/product-types/artwork.json",
  '"color": "not_applicable"', '"color": "allowed"', "tests.test_mappings"),
 ("product type README drifts from files", "resources/product-types/README.md",
  "| `sunglasses` | tangible | allowed | not_applicable |", "| `sunglasses` | tangible | allowed | supplied_only |", "tests.test_mappings"),
 ("example mapping references a missing category", "config/mappings/storefront.example.json",
  '"category": "goods"', '"category": "gadgets"', "tests.test_mappings"),
 ("mapping edit skips its change record", "config/mappings/storefront.example.json",
  '"version": 2,', '"version": 3,', "tests.test_mappings"),
 ("catalog-mappings loses its Forbidden actions section", "plugins/commerce-os/skills/catalog-mappings/SKILL.md",
  "## Forbidden actions", "## Notes", "tests.test_frontmatter"),
 ("merged entry points at a missing key", "config/mappings/storefront.example.json",
  '"merged_into": "widget"', '"merged_into": "gadget"', "tests.test_mappings"),
 ("read-role check lets customer tables through", "scripts/check_read_role.py",
  "if t not in ALLOWED and p.get(\"SELECT\")", "if t not in ALLOWED and p.get(\"SELECT\") and t != \"users\"", "tests.test_check_read_role"),
 ("read-role check stops forcing read-only sessions", "scripts/check_read_role.py",
  '"-c default_transaction_read_only=on -c statement_timeout=15000"', '"-c statement_timeout=15000"', "tests.test_check_read_role"),
 ("commercial facts may be inferred", "packages/contracts/schemas/common.schema.json",
  '"enum": ["supplied", "verified_catalog", "human_confirmed", "unknown", "conflicting"]',
  '"enum": ["supplied", "verified_catalog", "human_confirmed", "unknown", "conflicting", "inferred"]', "tests.test_contracts"),
 ("unknown facts may carry a value", "packages/contracts/schemas/common.schema.json",
  '"then": {"properties": {"value": {"type": "null"}}}', '"then": {}', "tests.test_contracts"),
 ("an agent may approve", "packages/contracts/schemas/approval.schema.json",
  '"const": "human"', '"enum": ["human", "agent"]', "tests.test_contracts"),
 ("create stops requiring must_not_exist", "packages/contracts/schemas/change-set.schema.json",
  '"must_not_exist"\n', '"key"\n', "tests.test_contracts"),
 ("validator ignores additionalProperties", "tests/_jsonschema.py",
  'elif "additionalProperties" in s:', 'elif False:', "tests.test_contracts"),
 ("semantic check forgets the color rule", "tests/test_contracts.py",
  'if "color" in defs and color_rule != "allowed":', 'if False:', "tests.test_contracts"),
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
