# Decision log

Confirmed facts, assumptions and open decisions, kept separate (PRD §23.3). Open decisions are tracked
with IDs in [BACKLOG.md](../BACKLOG.md).

## Confirmed (from the PRD's source conversation)

- Two ecommerce sites currently use Supabase. **Contradicted by the schema dumps; see Discovered below (B-023).**
- New product images originate in a Google Drive folder.
- Agents prepare images, identify product types (e.g. artwork, hats, blankets), use similar catalog
  entries to help populate product information, and handle multiple colors.
- Human review happens in a dashboard.
- Workflow initiation is event-driven.
- The two storefront catalogs stay separate.
- The repo exposes agents, skills, resources, docs and rules for Claude Code and Cursor.
- Commerce OS is independent of the sibling PM plugin repository.

## Decided in Phase 0a (2026-10-20)

| Decision | Why | Revisit when |
|---|---|---|
| Marketplace layout: plugin in `plugins/commerce-os/`, runtime at repo root | Only the plugin ships on install; runtime code and tests never do. Differs from PRD §18, which puts `.claude-plugin/` at root. | Never, unless distribution changes. |
| Router `commerce-lead` added, opt-in, not bound as default agent | Freeform routing without taking over every session. | B-022 |
| No MCP servers in the plugin | A storefront DB connector would bypass the workflow service. | Phase 1, when `~~workflow` exists. |
| All 12 PRD §6.1 skills scaffolded (§18 listed 9) | §6.1 is the requirement; §18 is illustrative. | — |
| Canonical agent-facing policies live in `plugins/commerce-os/shared/`; `AGENTS.md`, `CLAUDE.md`, the Cursor rule and `docs/` point to them | One source per rule; the plugin can't read outside its own folder once installed. | — |
| Agent tools limited to Read, Grep, Glob, Write (router adds Agent) | Least privilege; no shell, no network. | Phase 1 |

## Discovered in Phase 0b (2026-10-21)

From schema-only dumps of both storefronts. Detail: [discovery/storefront-schemas.md](discovery/storefront-schemas.md).

- **Contradicts a confirmed fact:** both storefronts run on Replit-managed PostgreSQL (Neon), not
  Supabase as PRD §1.1 states. Awaiting owner confirmation (B-023). The PRD is unchanged until then.
- Both sites share one schema lineage. Storefront B adds `color_variants`; Storefront A adds
  `show_in_gallery`, `is_sold` and its own boards and show tables.
- There is no variants table; options are JSONB on `products`.
- `products.status` defaults to `'active'`, so an insert without an explicit status is live.
- Customer data shares each catalog database, and row-level security is off.

## Decided in Phase 0b (2026-10-21)

