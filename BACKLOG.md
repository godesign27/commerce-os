# Backlog

Permanent `B-nnn` IDs. Never delete or reuse an ID. Statuses: `Open`, `In progress`, `Blocked`, `Done`.
Owner `Owner` means the product owner must decide; `Eng` means implementation work.

## Open decisions (PRD §22)

| ID | Item | Why | Owner | Status |
|---|---|---|---|---|
| B-001 | Storefront A and B names, schemas, product APIs, visibility fields, asset storage | Adapters, mappings and the schema proposal depend on the real schemas. Default: fake adapters, no writes. Schemas received 2026-10-21; visibility values and asset storage still open (B-024, B-025). | Owner | In progress |
| B-002 | Which Drive accounts/folders map to which storefront; can one product target both | Intake policy and destination suggestions. Default: reviewer selects destinations. | Owner | Open |
| B-003 | What signals a complete upload | Readiness rule for drive-intake. Proposed: product folder plus ready manifest. | Owner | Open |
| B-004 | Authoritative source for SKU, price, stock, sizes, dimensions, materials, rights | Without one, those fields stay unknown and block publication. | Owner | Open |
| B-005 | MVP categories and option vocabularies | Category templates and variant-grouping vocab. Start: artwork, hats, blankets. | Owner | Open |
| B-006 | Image sizes, crops, formats, background edits, storage policy per storefront | Image recipes and asset-validation limits. | Owner | Open |
| B-007 | Create-only first, or updates permitted | Scope of change sets and identity confirmation. Proposed: create-first. | Owner | Open |
| B-008 | Reviewer vs approver roles; is a second person required | Separation-of-duty policy for Gate 3. | Owner | Open |
| B-009 | Runtime, hosting, model provider, operational DB service, queue | Decided 2026-10-21: Python backend (workflow, workers, image pipeline, adapters) + TypeScript/React dashboard; operational DB in a new standalone project (Neon at the time; moved to Supabase, B-042). Still open: hosting, model provider, queue (proposed: Postgres-backed, no separate queue service) — B-041. | Owner | Done |
| B-010 | Daily volume, latency, cost, retention, recovery objectives | Instrument before committing targets. | Owner | Open |
| B-011 | Which live fields Commerce OS may own after publication | Default: never overwrite live fields without an approved operation. | Owner | Open |
| B-012 | Handling sold-out, deleted, renamed, or moved source products | Default: no automatic deletion or unpublication. | Owner | Open |
| B-013 | More organizations beyond these two sites | Isolation keys preserved now; broader multi-tenancy deferred. | Owner | Open |

## Phase 0

| ID | Item | Why | Owner | Status |
|---|---|---|---|---|
| B-014 | Phase 0a: repo and plugin scaffold (agents, skills, commands, policies, tests) | Reviewable structure before any runtime code. | Eng | Done |
| B-015 | Phase 0b: read-only inspection of Storefront A and B schemas | Schema proposal and mappings. Done from owner-supplied schema dumps; see docs/discovery/storefront-schemas.md. | Eng | Done |
| B-016 | Phase 0b: collect representative sample images per MVP category | Fixtures and the labeled evaluation corpus. | Owner | Open |
| B-017 | Phase 0b: verify current Google Drive push-notification and changes API docs | PRD §7.2 requires validating provider docs before choosing the mechanism. | Eng | Open |
| B-018 | Phase 0b: operational schema proposal and sample review package | Done: nine draft migrations (database/operational/), static checks, a rolled-back live smoke test; the sample review package is the contracts fixture. | Eng | Done |
| B-019 | Phase 0b: local fake storefront adapters | Lets Phase 1 run end to end without external systems. Done 2026-10-27: `packages/adapters/` (contract + `FakeStorefront`), with an interface-only contract suite that Phase 3 adapters must also pass. Storefront A only until B has a stand-in (B-045). | Eng | Done |

## Phase 1 and later

