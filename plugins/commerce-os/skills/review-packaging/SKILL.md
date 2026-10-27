---
name: review-packaging
description: Assemble the human review package for a submission — blockers first, original and processed images side by side, product and variant structure, fields needing decisions with their evidence, per-storefront catalog comparison and destination previews, and concrete reviewer questions. Use whenever someone asks to review a product, what's blocking it, what needs a decision, or to prepare something for the reviewer.
argument-hint: "<submission id>"
---

# Review packaging

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md) · Workflow: [WORKFLOW.md](../../shared/WORKFLOW.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)
> Output template: [review-package.md](../../shared/templates/review-package.md)

The reviewer's time is the scarce resource. A good package puts what blocks approval first, shows
evidence beside every claim, and asks questions that can be answered in a line. It never makes an
unsupported field look settled.

## Inputs

- Source manifest, derivative manifest, product proposal, canonical draft, and change sets for the
  selected destinations, all at matching revisions.

## Outputs

`review-package.md` under `.commerce-os/out/<submission-id>/`, following the template.

## Allowed tools

Read on the submission's outputs; Write under `.commerce-os/out/` only. From Phase 1, `~~workflow`
reads for the current state.

## Forbidden actions

- Presenting an `inferred` or `unknown` field as settled, or dropping it from the package.
- Merging Storefront A and B comparisons.
- Recording any reviewer decision. Decisions are made in the dashboard and recorded by the workflow
  service.

## Workflow

1. Check that all inputs reference the same canonical revision. If not, stop: the package would be stale.
2. Blockers: every blocking issue, with the gate it blocks, the destination, and who can resolve it.
3. Images: each original beside its derivatives; consequential edits flagged for acceptance.
4. Structure: products, variants, and each grouping decision to confirm or split.
5. Fields: unknown required first, then conflicting, then low-confidence inferences.
6. Catalog comparison, one section per storefront.
7. Destination previews: per destination, the change set's requested status, operations and diff.
8. Questions: numbered, specific, answerable in a line.

## Validation

Every blocking issue in the draft appears in Blockers. Every image appears once.

## Failure behavior

Missing input (e.g. no change set for a selected destination): include what exists, list the missing
piece as a blocker.

## Evidence requirements

Every field shown carries its status and evidence reference exactly as recorded.

## Current status

Runnable on hand-made fixture outputs. Mark the package `simulated: true`.
