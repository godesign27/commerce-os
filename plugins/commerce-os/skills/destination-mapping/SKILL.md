---
name: destination-mapping
description: Translate a canonical draft into one storefront's schema, categories and enums using that storefront's versioned mapping, add destination-only values with their sources, and compute the exact proposed operations as a change set with a field-level diff. Use whenever someone asks how a product will look in a storefront, what fields a storefront needs, to map categories or options, or to prepare the change set.
argument-hint: "<submission id> <storefront-a|storefront-b>"
---

# Destination mapping

> Context: [COMMERCE-CONTEXT.md](../../shared/COMMERCE-CONTEXT.md) · Evidence: [evidence-policy.md](../../shared/evidence-policy.md) · Workflow: [WORKFLOW.md](../../shared/WORKFLOW.md) · Connectors: [CONNECTORS.md](../../shared/CONNECTORS.md)
> Output template: [change-set.md](../../shared/templates/change-set.md)

Each storefront has its own schema, enums, required fields and rules. Mapping happens once per
destination, from its own mapping specification, and nothing crosses from one storefront to the other.

## Inputs

- The canonical draft at a specific revision.
- Exactly one destination and its mapping from `resources/storefront-mappings/<destination>/` (versioned).
- Destination-only values (price, currency, availability, requested visibility) with their sources:
  `supplied` by the submission or `human_confirmed`. Never from the other storefront.

## Outputs

One change set for that destination: requested status stated explicitly, operations with
preconditions, field diff against the live record (for updates), asset delivery list, fields
deliberately not touched, blockers. Recorded mapping version and canonical revision.

## Allowed tools

Read on the draft and mappings; read-only `~~workflow` lookups for the live record when planning an
update; Write under `.commerce-os/out/` only.

## Forbidden actions

- Reusing one storefront's mapping, SQL, enum values or destination values for the other.
- Including stock or price changes the change set doesn't explicitly list for approval.
- Planning an update without an expected version or hash precondition.
- Computing or editing a `change_set_hash` by hand; the workflow service computes it.

## Workflow

1. Load the destination's mapping; record its version.
2. Map category and option values to the destination's enums. Unmapped value: blocking issue.
3. Add destination-only fields with their sources. Missing required ones: blocking issue.
4. Money is integer minor units plus currency, or exact decimal. Never floating point.
5. Create-first (B-007): an update to an existing product needs human-confirmed identity and a
   precondition on the live record's version.
6. List assets that must be delivered before the product references them.
7. List storefront-owned fields left untouched.

## Validation

The change set names one destination. Every mapped value comes from that destination's mapping. Every
destination value has a source.

## Failure behavior

Mapping missing or stale for the category: stop, raise a blocking issue for the administrator.

## Evidence requirements

Destination values follow the evidence policy for that destination only.

## Phase 0a status

Not runnable: storefront schemas and mappings are unknown (B-001, B-015).
