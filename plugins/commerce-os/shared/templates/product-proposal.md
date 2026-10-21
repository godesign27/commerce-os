---
type: product-proposal
submission_id: <logical submission id>
source_snapshot_id: <snapshot id>
revision: 1
status: draft
policy_versions: [evidence-policy@<v>, category-templates@<v>]
created: <ISO-8601>
updated: <ISO-8601>
simulated: true
---

# Product proposal — <working title>

## Category

| Proposed category | Status | Evidence | Confidence | Alternatives |
|---|---|---|---|---|
| <category id> | observed / inferred | <asset refs> | <0–1> | <other candidates> |

## Grouping

How the submitted images map to products, views and variants. Each image appears exactly once.

| Asset | Product | Role | Variant | Reason |
|---|---|---|---|---|
| <asset id> | P-1 | primary / gallery / detail / swatch | V-1 | <why this grouping> |

## Option definitions

| Axis key | Display label | Values (normalized) | Evidence |
|---|---|---|---|
| color | Color | <values> | <asset refs> |

## Variants

| Variant | Option values | SKU | GTIN | Assets | Evidence |
|---|---|---|---|---|---|
| V-1 | color=<value> | null (unknown) | null (unknown) | <asset ids> | <refs> |

## Fields

Every factual field uses the record shape from `evidence-policy.md`. Unknown stays `null`.

| Field | Value | Status | Evidence | Method | Blocking? |
|---|---|---|---|---|---|
| title | <draft or null> | inferred | <refs> | <model@version> | no |
| material | null | unknown | — | — | yes, if required by destination |

## Catalog candidates

Listed per storefront, never merged. Similarity informs structure only.

| Storefront | Candidate | Matching evidence | Conflicting evidence | Proposed use |
|---|---|---|---|---|
| A | <external id> | <evidence> | <evidence> | structure only / possible same product (needs human) |

## Review issues

| ID | Severity | Field or asset | Question for the reviewer |
|---|---|---|---|
| RI-1 | blocking / warning | <target> | <question> |
