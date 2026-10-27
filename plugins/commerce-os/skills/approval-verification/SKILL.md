---
name: approval-verification
description: Check whether a recorded human approval still matches the exact change set it approved — actor and permission, destination, canonical revision, asset-manifest hash, mapping version and change-set hash — and report whether it is valid, stale or missing. Use whenever someone asks if a product is approved, whether an approval still holds after an edit, or why publication was refused.
argument-hint: "<submission id> <storefront-a|storefront-b>"
---

# Approval verification

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Workflow: [WORKFLOW.md](../../shared/WORKFLOW.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)

An approval is a human's consent to one exact payload. If anything material changed afterwards, the
approval no longer applies, and the right answer is a new review, not a regenerated payload under the
old approval (PRD §13).

This skill **reports**. The authoritative check is Gate 4, run by the server-side publishing worker
immediately before writing. A report from this skill is never a substitute for it.

## Inputs

- The approval record for one destination, from `~~workflow`.
- The current change set, canonical revision, asset manifest and mapping version for that destination.

## Outputs

A verdict per destination: `valid`, `stale` (with each mismatched binding), `missing`, or
`not_authorized` (actor lacks the approver role), plus what would make it valid.

## Allowed tools

Read-only `~~workflow` calls; Read on local outputs; Write under `.commerce-os/out/` only.

## Forbidden actions

- Creating, editing, extending or re-pointing an approval.
- Treating a chat message ("yes, approve it") as an approval.
- Reporting `valid` when any binding could not be checked.

## Workflow

1. Fetch the approval for the destination. None: `missing`.
2. Compare each binding: destination, canonical revision, asset-manifest hash, mapping version,
   change-set hash. Any difference: `stale`, listing each.
3. Check the actor held the approver role at approval time, and is not the agent or service that
   prepared the change set.
4. Check the kill switch. If writes are disabled, say so regardless of verdict.

## Validation

The verdict lists every binding checked and its result.

## Failure behavior

Any binding unavailable: verdict `stale` with "could not verify <binding>". Never default to valid.

## Evidence requirements

Each comparison cites the record IDs compared.

## Current status

Not runnable: no approval records exist without the workflow service.
