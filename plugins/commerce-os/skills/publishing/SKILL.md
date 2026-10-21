---
name: publishing
description: Run a publishing dry run for one storefront's change set, or request server-side publication of a change set a human has already approved — never write directly. Use whenever someone says dry run, preview the publish, publish, push live, send to the storefront, or asks what publishing would change.
argument-hint: "<submission id> <storefront-a|storefront-b> [--dry-run]"
---

# Publishing

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Workflow: [WORKFLOW.md](../../shared/WORKFLOW.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)

Publishing has two modes, and an agent can only ever do the first one itself:

- **Dry run:** show exactly what the adapter would do for one destination, with no side effects.
- **Request:** ask the workflow service to queue an already-approved change set. The server-side
  worker then runs Gate 4 and performs the write. The agent never holds write credentials.

## Inputs

- One destination and its change set.
- For a request: an approval verdict of `valid` from approval-verification.

## Outputs

- Dry run: the adapter's plan, preconditions, validation results, and what would be written, marked
  `dry_run: true`.
- Request: the job ID and the destination's state (`QUEUED`), and a note that queued is not published.

## Allowed tools

Read on local outputs; `~~workflow` dry-run and publication-request calls only; Write under
`.commerce-os/out/` only.

## Forbidden actions

- Any direct write to a storefront database, asset store, or API.
- Requesting publication without a `valid` approval for that exact change set.
- Changing the change set to fix a dry-run failure. Fixes produce a new change set needing new approval.
- Publishing both storefronts as one operation, or undoing one because the other failed.
- Reporting anything other than verified `SUCCEEDED` as published.

## Workflow

1. Confirm one destination is named. "Both" means two separate runs.
2. **Dry run:** call the adapter's dry run through `~~workflow`. Report the plan and every failed
   precondition. Stop.
3. **Request:** run approval-verification. Anything but `valid`: stop and explain.
4. Request the job through `~~workflow`. Report the job ID and `QUEUED`.
5. Tell the user how to check the outcome (reconciliation), and that the dashboard shows it.

## Validation

A dry run reports `dry_run: true` and no receipt IDs. A request reports exactly one job per destination.

## Failure behavior

Workflow interface unavailable: stop. Never fall back to any other route to the storefront.

## Evidence requirements

None asserted; this skill reports adapter and workflow results verbatim.

## Current status

Not runnable: no workflow interface or adapter exists. The command `/publish` explains this and stops.
