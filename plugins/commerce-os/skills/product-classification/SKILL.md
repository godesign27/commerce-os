---
name: product-classification
description: Propose a tentative product type (for example artwork, hat, blanket) for a submission from its validated images and supplied metadata, with visual observations, evidence and confidence. Use whenever someone asks what a product is, which category or template applies, or why a submission was classified a certain way.
argument-hint: "<submission id>"
---

# Product classification

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)
> Output template: [product-proposal.md](../../shared/templates/product-proposal.md)

The category chooses the template and therefore which fields are required. A wrong category silently
changes what the reviewer is asked for, so classification is tentative and always shows its evidence.

## Inputs

- Source manifest with accepted asset records.
- Product types from `resources/product-types/*.json` (each versioned; `draft` types count as candidates
  until the owner confirms them), plus `other`. Aliases help recognize a type; they are never evidence.

## Outputs

The Category section of a product proposal: proposed category, status (`observed` or `inferred`),
evidence (asset IDs), confidence, alternatives considered, and a review issue when confidence is low
or alternatives are close. Visible-attribute observations (e.g. "embroidered logo on front panel"),
each tied to an asset.

## Allowed tools

Read on the source manifest and assets; Write under `.commerce-os/out/` only.

## Forbidden actions

- Classifying from filename or folder name alone.
- Inventing a product type that has no file. Use `other` plus a review issue.
- Asserting material, size, brand or any commercial fact from appearance.

## Workflow

1. Look at every accepted image. Note what is visibly present.
2. Compare against the product types. Choose the best fit; record the runner-up and the type's version.
3. A supplied category in the manifest is `supplied`; if it disagrees with what's visible, mark
   `conflicting` and raise a blocking issue.
4. Record visible attributes as `observed`, each with the asset that shows it.

## Validation

The type is a product-type ID or `other`. Every observation cites at least one asset.

## Failure behavior

No confident fit: category `other`, status `unknown`, blocking issue asking the reviewer to choose.

## Evidence requirements

`observed` for what is visible; `inferred` for category when it is a judgment; `supplied` when the
manifest states it. Confidence never stands in for evidence.

## Current status

Specification only. Seven draft product types exist in `resources/product-types/`.
