---
name: listing-edit
description: Change a drafted listing's title, short description, collector description, store tags or search keywords on the owner's instruction, in plain words ("change the wolf's title to The Wolf's Gaze", "use this description instead", "go back to the drafted title"). Saves the owner's exact words to the same local files the review dashboard uses, runs the claim and repetition checks on what was saved, and reports them. Use whenever someone wants to set, pick, replace or revert listing copy from Claude Code rather than the dashboard. Not for writing new copy (that is listing-copy) or recording what a piece means (that is brand-context).
argument-hint: "<listing> <what to change>"
---

# Listing edit

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md)

The owner's words, saved as they gave them. This skill is a typist, not a writer: it never rewrites,
polishes or completes the text it was given. The engine is `scripts/listing_edit.py`, which goes
through the same code as the dashboard's Save buttons (`packages/drafting/editing.py`), so both apply
the same lock and the same checks.

## Inputs

- Which listing: an item ID, or words from its title or file name ("the wolf").
- Which field: title, short (description), collector (description), tags, keywords.
- The new text, a title option number, or "go back to the draft".

## Outputs

- The saved field in `.commerce-os/review/listings.json`, as an edit on top of the current draft.
- The checks on what was saved, and the dashboard link for the listing.

## Allowed tools

Bash, to run `.venv/bin/python scripts/listing_edit.py` only. Read in the working directory. No Write
or Edit: every change goes through the script.

## Forbidden actions

- Changing the owner's text: no rewording, fixing, shortening or adding, even to clear a check. If a
  check flags it, report the check and let the owner decide.
- Editing a field the owner didn't name.
- Unlocking approved copy, approving copy, redrafting, or calling a model. Those happen on the dashboard.
- Guessing between several matching listings.
- Publishing, or writing to any storefront.
- Recording a meaning. "The wolf means patience" is brand-context (`/brand-context`), not an edit.

## Workflow

1. **Find the listing.** Run `listing_edit.py find <words>`. One match: go on. Several: list them and
   ask which. None: say so and stop.
2. **Read it back.** Run `listing_edit.py show <id>` when the request depends on what's there now ("the
   second title", "keep the first sentence"). Skip it for a plain replacement.
3. **Save.** One field per call:
   - New text: `listing_edit.py set <id> <field> --file -`, with the owner's exact text on stdin
     (avoids quoting problems with apostrophes and quotation marks). A short title can go inline.
   - A drafted title: `listing_edit.py choose <id> <n>`.
   - Back to the draft: `listing_edit.py revert <id> <field|all>`.
4. **Report.** Say what was saved, quote any checks the script printed, and give the dashboard link.
   A blocking check (an unsupported claim, a title already in use) is saved anyway: say it will need
   fixing or a supplied fact before the copy is approved.

## Validation

- The script exits 0 and prints "Saved …" (or "Back to the draft …").
- What was saved is the owner's text, character for character apart from surrounding whitespace.

## Failure behavior

- Exit 1 because the copy is approved: tell the owner to unlock it on the dashboard; change nothing.
- Exit 1 for any other reason: show the message; change nothing.
- Exit 2: no single listing matches; list the candidates and ask.
- No drafts yet: the listing has to be drafted first (`scripts/draft_listings.py` or the dashboard).

## Evidence requirements

An edit is the owner's own text. It stays an edit on the draft until the owner approves the copy on the
dashboard; approval records the before and after for the learning loop.

## Current status

Runnable locally (B-059). Uses the same files as the local review dashboard. Moves to the operational
database with the dashboard (Phase 2).