| Decision | Why | Revisit when |
|---|---|---|
| Pluggable database providers: each storefront and the operational database choose a provider from `resources/providers/`; storefronts also choose a catalog profile | Owner request after discovery showed both storefronts on Replit-managed Postgres, not Supabase. New hosting types are added as a provider file plus a driver. | A third provider is needed. |
| One catalog profile (`replit-artstore-v1`) describes both storefronts' shared structure; each storefront keeps its own features, mapping, credentials and schema fingerprint | Both apps share a schema lineage. PRD §15 forbids assuming matching schemas; the profile is backed by both schemas, and per-storefront contract tests still run separately. | A storefront's schema diverges from the profile. |
| Color is a product-type rule (B-030): artwork never has a color option; tangible goods may. A multi-color product is blocked only for a destination without color support | Owner decision. Keeps artwork free of color options and lets tangible goods carry colors where the storefront supports them. | A storefront adds color support. |
| Product types replace PRD "category templates"; storefront categories and tags are separate, per-storefront, per-environment lists | Storefront categories differ by site and environment (IDs, names); Commerce OS needs one stable classification. | — |
| Real mappings are gitignored local files | The GitHub repo is public; mappings hold real names and IDs. | The repo becomes private. |
| **Stack (B-009): Python backend, TypeScript dashboard.** Workflow service, workers, image pipeline and storefront adapters in Python; the review dashboard in TypeScript/React | Owner decision. Python has strong imaging libraries for the pipeline. Skill input/output contracts are JSON Schema in `packages/contracts/` so both languages validate against the same definitions. | — |
| **Operational database (B-009): a new standalone Neon project** (`neon` provider), separate from both storefronts' Replit-managed projects | Owner decision: same vendor and console already in use; branches give test copies for migrations. | — |
| Product-type → category mappings confirmed as proposed on both storefronts (B-036); Blog excluded | Owner decision. | A storefront changes its categories. |
| **MVP targets Storefront A only (2026-10-25).** Phases 1–4 run end to end for Storefront A first; Storefront B follows as an extension | Owner decision. One storefront proves the whole pipeline with less to configure. Everything stays multi-storefront by design (separate mappings, credentials, adapters), so adding B is configuration plus its adapter, not a redesign. | Storefront A's pilot passes its acceptance criteria. |
| **Storefront A moves to Supabase (2026-10-26).** Commerce OS targets only Storefront A's Supabase project, never its Replit/Neon database. Until switch-over, that project is the test copy run by the storefront's `supabase-migration` branch; after switch-over it is production | Owner decision; Storefront A's own migration (database and images) is done and verified. The provider model absorbs it as a config change. | Switch-over. |
| **Testing happens on the storefront's GitHub branch environment** (2026-10-26): today the `supabase-migration` test copy; after switch-over, a separate test environment tied to a branch | Owner decision. A fresh production copy at switch-over resets any Commerce OS test writes. Exact post-switch-over mechanism (e.g. a Supabase branch) to be chosen before then (B-047). | Switch-over. |
| **Operational database moves to Supabase (2026-10-26)**: a new Supabase project in the owner's organization, separate from Storefront A's (replaces the earlier Neon choice) | Owner decision: one vendor for Storefront A and Commerce OS. Migration 0009 revokes Supabase's Data API roles from the `commerce_os` schema; Commerce OS never uses the secret key or `postgres` role. | — |
| **Switch-over waits** until Commerce OS reaches a point where it makes sense (2026-10-26) | Owner decision. Commerce OS reads and later test-publishes against the Supabase test copy meanwhile. | Commerce OS Phase 3 sandbox publication works. |
| **Hosting for the proof of concept (B-041, 2026-10-27): Replit**, one new Repl for Commerce OS only, deployed as a Reserved VM (always on, so the workers keep running) | Owner decision: familiar platform, predictable cost (about $15/month). Conditions: its own Repl and Secrets, never shared with a storefront's Repl; no storefront write credentials until Phase 3; services stay plain Python with nothing Replit-specific, so moving to another host (e.g. Fly.io) is a redeploy. | Cost, worker limits or the pilot's load outgrow it. |
| **Model provider (B-041, 2026-10-27): Claude, through the Anthropic API**, for classification, grouping and drafting from photos | Owner decision. Strong image understanding and structured output. Every model output records its model version (`product_proposals.model_version`), so a model change is visible in the audit trail. The specific model is chosen in Phase 1 against the labeled sample photos (B-016). | Phase 1 evaluation shows a quality or cost problem. |
| **Job queue (B-041, 2026-10-27): Postgres-backed, in the operational database** (`commerce_os.jobs`, `claim_job` with `FOR UPDATE SKIP LOCKED` and leases); no separate queue service | Owner decision. Low volume (tens to hundreds of photos a week); one fewer service to host, secure and pay for; jobs share transactions with the state they change. | Throughput or latency needs outgrow it. |
| `gallery_items` excluded from product mapping | Both owners' recommendation; it is editorial content, not sellable products. | Commerce OS should manage gallery content. |

## Assumptions (unconfirmed)

- Submission unit is one product folder with an optional manifest; readiness is a ready manifest (B-003).
- MVP categories: artwork, hat, blanket (B-005).
- Create-only publication first (B-007).
- Cursor reads `AGENTS.md`, `CLAUDE.md` and `.mdc` rules with `alwaysApply` (checked against Cursor's
  rules documentation on 2026-10-20; re-verify before claiming AC-14).

## Open

PRD §22 questions 1–13 are BACKLOG B-001 to B-013.