| ID | Item | Why | Owner | Status |
|---|---|---|---|---|
| B-020 | Machine-readable contracts (JSON Schema) for skill inputs/outputs in `packages/contracts/` | Done: nine schemas, valid fixtures for two scenarios, 21 schema and 6 semantic rejection cases. | Eng | Done |
| B-021 | Plugin eval suite (`claude plugin eval`) for no-invented-facts and prompt-injection cases | Structural tests cannot prove the model follows a skill. | Eng | Open |
| B-022 | Decide whether to bind commerce-lead as the default agent in `settings.json` | Currently opt-in via `claude --agent commerce-os:commerce-lead`. | Owner | Open |

## Phase 0b discovery findings (2026-10-21)

| ID | Item | Why | Owner | Status |
|---|---|---|---|---|
| B-023 | Confirm both storefronts run on Replit-managed Postgres (Neon), not Supabase | The dumps contradict PRD §1.1. Confirmed by both handoffs (Replit App Storage, Replit-managed databases). Led to the pluggable provider model (B-034). | Owner | Done |
| B-024 | JSONB shapes (`images`, `pricing_tiers`, `color_variants`, `tags`) and allowed `products.status` values per storefront | Answered by both owners' handoffs; recorded in docs/discovery/storefront-schemas.md. | Owner | Done |
| B-025 | Where each storefront's product images are stored, and whether Commerce OS may upload there | Both use Replit App Storage via an admin-authorized signed-upload flow. Upload is NOT authorized for Commerce OS on either; treated as read-only until the owner approves (Phase 3). | Owner | Blocked |
| B-026 | Currency per storefront | Both USD, prices in major units (exact decimal). | Owner | Done |
| B-027 | Restricted database roles per storefront: read (catalog tables only) and write (products only) | Customer data shares the database and RLS is disabled. | Eng | Open |
| B-028 | Schema fingerprint per mapping version, checked at Gate 4 | Replit deployments can change production schemas. Proposed fingerprint: sha256 of the canonical catalog structure, as computed by `scripts/local_storefront_db.py` (`drift` already compares it). | Eng | Open |
| B-029 | Local Storefront A and B test databases built from the schema dumps | Real-schema adapter contract tests without touching either site. Storefront A done 2026-10-27: `database/storefronts/storefront-a/` (structure snapshot, schema, invented seed) and `scripts/local_storefront_db.py` (up/down/drift); the structure matches the live Supabase copy and the production dump, and the runbook read role passes every check against it. Storefront B deferred (B-045). | Eng | In progress |
| B-030 | How to publish multi-color products to Storefront A, which has no color field | Decided: color is governed by product type (artwork: none; tangible goods: allowed). A multi-color product is blocked only for a destination without color support; the reviewer picks one color there or skips it. | Owner | Done |
| B-031 | Is the `gallery_items` table in scope | Excluded from product mapping, per both owners' recommendation. Revisit only if Commerce OS should manage gallery content. | Owner | Done |
| B-032 | Which environment the unlabeled Storefront A dump comes from | Development database (`heliumdb`). | Owner | Done |
| B-033 | Remove the development fallback credential from Storefront A's upload authorization code | The handoff shows it is also sent by the upload screens, so it is in the public frontend bundle: treat it as compromised and rotate it. Precondition before granting any external integration upload access. | Owner | Open |
| B-034 | Pluggable database providers and catalog profiles, with `/setup-storefront` | Owner request: choose Replit-managed Postgres or Supabase per database, and add more later. | Eng | Done |
| B-035 | Write per-storefront mappings (categories, tier types, tag IDs) | Written to `config/mappings/<id>.local.json` (gitignored) from both owners' lists; editable with `/edit-mappings`. Product-type → category mappings marked `proposed` until confirmed. | Eng | Done |
| B-036 | Confirm product-type → category mappings and whether `Blog` is excluded on both storefronts | Blog excluded on both; all product-type mappings confirmed (owner, 2026-10-21; mappings v3). | Owner | Done |
| B-037 | Confirm whether Storefront B's development `Cap` and production `Ball Cap` tags mean the same thing | Same tag (owner, 2026-10-21). Merged into one key, `ball-cap`, in mapping v2. | Owner | Done |
| B-038 | Creating new categories or tags in a storefront (`proposed_new` entries) | A storefront write: needs `categories`/`tags` in the profile's write tables and an approved change set. Phase 3. | Eng | Open |
| B-039 | Read-only roles for both storefronts, limited to `products`, `categories`, `tags` | Enables Phase 2 catalog reads and list refresh in `/edit-mappings`. Storefront A: done 2026-10-27 on its Supabase project, with read policies (runbook §2a); the check passes all 10 items, reads 39 products, 4 categories and 4 tags, and both lists match mapping v3. Storefront B: deferred (B-045). `scripts/check_read_role.py` verifies grants, RLS policies, row counts, and diffs live lists against the mapping. | Owner | In progress |
| B-040 | Install a Postgres client (`brew install libpq`) on the machine that runs the read-role check | Installed 2026-10-21: libpq 18.6 via Homebrew (keg-only at /opt/homebrew/opt/libpq/bin; the check script finds it there). | Owner | Done |
| B-041 | Hosting for the Python services and dashboard, model provider, and job queue | Remaining B-009 choices. Proposed: Postgres-backed queue in the operational DB; decide hosting before Phase 2. Hosting quotes (2026-10-27): Replit Reserved VM about $15/month (owner's quote); Fly.io pay-as-you-go, roughly $2–7 per small machine (no free tier for new accounts); Render and Railway similar. Needs: always-on worker, separate secrets from the storefronts. **Hosting decided 2026-10-27: Replit Reserved VM for the proof of concept, in its own Repl** (decision log). Model provider and queue decided 2026-10-27: Claude through the Anthropic API, and the Postgres-backed queue in the operational database (`commerce_os.jobs`, `claim_job` with SKIP LOCKED; no separate queue service). | Owner | Done |
| B-042 | Create the operational Supabase project (new, separate from both storefronts) | Done 2026-10-26: a fresh project (micro, us-west-2, no migrations; ref in local config). An earlier project with another app's migration was set aside. | Owner | Done |
| B-043 | Implement the contract semantic rules in `packages/policy` (Python) and validate with `jsonschema`/Ajv | Done 2026-10-27: `packages/policy` (`validate` = schema + semantic rules, plus size, undeclared-option and missing-option rules and an expected-contract check); approval bindings defined once and shared with the adapters. Python uses the strict stdlib validator, moved to `packages/contracts/validator.py`, instead of `jsonschema`, to stay dependency-free; the dashboard will use Ajv. | Eng | Done |
| B-044 | Run the live operational-database test against the CommerceOS Supabase project | Done 2026-10-26: all nine migrations apply on Supabase Postgres; 30 smoke checks pass, each rejection for its named error; rolled back, nothing left behind. | Owner | Done |
| B-045 | MVP scope: Storefront A first, Storefront B after A's pilot | Owner decision 2026-10-25. Storefront B work (read role, adapter, tests) is deferred, not dropped; B stays in config with writes disabled. | Owner | Done |
| B-046 | Confirm Storefront A's production database is the Neon project the owner identified | Superseded 2026-10-26: Commerce OS no longer reads Storefront A's Neon database; it targets the Supabase project instead. | Owner | Done |
| B-047 | Choose Storefront A's test environment after switch-over (e.g. a Supabase branch tied to a GitHub branch) | Until switch-over, the `supabase-migration` test copy is the test environment. | Owner | Open |
| B-048 | Storefront A's admin API is not admin-only on `main` (orders, customers, messages exposed) | From the owner's handoff. Not a Commerce OS dependency (adapters never use the app API), but a live exposure; fix in the storefront repo. | Owner | Open |
| B-049 | Decide Storefront A's Commerce OS upload path: the app's upload flow, or bucket + `_meta` visibility record with a scoped credential | Images live in the private Supabase bucket `artwork` with `_meta/<path>.json`. Phase 3. | Eng | Open |
