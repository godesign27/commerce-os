# Workflow: states, gates, and transitions

Canonical reference for agents (PRD §13–§14). Agents read this to explain status and blockers. They
never set a state: only the workflow service moves state, through validated transitions that check the
expected revision and state, the actor's permission, and record a reason and an audit event.

## Submission states

```text
RECEIVED → WAITING_FOR_READY → SNAPSHOTTED → ASSETS_PROCESSING
→ PRODUCT_ANALYSIS → DRAFTING → VALIDATING → IN_REVIEW
→ READY_FOR_APPROVAL → APPROVED → PUBLISHING
→ PUBLISHED | PARTIALLY_PUBLISHED
```

Side states: `NEEDS_INPUT`, `RETRY_WAIT`, `FAILED`, `REJECTED`, `CANCELLED`, `SUPERSEDED`.

| From | To | Trigger |
|---|---|---|
| `IN_REVIEW` | `NEEDS_INPUT` | A required fact is missing; a human must supply it. |
| `NEEDS_INPUT` | `IN_REVIEW` | The fact was supplied. |
| `IN_REVIEW`, `READY_FOR_APPROVAL`, `APPROVED` | `VALIDATING` | A reviewer edit. Affected approvals are invalidated. |
| Any pre-publish state | `SUPERSEDED` | A new source snapshot replaced this draft. |
| Any processing state | `RETRY_WAIT` | Retryable failure; resumes the failed checkpoint on a bounded schedule. |
| Any processing state | `FAILED` | Terminal validation or permission failure, with a recovery action. |
| Any pre-publish state | `REJECTED`, `CANCELLED` | Human decision. In-flight external writes are still reconciled. |

## Per-destination publication states

Each storefront is tracked separately; the submission's aggregate status is derived from these.

`NOT_SELECTED` · `DRAFT` · `BLOCKED` · `AWAITING_APPROVAL` · `APPROVED` · `QUEUED` · `WRITING` ·
`VERIFYING` · `SUCCEEDED` · `FAILED` · `OUTCOME_UNKNOWN` · `CANCELLED`

There is no atomic transaction across the two storefronts. A success at one is never undone because
the other failed. `QUEUED` is not published; only `SUCCEEDED` after verification is.

## Gates

| Gate | Passes when | Who |
|---|---|---|
| 1. Ready for review | Snapshot complete, required validation run, draft and issues persisted. | Workflow service |
| 2. Product and asset acceptance | Required facts, grouping, identity and asset changes resolved. | Reviewer |
| 3. Destination publication approval | Exact operations approved per storefront, including status and commercial fields. | Publisher/approver |
| 4. Execution revalidation | Approval valid; revision, payload hash, mapping version, permission and destination preconditions unchanged. | Publishing worker, immediately before writing |

An approval binds: actor, time, destination, canonical revision, asset-manifest hash, mapping version,
and change-set hash. Any material edit or new source revision invalidates the affected approvals.
Stale approvals are rejected, never re-pointed at a regenerated payload. A global kill switch stops new
writes without discarding jobs or audit history.
