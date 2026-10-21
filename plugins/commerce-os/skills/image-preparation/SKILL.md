---
name: image-preparation
description: Plan and produce product image derivatives from versioned recipes — orientation, safe re-encode, color handling, resize, compression, destination format, metadata stripping — while keeping originals untouched. Use whenever someone asks to prepare, resize, compress, convert, crop, clean up or remove the background of product images, or asks what derivatives a storefront needs.
argument-hint: "<submission id> [recipe id]"
---

# Image preparation

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)

Derivatives exist so each storefront gets images in the size and format it needs. They must show the
same product: identity, artwork, colorway, branding, pattern and texture never change (PRD §9).

## Inputs

- Accepted asset records from asset-validation.
- An image recipe from `resources/image-recipes/` (versioned), chosen per destination. Until B-006 is
  decided, only the `preview` recipe (orientation fix, resize to fit, re-encode, strip metadata) applies.

## Outputs

A derivative manifest: for each derivative its source asset, recipe and version, output MIME, width ×
height, bytes, checksum, collision-safe key (content-addressed), and transformation history. A list of
consequential edits awaiting reviewer acceptance.

## Allowed tools

Read on asset records; Write under `.commerce-os/out/` only. From Phase 1, the
`packages/image-pipeline` transform entry point via `~~workflow`.

## Forbidden actions

- Changing an original, or saving a derivative over one.
- Recoloring, retouching, generating, extending, or compositing image content.
- Applying crop or background removal that may remove product detail without a reviewer accepting a
  preview first.
- Uploading any derivative to a storefront or public location.

## Workflow

1. Select the recipe per destination. Record recipe ID and version.
2. Apply only the recipe's operations, in order. Preserve aspect ratio unless the recipe says otherwise
   and the result is marked consequential.
3. Key each derivative by content hash plus recipe version, so re-running is idempotent.
4. Mark crops, background removal, and any operation that changes visible product area as
   consequential: produce a preview, do not use the derivative until accepted.
5. Draft alt text describing only what is visible. No materials, sizes or claims.

## Validation

Every derivative traces to exactly one original and one recipe version. Re-running the same recipe on
the same checksum yields the same key.

## Failure behavior

A failed transform records the error against that derivative only and leaves the original usable for
review.

## Evidence requirements

Alt text is `observed` and limited to visible content. Image rights are never inferred from presence.

## Phase 0a status

Specification only. No recipes exist yet (`resources/image-recipes/` is empty) and no pipeline runs.
