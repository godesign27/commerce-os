# Architecture

Status: Phase 0a. This describes the target architecture from [PRD.md](../PRD.md) §5 and how the
repository is laid out to build it. Nothing below the plugin layer exists yet.

## System

```text
Google Drive intake folders
    → notification receiver (services/drive-events) → durable inbox
    → source resolution and immutable snapshot
    → workflow service (services/workflow) + workers (services/workers)
        └─ invokes agents for proposals; validates every output deterministically
    → Commerce OS operational database (database/operational) + asset storage
    → review dashboard (apps/review-dashboard)
    → approved immutable change sets
    → Storefront A adapter (packages/adapters/storefront-a) → Storefront A database
    → Storefront B adapter (packages/adapters/storefront-b) → Storefront B database
```

## Layers and who may do what

| Layer | Location | May write to | Notes |
|---|---|---|---|
| Plugin agents and skills | `plugins/commerce-os/` | Local `.commerce-os/out/` only | Propose; never decide or publish. |
| Workflow service | `services/workflow/` | Operational DB | The only thing that moves state, via validated transitions. |
| Workers | `services/workers/` | Operational DB, asset store; storefronts only via adapters after Gate 4 | Holds write credentials server-side. |
| Drive receiver | `services/drive-events/` | Operational DB inbox | Persists before acknowledging. |
| Dashboard | `apps/review-dashboard/` | Through the workflow service only | Never holds a storefront credential. |
| Adapters | `packages/adapters/storefront-*/` | Their own storefront only | Separate code, mapping and credentials per storefront. |
| Contracts and policy | `packages/contracts/` (JSON Schema, written), `packages/policy/` (Phase 1) | Nothing | Shared schemas and rules used by the Python backend and the TypeScript dashboard. |

## Database providers

Each storefront and the operational database choose a provider (`replit-postgres`, `supabase`, more
later) and storefronts choose a catalog profile. Adapters are provider drivers plus a profile, configured
per storefront. See [storefront-connections.md](storefront-connections.md).

## Three database boundaries

Storefront A, Storefront B and the operational database each have their own project, URL and
credentials per environment (see `.env.example`). Storefront databases stay authoritative for their
live records. Cross-storefront identity is an explicit `destination_product_links` row, never assumed.

## Developer-tool entry points

Claude Code uses the plugin. Cursor reads `AGENTS.md`, `CLAUDE.md` and `.cursor/rules/commerce-os.mdc`,
and follows the same skill files directly. Both reach data only through the workflow interface
(Phase 1+), so neither can bypass server-side approval (PRD §18, AC-14).

## Open architecture decisions

Runtime, hosting, model provider, queue and operational DB service are undecided (BACKLOG B-009). See
[decision-log.md](decision-log.md).
