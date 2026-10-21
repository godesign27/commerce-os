# Storefront connections: providers, profiles, and storefront entries

Commerce OS doesn't hard-code where a storefront's catalog lives. Every database it talks to, each
storefront and its own operational database, is set up by choosing a **provider**. Each storefront
also chooses a **catalog profile**. Adding a new kind of database later means adding one provider
file and one adapter driver. Nothing else in the workflow changes.

## The three layers

| Layer | Answers | Lives in | Changes when |
|---|---|---|---|
| Provider | How do we connect, which roles do we use, where do images live, how does the schema change? | `resources/providers/<provider-id>.json` | A new hosting type is supported |
| Catalog profile | How are products, variants, images, tags and status shaped inside the database? | `resources/catalog-profiles/<profile-id>.json` | A storefront app with a different product model is supported |
| Storefront entry | Which provider and profile does this storefront use, with which features, currency and credentials? | `config/storefronts.local.json` (gitignored; template in `config/storefronts.example.json`) | A storefront is added or reconfigured |

A storefront's **mapping** (its categories, tier types and tag IDs) stays per storefront in
`config/mappings/<storefront-id>.local.json` (gitignored), as PRD §15 requires; edit it with
`/edit-mappings`. Profiles describe structure,
mappings describe one storefront's values, and neither is shared across storefronts at runtime.

## Supported providers

| Provider ID | What it is | Storefronts | Operational DB | Status |
|---|---|---|---|---|
| `replit-postgres` | Replit-managed PostgreSQL (Neon), images in Replit App Storage | Yes | Yes | Documented from discovery; adapter not built |
| `supabase` | Supabase Postgres, images in Supabase Storage | Yes | Yes | Documented; details must be verified against current Supabase docs before an adapter is built |

Both storefronts in discovery use `replit-postgres` with the `replit-artstore-v1` profile. The
operational database may use either provider (BACKLOG B-009), but it is always a separate
project with its own credentials.

## Setting up a storefront

Run `/setup-storefront` in Claude Code, or follow the `storefront-setup` skill in Cursor. It asks for:

1. **Storefront ID and display name.** The ID is a lowercase slug such as `storefront-c`.
2. **Provider:** a choice from `resources/providers/`.
3. **Catalog profile:** a choice from `resources/catalog-profiles/`, or "none fits". That stops setup and
   records a backlog item to write a new profile.
4. **Optional features** the profile defines, such as `color_variants` or `is_sold`.
5. **Currency** and an **environment variable prefix**, such as `STOREFRONT_C`.

It writes the entry to `config/storefronts.local.json` and tells you which environment variables to
set in `.env`. It never asks for, stores or prints a credential, and never connects to the database.
New entries always start with `writes_enabled: false` and `asset_upload: "not_authorized"`.

## Adding a new provider

1. Add `resources/providers/<id>.json` with every required key (see `resources/providers/README.md`).
   Keep `status` at `documented` until an adapter driver passes its contract tests.
2. Add a row to the table above. `tests/test_providers.py` fails if a provider is missing from it.
3. In Phase 1 and later, add the driver in `packages/adapters/drivers/<id>/`, implementing the adapter
   contract (`capabilities`, `readCatalog`, `validate`, `plan`, `dryRun`, `publishApprovedChangeSet`,
   `reconcile`).
4. Add contract tests against a local database built for that provider.

## Adding a new catalog profile

Write `resources/catalog-profiles/<id>.json` from the storefront's application schema and
sanitized sample rows, never from guesses. It must name the hidden status used for creates and the
placeholder values to ignore, and list every optional feature with its column.

## Rules that hold for every provider

- One storefront entry = one provider instance with its own credentials. Two storefronts never share
  an `env_prefix`, a credential, or a mapping, even on the same provider.
- Agents never connect directly. Every provider is reached only through the workflow service and its
  adapter (PRD §6).
- A storefront is read-only until it has a write role, a verified adapter, an approved Phase 3 plan,
  and `writes_enabled: true` set by an administrator.
- Gate 4 checks the storefront's schema fingerprint against its mapping version before any write, on
  every provider.
