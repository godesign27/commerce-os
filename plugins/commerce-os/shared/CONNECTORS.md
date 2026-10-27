# Connectors

Skills never name a concrete tool. They use a `~~category` placeholder, mapped here.

**Phase 0a: nothing is connected.** The plugin ships no MCP servers on purpose. A database connector
in the plugin would hand agents direct write access to a storefront, which [COMMERCE-CONTEXT.md](COMMERCE-CONTEXT.md)
forbids. From Phase 1, agents reach data only through `~~workflow`, the authenticated Commerce OS
workflow interface, which enforces read-only scopes and server-side approvals.

| Category | Placeholder | Planned implementation | Agent access | Status |
|---|---|---|---|---|
| Workflow interface | `~~workflow` | Commerce OS workflow API | Inspect, draft, dry run, request publication | Not built |
| Intake source | `~~drive` | Google Drive, via the workflow service | None directly; read via `~~workflow` | Not built |
| Storefront A catalog | `~~storefront-a` | Storefront A adapter, read-only for agents; provider set in config | Read via `~~workflow` | Not built |
| Storefront B catalog | `~~storefront-b` | Storefront B adapter, read-only for agents; provider set in config | Read via `~~workflow` | Not built |
| Operational database | `~~ops-db` | Separate Commerce OS database; provider set in config | None directly | Not built |
| Asset storage | `~~assets` | Operational asset store | Read derivatives via `~~workflow` | Not built |

## Database providers

A storefront category says *which* storefront, not *what kind of database*. Each storefront entry in
`config/storefronts.local.json` names a provider from `resources/providers/` (today `replit-postgres`, `neon` or
`supabase`) and a catalog profile from `resources/catalog-profiles/`. Skills stay provider-neutral: they
use the catalog profile's field names and never assume a provider. Set entries up with
`/setup-storefront`.

## When a category isn't connected

Work from what the user provides (local files, fixtures, pasted metadata) and say plainly which step
could not run and why. Don't nag the user to connect something, and never simulate a connection and
present its output as real.
