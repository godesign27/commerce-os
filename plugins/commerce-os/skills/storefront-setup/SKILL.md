---
name: storefront-setup
description: Set up or change a storefront connection, or the Commerce OS operational database, by choosing a database provider (for example Replit-managed Postgres or Supabase) and a catalog profile, then writing a credential-free config entry. Use whenever someone wants to add a storefront, connect a new site, choose or switch a database type, configure the operational database, or asks which databases Commerce OS supports.
argument-hint: "[storefront id | operational]"
---

# Storefront setup

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)

Commerce OS supports more than one kind of database. Each storefront, and the operational database,
chooses a **provider** (how to connect, roles, where images live). Each storefront also chooses a
**catalog profile** (how its products are shaped). This skill records those choices. It doesn't
connect to anything, and it never handles a credential.

The provider and profile files live in the Commerce OS repository, not in the plugin, so this skill
runs in a Commerce OS checkout.

## Inputs

- The working directory's `resources/providers/*.json`, `resources/catalog-profiles/*.json`, and
  `config/storefronts.local.json` if it exists (otherwise `config/storefronts.example.json` as the
  starting shape).
- The administrator's answers: storefront ID and display name, provider, catalog profile, optional
  features, currency, environment variable prefix. For the operational database, only the provider.

## Outputs

- A new or updated entry in `config/storefronts.local.json` (gitignored).
- A list of the environment variables to set in `.env`: names only, such as `STOREFRONT_C_DB_URL`.
- When no profile fits, a proposed backlog item to write one, instead of a config entry.

## Allowed tools

Read and Glob in the working directory; Write and Edit on `config/storefronts.local.json` only.

## Forbidden actions

- Asking for, accepting, writing, or echoing a password, connection string, API key, or token. If the
  user pastes one, don't repeat it, tell them to rotate it, and continue with the variable name only.
- Connecting to, querying, or testing any database.
- Setting `writes_enabled` to `true` or `asset_upload` to `authorized`. Only an administrator does
  that, by hand, after Phase 3 approval.
- Reusing another entry's `env_prefix` or `mapping` path.
- Writing real storefront names into any committed file, including `config/storefronts.example.json`.
- Inventing a provider or profile that has no file. A missing one is a backlog item, not a guess.

## Workflow

1. Confirm the working directory has `resources/providers/`. If not, stop: setup must run in a
   Commerce OS checkout.
2. Say whether this is a storefront or the operational database, and whether it's new or a change.
3. **Provider:** list each provider file's `display_name`, `status` and `used_for`. Offer only those
   whose `used_for` includes the target. Note when `status` is `documented` (no adapter yet).
4. **Catalog profile** (storefronts only): list profiles. If the user isn't sure, ask for the
   storefront's application schema or a schema-only dump, and compare its products table with each
   profile's `product`, `variants` and `optional_features`. If none fits, stop and propose a backlog item.
5. **Features:** offer the chosen profile's `optional_features`; record only the ones this storefront has.
6. **Identity:** lowercase `id` (e.g. `storefront-c`), `display_name`, `currency`, and an `env_prefix`
   in upper snake case that no other entry uses. The mapping path is
   `config/mappings/<id>.local.json`; create its lists with `/edit-mappings <id>`.
7. Write the entry with `writes_enabled: false` and `asset_upload: "not_authorized"`. Show the diff
   before writing, and ask before overwriting an existing entry.
8. List the `.env` variable names from the provider's `connection.env_suffixes`, prefixed.

## Validation

- The provider and profile files exist, and the provider's `used_for` includes the target.
- `features` is a subset of the profile's `optional_features`.
- `id` and `env_prefix` are unique across all entries, and the operational database's prefix differs
  from every storefront's.

## Failure behavior

Any check fails: write nothing, say which one, and what would fix it.

## Evidence requirements

A catalog profile choice must cite what it was compared against: schema file, dump, or samples. "It
looks like the other site" is not evidence.

## Current status

Runnable. Writes local configuration only; nothing reads it until the Phase 1 workflow service exists.
