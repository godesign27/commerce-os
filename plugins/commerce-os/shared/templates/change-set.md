---
type: change-set
submission_id: <logical submission id>
destination: storefront-a | storefront-b
canonical_revision: <n>
mapping_version: <mapping id@version>
asset_manifest_hash: <sha-256>
change_set_hash: <sha-256 of the operations block, computed by the workflow service>
status: draft
created: <ISO-8601>
simulated: true
---

# Change set — <destination> — <working title>

> One destination per change set. A change set is immutable once approved; any edit produces a new
> change set and invalidates the old approval.

## Requested destination status

<hidden draft / visible> — stated explicitly. Never implied.

## Operations

| # | Operation | Entity | Key | Precondition | Fields |
|---|---|---|---|---|---|
| 1 | create | product | <external reference> | must not exist | <field list> |

## Field diff

| Entity | Field | Before (live) | After (proposed) | Source status |
|---|---|---|---|---|
| product | title | — | <value> | human_confirmed |

## Assets

| Asset | Derivative | Destination key | Already delivered? |
|---|---|---|---|
| <id> | <recipe@version> | <key> | no |

## Not touched

Storefront-owned fields this change set deliberately leaves alone (stock, price unless approved here).

## Blockers

Anything that prevents approval, with the field and the evidence needed.
