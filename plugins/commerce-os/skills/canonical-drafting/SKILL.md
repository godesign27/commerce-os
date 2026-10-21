---
name: canonical-drafting
description: Build the versioned canonical product and variant draft from a product proposal using the approved category template — structured fields with field-level evidence, option definitions, ordered asset roles and required-field validation. Use whenever someone asks to draft the product, fill in the listing, write the title or description, check required fields, or see what's still missing.
argument-hint: "<submission id>"
---

# Canonical drafting

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md) · Workflow: [WORKFLOW.md](../../shared/WORKFLOW.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)

The canonical draft is the storefront-neutral staging record (PRD §8). It is not a third catalog:
prices, stock and destination status live only in each destination's draft. Every field carries its
evidence so the reviewer sees what is known, what is guessed, and what is missing.

## Inputs

- The product proposal, including any reviewer decisions already recorded.
- The category template from `resources/categories/` (versioned): required fields, permitted
  attributes, option vocabulary.

## Outputs

A canonical draft at a new revision: product fields (`title`, `description`, `category_id`, `brand`,
`vendor`, `material`, `dimensions`, `option_definitions`, `attributes`, `assets`), variants
(`option_values`, `sku`, `gtin`, assets, attributes), each factual field as an evidence record, the
template and policy versions used, and review issues for every unmet requirement.

## Allowed tools

Read on the proposal and templates; Write under `.commerce-os/out/` only.

## Forbidden actions

- Filling a required field to make validation pass.
- Adding attributes the category template does not permit.
- Putting price, currency, stock, tax or destination status in the canonical draft.
- Writing copy that adds unverified claims (handmade, organic, premium, exact sizing).
- Editing a previous revision in place.

## Workflow

1. Start a new revision; record `source_snapshot_id` and all policy and template versions.
2. Carry every field from the proposal with its evidence record unchanged.
3. Draft `title` and `description` only from supported facts. Mark them `inferred` with the facts they
   rephrase as evidence. Unknown facts are left out of the copy, not hedged into it.
4. Dimensions carry value and unit; unknown stays `null`.
5. Validate against the template: each missing required field becomes a blocking issue naming the
   evidence needed and who can supply it.
6. Detect duplicate-candidate issues carried from catalog-retrieval and keep them blocking until a
   human decides.

## Validation

- Option combinations are unique per product.
- Every non-null factual field has an evidence record with an allowed status.
- No commercial fact has status `observed` or `inferred` without a policy exception and human decision.

## Failure behavior

Template missing for the category: stop, raise a blocking issue, keep the proposal as-is.

## Evidence requirements

Per [evidence-policy.md](../../shared/evidence-policy.md). Copy fields cite the facts they rephrase.

## Current status

Specification only. Category templates are not populated (B-005); contracts arrive in Phase 1 (B-020).
