---
name: brand-context
description: Create or change a storefront's brand context, the voice its listing copy is written in. Asks whether it is an artist site or a product site, interviews the owner (or splits an existing style guide into the right sections), records meanings the artist confirms for one artwork, a series or the whole catalog, and reviews the lessons the learning loop proposes from the owner's edits. Use whenever someone wants to set up the voice, explain what a painting or series means, add or retire a phrase to watch, approve examples, or review what the system has learned from their edits.
argument-hint: "<storefront id> [interview | meaning | lessons | import <file>]"
---

# Brand context

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md)

The brand context is the storefront's voice, kept apart from the writing craft in the listing-copy
skill so it can grow without anyone editing a skill. Contract: `brand-context`
(`packages/contracts/schemas/brand-context.schema.json`). It holds the artist's or brand's own words,
so it lives in gitignored `config/brand/<storefront-id>.local.json`, with every earlier version in
`config/brand/history/`.

## Inputs

- The storefront ID, and its entry in `config/storefronts.local.json` (for `site_kind`).
- The owner's answers, or an existing style guide the owner points to.
- For lessons: proposed lessons in the brand context and the edit records they cite
  (`.commerce-os/learning/edits.jsonl`).

## Outputs

- A new version of `config/brand/<storefront-id>.local.json`, the previous one archived as
  `config/brand/history/<storefront-id>.v<N>.json`.
- A short summary of what changed.

## Allowed tools

Read in the working directory; Write and Edit on `config/brand/` only.

## Forbidden actions

- Writing a meaning the owner did not state. A model's reading is a proposal on a draft, never a
  confirmed meaning.
- Widening a meaning's scope beyond what the owner said ("this fox" is not "every fox").
- Approving a lesson or example on the owner's behalf.
- Editing a previous version in place, or deleting history.
- Copying the brand context into any committed file.

## Workflow

1. **Site kind.** If the storefront entry has no `site_kind`, ask: "Is this an artist site (one
   artist's own work) or a product site (a brand selling goods)?" Record the answer in both the
   storefront entry and the brand context.
2. **Interview** (new context), or **import** (the owner has a guide: split it into the sections
   below, and show what went where). The questions depend on the site kind:
   - **Artist:** the artist's name and how often it may appear; the idea behind the work, in their own
     words; the two or three kinds of work and how each should be written about; what recurring
     subjects or backgrounds mean; style words they accept and reject; phrases they are tired of.
   - **Product:** the brand name and audience; the brand story; product lines and what matters for
     each (use, feel, fit, care); claims the brand can and cannot make; words to avoid.
   - **Both:** length targets for the short and long descriptions.
3. **Meaning.** Record what the owner says about one artwork, a series or the whole catalog. Ask the
   scope when it isn't clear. Each meaning records who said it and when.
4. **Lessons.** Show each proposed lesson with the before-and-after edits it came from. The owner
   approves, rewrites or rejects each one. Only approved lessons reach the prompt.
5. **Examples.** Proposed examples are shown for approval the same way.
6. Bump `version`, archive the previous version, validate against the contract, write.

## Validation

- The document validates against `brand-context.schema.json`.
- `version` is one more than the archived previous version.
- Every meaning has a scope, and a catalog-wide meaning has no ref.

## Failure behavior

Validation fails: write nothing, show the error, keep the previous version. The owner declines a
question: leave that section empty rather than guessing.

## Evidence requirements

Every meaning and approved lesson is the owner's statement: record `recorded_by` and the time. A
lesson cites the edit records it came from.

## Current status

Runnable locally: this skill, and the Brand context and Learning pages of the local review dashboard,
edit the same file. Moves to the operational database with the dashboard (Phase 2).
