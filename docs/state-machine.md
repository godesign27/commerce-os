# State machine

The canonical states, gates and transitions are in
[plugins/commerce-os/shared/WORKFLOW.md](../plugins/commerce-os/shared/WORKFLOW.md), so agents and
developers read the same definition. This page adds only what the implementation must enforce.

## Enforcement requirements (Phase 1)

- Transitions are a whitelist in `packages/policy`. Anything not listed is rejected.
- Every transition is a compare-and-set on `(state, revision)` in the operational database, inside
  the same transaction that writes its audit event and any outbox job.
- Transitions record actor (human or service identity), reason and the triggering record.
- Per-destination publication state is a separate row per storefront; the submission's aggregate
  status is derived, never stored independently.
- Approval invalidation is triggered by the transition into `VALIDATING` and by `SUPERSEDED`.
- Agents have no transition API. They submit proposals; the workflow service decides the transition.
