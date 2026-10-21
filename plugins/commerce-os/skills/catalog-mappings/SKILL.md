---
name: catalog-mappings
description: Add, edit, retire or propose entries in a storefront's category, tag and tier-type lists, or in Commerce OS's product types, and change how product types map to a storefront's categories and tags — versioned, local, never written to the storefront. Use whenever someone wants to add or rename a category or tag, change which category a product type goes in, exclude a category such as a blog, add a product type, or change whether a type has colors.
argument-hint: "<storefront-id | product-types>"
---

# Catalog mappings

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)

Each storefront keeps its own categories and tags. Commerce OS keeps one shared list of product types,
which decides things like whether a product can have colors. This skill maintains both lists and the
mapping between them. Every change is a new version, because approvals record the mapping version
they used.

These files live in the Commerce OS repository, so this skill runs in a Commerce OS checkout.

## Inputs

- Target: a storefront ID (edits `config/mappings/<id>.local.json`) or `product-types` (edits
  `resources/product-types/*.json`).
- The administrator's change, and its source: the storefront admin screen, an owner handoff, or (from
  Phase 2) a read-only refresh through `~~workflow`.

## Outputs

- The updated file with `version` increased and, for mappings, a new `changes` entry (date, who or
  what supplied it, summary).
- A before/after diff shown before saving.

## Allowed tools

Read and Glob in the working directory; Write and Edit on `config/mappings/*.local.json` and
`resources/product-types/*.json` only.

## Forbidden actions

- Creating, renaming or deleting a category or tag **in a storefront**. A new one is recorded as
  `proposed_new` and waits for an approved change set.
- Deleting an entry or a product type. Retire it (`excluded` or `retired`) instead.
- Copying an ID from one storefront or environment into another.
- Inventing an ID or slug. Unverified values stay `null`.
- Writing real storefront names, IDs or lists into a committed file, including the example mapping.
- Changing an approved change set because a mapping changed. The change invalidates that approval
  instead (Gate 4 checks the mapping version).

## Workflow

1. Read the target file. If a storefront's mapping is missing, start from
   `config/mappings/storefront.example.json`'s shape with no entries.
2. Restate the change in one line, and its source.
3. **Storefront lists:**
   - Add: require a name for at least one environment; record the ID and slug only if supplied.
   - Edit: change only the stated fields.
   - Retire: set `status: "excluded"` with a note saying why.
   - Merge (two entries are the same thing): move the other entry's names and IDs onto the survivor,
     then retire the other with `status: "excluded"`, empty `name`, and `merged_into: "<survivor key>"`.
     Repoint any `product_types` references to the survivor.
   - New in the storefront: add with `status: "proposed_new"` and no IDs.
4. **Product-type mapping:** set the `category` key and `type_tags` keys. Each must exist in this file;
   set `proposed: true` unless the owner confirmed it.
5. **Product types:** add or edit `resources/product-types/<id>.json`, increase its `version`, and keep
   the README table in step. Changing `options.color` from `not_applicable` to `allowed` or back is a
   rule change: say what it changes for existing drafts of that type.
6. Show the diff, save on confirmation, and increase `version`.
7. If a storefront lacks the `color_variants` feature and a mapped product type allows color, remind
   the user that multi-color products of that type will be blocked for that storefront.

## Validation

- Keys are unique within each list. Every `product_types` reference resolves to an entry in the same file.
- Every product type referenced exists in `resources/product-types/`.
- `version` increased by exactly one.

## Failure behavior

Any check fails: save nothing, and say which check failed and how to fix it.

## Evidence requirements

Every change names its source. A list entry is never added from a guess about what the storefront
probably has.

## Current status

Runnable on local files. Refreshing from a storefront needs the Phase 2 read connection.
