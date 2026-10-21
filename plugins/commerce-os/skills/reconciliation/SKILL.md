---
name: reconciliation
description: Verify what actually happened at one storefront after a publication attempt — read-after-write comparison against the approved change set, recovery of OUTCOME_UNKNOWN attempts, and detection of remote mismatches — and report queued, unknown, failed and verified-success states distinctly. Use whenever someone asks "did it publish", "is it live", about a timeout, a partial publish, or a mismatch between the dashboard and a storefront.
argument-hint: "<submission id> <storefront-a|storefront-b>"
---

# Reconciliation

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Workflow: [WORKFLOW.md](../../shared/WORKFLOW.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)

A timeout after a write may mean the write happened. Retrying a create without checking can duplicate
a product. Reconciliation reads the destination, compares it with the approved change set, and says
what is true (PRD §16).

## Inputs

- One destination; its publication attempts, receipts and the approved change set, from `~~workflow`.

## Outputs

Per destination: verified state (`SUCCEEDED`, `FAILED`, `OUTCOME_UNKNOWN`, `QUEUED`, `WRITING`), each
operation's match or mismatch against the live record, and the recommended next action for an operator.

## Allowed tools

Read-only `~~workflow` calls, including read-only destination lookups by external reference; Write
under `.commerce-os/out/` only.

## Forbidden actions

- Retrying, rolling back, or deleting anything. Recovery actions are operator decisions in the
  dashboard.
- Marking `SUCCEEDED` without a read-after-write match.
- Letting one storefront's outcome change the other's state.

## Workflow

1. Load attempts and receipts for the destination.
2. For each operation, look up the live record by external ID or the change set's unique external reference.
3. Compare live fields with the approved values.
4. All match: `SUCCEEDED (verified)`. Record found but different: mismatch, list fields. Not found
   after an unknown outcome: still `OUTCOME_UNKNOWN` until an operator decides; recommend a safe
   recheck before any retry.
5. Report each destination separately; derive nothing across them.

## Validation

Every operation in the change set has a reconciliation result.

## Failure behavior

Destination unreachable: leave the state as it is, record that reconciliation could not run, and
recommend retrying reconciliation, not publication.

## Evidence requirements

Each verdict cites the receipt and live-record IDs compared.

## Phase 0a status

Not runnable: no publication attempts exist.
