---
name: variant-grouping
description: Decide how a submission's images map to products, views and option variants — multiple angles of one item versus color or size variants versus separate products — with duplicate detection and explicit ambiguity. Use whenever someone mentions colors, colorways, sizes, variants, "these are the same product", "split these", swatches, or multiple products in one folder.
argument-hint: "<submission id>"
---

# Variant grouping

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)
> Output template: [product-proposal.md](../../shared/templates/product-proposal.md)

The commonest catalog error is grouping: two angles become two products, or two colors become one.
This skill makes each grouping decision visible so the reviewer can confirm, split or merge (PRD §10).

## Inputs

- Source manifest, asset records, and the classification from product-classification.
- Option vocabulary for the category from `resources/categories/` (B-005).

## Outputs

The Grouping, Option definitions and Variants sections of the product proposal. Each image is assigned
exactly once: product, role (primary, gallery, detail, swatch), and variant. Review issues for every
ambiguous decision.

## Allowed tools

Read on the manifest, assets and proposal; Write under `.commerce-os/out/` only.

## Forbidden actions

- Generating a full color × size matrix. Only combinations with evidence exist.
- Inferring sizes that no image or manifest shows.
- Treating lighting differences as distinct colors without a review issue.
- Treating upload proximity or filename numbering as proof of grouping.

## Workflow

1. Group images showing the same physical item from different angles as views of one variant.
2. Where the same design appears in clearly different colors, propose a `color` option with one value
   per observed color. Uneven lighting: keep it one variant, add a warning issue.
3. Where images show different designs, propose separate products. Never merge silently.
4. Sizes come only from the manifest (`supplied`) or a human. Otherwise no size axis.
5. Normalize option keys and values (lowercase keys, trimmed labels); check uniqueness of option
   combinations per product.
6. A product with no options gets one default variant.
7. If a reviewer decision already exists for this revision, apply it and record it; don't re-decide.

## Validation

Every accepted asset is assigned once. No two variants of a product share the same normalized option
values. Every variant cites assets.

## Failure behavior

Cannot tell views from variants: keep them as views of one variant and raise a blocking issue
showing both interpretations.

## Evidence requirements

Observed colors are `observed` with confidence; supplied options are `supplied`. SKU and GTIN are
`supplied` or `null`, never generated.

## Current status

Specification only. Runs on fixtures once the Phase 1 contracts exist (B-020).
