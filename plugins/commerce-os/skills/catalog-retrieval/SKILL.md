---
name: catalog-retrieval
description: Retrieve similar or possibly identical existing products from one storefront's catalog at a time, read-only, and compare them with a proposed product — ranked candidates with matching and conflicting evidence. Use whenever someone asks about similar items, existing products, duplicates, "do we already sell this", or how a storefront usually structures this category.
argument-hint: "<submission id> <storefront-a|storefront-b>"
---

# Catalog retrieval

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)

Similar items are useful for structure, option names, category conventions and writing style. They
are never evidence for a new product's facts, and a likely match is a question for a human, not a
decision (PRD §10).

## Inputs

- The product proposal (category, observations, grouping).
- Exactly one destination: `~~storefront-a` or `~~storefront-b`. Run the skill again for the other.

## Outputs

The Catalog candidates section of the product proposal for that storefront: candidate external ID,
matching evidence, conflicting evidence, rank, and proposed use (`structure only` or `possible same
product — needs human`). Structural conventions observed (option names, typical fields).

## Allowed tools

Read-only catalog queries through `~~workflow` scoped to the one storefront; Write under
`.commerce-os/out/` only.

## Forbidden actions

- Querying both storefronts in one call or combining their results.
- Copying price, stock, material, dimensions, brand, SKU, GTIN or rights from a candidate.
- Marking a candidate as the same product. Identity reuse needs human confirmation.
- Any write to a catalog.

## Workflow

1. Search by supplied identifiers first (SKU, GTIN). An exact match is strong evidence but still needs
   confirmation, and any conflict blocks.
2. Then by category plus visible attributes and title terms.
3. Rank candidates; for each, list what matches and what conflicts.
4. Summarize conventions: option axis names and values used, field patterns, copy style.

## Validation

Every candidate names its storefront. No candidate field appears in the proposal's Fields table as a
value source.

## Failure behavior

Storefront unreachable: record that retrieval did not run for that storefront and continue; the other
storefront's review is not blocked.

## Evidence requirements

Candidate facts are evidence about the candidate only. A field may become `verified_catalog` only after
a human confirms identity, and only for that storefront.

## Current status

Not runnable: no storefront connection exists. Schemas are known from discovery
(`docs/discovery/storefront-schemas.md`). Do not simulate candidates and present them as real.
