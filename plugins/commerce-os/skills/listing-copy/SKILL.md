---
name: listing-copy
description: Write the title, short description, collector description, store tags and search keywords for one product or artwork in the storefront's own voice, from the image, the storefront's brand context and any meaning the artist or owner supplied. Returns three title options with a recommendation, separates what is visible from what is confirmed and what is a proposed reading, lists questions for the artist, and scores itself against a rubric. Use whenever someone asks to name an artwork, write or rewrite a description, make the copy sound like the artist, redraft with a note, or check copy for repetition.
argument-hint: "<review item id | image path> [note]"
---

# Listing copy

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md) · Workflow: [WORKFLOW.md](../../shared/WORKFLOW.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)

The copy part of a canonical draft (canonical-drafting step 3). The craft is in two references, read
in full before writing: [writing-standards.md](references/writing-standards.md) and
[rubric.md](references/rubric.md). Everything about one storefront's voice is in its brand context,
not here, so the artist's philosophy can change without editing this skill.

## Inputs

- The artwork or product image the listing will use (the accepted crop, rotated), never a mockup.
- The storefront's brand context: `config/brand/<storefront-id>.local.json` (contract
  `brand-context`). Its `site_kind` decides the frame: `artist` (meaning, the artist's intent) or
  `product` (use, feel, fit).
- Confirmed meanings that apply to this item: its own, its series', and catalog-wide ones. No others.
- Supplied facts for the item, if any: edition (original or print), medium, dimensions, series.
- The reviewer's note for this item, if any, treated as `supplied`.
- Catalog memory: titles already taken and openings of recent approved descriptions.
- The store's tag list from `config/mappings/<storefront-id>.local.json`.

## Outputs

One structured result (the drafting service's `listing-draft@4` schema), mapped onto a canonical
draft revision:

- `category` with confidence; `moment` with basis `confirmed` or `proposed`.
- `subject_name`: the animal or character shown, as a shopper would search for it ("" for abstracts).
- Three `title_options`, each with a rationale, and `recommended_title`. When there is a
  `subject_name`, every title contains it, so a search for "lion" finds the lion.
- `short_description` (concise, for browsing) and `collector_description` (a small human story grounded
  in this piece: an encounter, two or three visible details, a resonant close).
- `store_tags` (existing only), `proposed_store_tags` (at most 3), `search_keywords` (10 to 12).
- `observations` (visible), `interpretations` (each with its basis), `ask_artist` (questions).
- `self_review` scores; the service adds the automatic checks as review issues.

## Allowed tools

Read on the image, brand context, mappings and drafts; Write under `.commerce-os/` only. The brand
context is changed only through the brand-context skill or the dashboard, never by this skill.

## Forbidden actions

- Treating a proposed reading as the artist's intent, or applying a meaning outside its scope.
- Stating medium, size, edition, originality or how it was made without a supplied fact.
- Overwriting copy a human approved. A redraft is a new revision; approved copy changes only when the
  reviewer unlocks it.
- Writing to the brand context, including adding lessons or meanings. Those come from humans.
- Publishing, or marking copy approved.

## Workflow

1. Load the brand context and validate it against the contract; record its `version`.
2. Collect the confirmed meanings in scope for this item and the reviewer's note.
3. Follow the process in [writing-standards.md](references/writing-standards.md): inspect, category,
   moment, three titles, recommendation, descriptions, tags, keywords.
4. Separate every statement into visible, confirmed or proposed; every proposed reading gets an
   `ask_artist` question.
5. Score the copy against [rubric.md](references/rubric.md) and revise anything under 2 that can be
   fixed without inventing facts. Ask of the collector description: "Does this read like a small human
   story grounded in this particular piece, or like a visual inventory or generic art advertisement?"
6. Return the result. The drafting service runs the automatic checks and writes the canonical draft
   with the brand context version in `policy_versions`.

## Validation

- Every confirmed interpretation cites a meaning in scope; nothing else is marked confirmed.
- Store tags are a subset of the store's tag list.
- Recommended title is not already taken; the three options do not share their main word (the
  subject's name doesn't count); every option names the animal or character shown.
- Lengths are inside the brand context's `length` targets.

## Failure behavior

No brand context for the storefront: draft with the writing standards alone, add a warning that the
copy has no brand voice, and suggest `/brand-context <storefront-id>`. Image missing or unreadable:
stop and say so.

## Evidence requirements

Title and descriptions are `inferred`, citing the image asset. A confirmed meaning used in the copy is
cited by its meaning ID in `interpretations`. A reviewer's note is `supplied`. Edits a reviewer makes
become `human_confirmed` when the copy is approved.

## Current status

Runnable locally. `scripts/draft_listings.py` drafts a batch with the Claude API; the local review
dashboard (`apps/review-dashboard`) shows the drafts for editing, redrafting with a note and approval.
Approved copy and the reviewer's edits feed the learning loop (brand-context skill).
