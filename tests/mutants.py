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
 ("validator ignores additionalProperties", "packages/contracts/validator.py",
  'elif "additionalProperties" in s:', 'elif False:', "tests.test_contracts"),
 ("policy forgets the option rule", "packages/policy/semantics.py",
  "if rule not in OPTION_PERMITTED.get(key, set()):", "if False:", "tests.test_contracts"),
 ("approval gate skipped in the submission state machine", "database/operational/migrations/0003_state_machines.sql",
  "('IN_REVIEW', 'READY_FOR_APPROVAL'), ", "('IN_REVIEW', 'READY_FOR_APPROVAL'), ('IN_REVIEW', 'APPROVED'), ", "tests.test_operational_schema"),
 ("in-flight write made cancellable", "database/operational/migrations/0003_state_machines.sql",
  "('FAILED', 'CANCELLED');", "('FAILED', 'CANCELLED'), ('WRITING', 'CANCELLED');", "tests.test_operational_schema"),
 ("row-level security not forced on the owner", "database/operational/migrations/0009_tenant_isolation.sql",
  "EXECUTE format('ALTER TABLE commerce_os.%I FORCE ROW LEVEL SECURITY', t.table_name);", "", "tests.test_operational_schema"),
 ("commercial facts may be inferred in the database", "database/operational/migrations/0005_drafts.sql",
  "status IN ('supplied', 'verified_catalog', 'human_confirmed', 'unknown', 'conflicting'))",
  "status IN ('supplied', 'verified_catalog', 'human_confirmed', 'unknown', 'conflicting', 'inferred'))",
  "tests.test_operational_schema"),
 ("self-approval allowed", "database/operational/migrations/0007_review_and_approval.sql",
  "CONSTRAINT approvals_no_self_approval CHECK (actor_id <> prepared_by),", "", "tests.test_operational_schema"),
 ("audit trail made editable", "database/operational/migrations/0008_jobs_publication_audit.sql",
  "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE", "CREATE TRIGGER audit_events_append_only BEFORE DELETE", "tests.test_operational_schema"),
 ("live database test commits", "scripts/test_operational_db.py",
  'parts.append("ROLLBACK;")', 'parts.append("COMMIT;")', "tests.test_operational_schema"),
 ("read-role check accepts RLS with no policy", "scripts/check_read_role.py",
  'readable = any(p["cmd"] in ("SELECT", "ALL")', 'readable = True or any(p["cmd"] in ("SELECT", "ALL")', "tests.test_check_read_role"),
 ("smoke check accepts any error", "database/operational/tests/smoke.sql",
  "'a sealed change set is edited', 'is sealed');", "'a sealed change set is edited');", "tests.test_operational_schema"),
 ("local stand-in drifts from the recorded structure", "database/storefronts/storefront-a/schema.sql",
  "price numeric(10,2) NOT NULL,", "price numeric(12,2) NOT NULL,", "tests.test_local_storefront_db"),
 ("seed product relies on the status default", "database/storefronts/storefront-a/seed.json",
  '"sku": null, "status": "draft",', '"sku": null,', "tests.test_local_storefront_db"),
 ("drift check ignores changed defaults", "scripts/local_storefront_db.py",
  'for k in ("type", "not_null", "default"):', 'for k in ("type", "not_null"):', "tests.test_local_storefront_db"),
 ("runbook role script loses a catalog policy", "docs/runbooks/read-only-role.md",
  "CREATE POLICY commerce_os_read_catalog ON public.tags       FOR SELECT TO commerce_os_read USING (true);\n```",
  "```", "tests.test_local_storefront_db"),
 ("customer stand-in left without row-level security", "database/storefronts/storefront-a/schema.sql",
  "ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;\n", "", "tests.test_local_storefront_db"),
 ("fake storefront ignores the kill switch", "packages/adapters/fake.py",
  "        if not self.writes_enabled:\n", "        if False:\n", "tests.test_adapter_contract"),
 ("approval check skips the sealed hash", "packages/adapters/contract.py",
  "elif change_set_hash(change_set) != sealed:", "elif False:", "tests.test_adapter_contract"),
 ("approval check accepts an agent", "packages/adapters/contract.py",
  'if actor.get("kind") != "human" or actor.get("role") != "approver":', 'if actor.get("role") != "approver":',
  "tests.test_adapter_contract"),
 ("dry run writes to the destination", "packages/adapters/fake.py",
  "planned = self.plan(change_set, tables=copy.deepcopy(self.tables))", "planned = self.plan(change_set)\n"
  "        for p in planned:\n            if p[\"after\"]:\n                self.tables[p[\"table\"]][p[\"key\"]] = p[\"after\"]",
  "tests.test_adapter_contract"),
 ("multi-operation publish not atomic", "packages/adapters/fake.py",
  "        if failed or self._fail == \"before_write\":", "        for p in planned:\n            if p[\"after\"]:\n"
  "                self.tables[p[\"table\"]][p[\"key\"]] = p[\"after\"]\n        if failed or self._fail == \"before_write\":",
  "tests.test_adapter_contract"),
 ("create may rely on the status default", "packages/adapters/fake.py",
  'if status_rule.get("always_set_explicitly") and status_field not in fields:', "if False:",
  "tests.test_adapter_contract"),
 ("update skips its row-hash precondition", "packages/adapters/fake.py",
  'elif op["op"] == "update" and row_hash(before) != op["precondition"].get("expected_row_hash"):',
  "elif False:", "tests.test_adapter_contract"),
 ("reconcile claims success for missing rows", "packages/adapters/fake.py",
  'if results == {"match"}:', 'if "mismatch" not in results:', "tests.test_adapter_contract"),
 ("publish replays a different change set", "packages/adapters/fake.py",
  'if sealed != change_set.get("change_set_hash"):', "if False:", "tests.test_adapter_contract"),
 ("policy lets sizes onto types without sizes", "packages/policy/semantics.py",
  '"size": {"from_tiers", "supplied_only"},', '"size": {"from_tiers", "supplied_only", "not_applicable"},',
  "tests.test_policy"),
 ("policy accepts variants missing an option", "packages/policy/semantics.py",
  "for key in sorted(set(defs) - set(values)):", "for key in []:", "tests.test_policy"),
 ("policy binding list drops a field", "packages/policy/approvals.py",
  '"asset_manifest_hash", "mapping_version", "schema_fingerprint", "requested_status")',
  '"asset_manifest_hash", "schema_fingerprint", "requested_status")', "tests.test_policy"),
 ("policy skips the schema before semantics", "packages/policy/__init__.py",
  "    if errors:\n        return errors\n", "", "tests.test_policy"),
 ("policy accepts a document of the wrong contract", "packages/policy/__init__.py",
  "        if kind != expected:", "        if False:", "tests.test_policy"),
 ("adapter stops checking self-approval", "packages/policy/approvals.py",
  "    if prepared and prepared == approver:", "    if False:", "tests.test_adapter_contract"),
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
