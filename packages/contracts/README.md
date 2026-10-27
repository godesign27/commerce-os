# Contracts

JSON Schema (draft 2020-12) definitions for every document that passes between pipeline stages. They
are the shared language of the Python backend and the TypeScript dashboard (BACKLOG B-009, B-020):
both validate against these files, and neither defines its own shapes.

The markdown templates in `plugins/commerce-os/shared/templates/` are human-readable renderings of the
same documents, for local Phase 0 output. When they disagree, these schemas win.

## Documents

| Schema | Produced by | What it is |
|---|---|---|
| `source-manifest` | drive-intake, asset-validation | Immutable snapshot of one submission: files, real types, checksums, supplied metadata, findings |
| `derivative-manifest` | image-preparation | Image derivatives with recipe versions and content-addressed keys |
| `product-proposal` | product-classification, variant-grouping, catalog-retrieval | Product type, grouping of images into products and variants, visible attributes, catalog candidates |
| `canonical-draft` | canonical-drafting | The storefront-neutral draft at one revision; no price, stock or destination status |
| `change-set` | destination-mapping | Exact operations for one storefront and environment, with preconditions |
| `approval` | the dashboard (Gate 3) | A human approver's binding to one exact change set |
| `review-package` | review-packaging | Blockers, images, decisions needed, previews, questions |
| `reconciliation-report` | reconciliation | Read-after-write verdict per operation at one storefront |

`common.schema.json` holds the shared definitions: the field evidence record, money, dimensions,
actors, review issues and the publication states.

## Rules the schemas enforce

- **Field evidence (evidence policy):** `unknown` and `conflicting` fields have a null value;
  observed, supplied, verified and inferred values need at least one evidence reference;
  `human_confirmed` needs a recorded decision.
- **Commercial facts** (price, stock, SKU, GTIN, material, brand, vendor, dimensions) can never be
  `observed` or `inferred`. In a change set they must also be non-null.
- **Money** is integer minor units plus a currency code, never a float. Adapters convert to each
  storefront's own representation (both current storefronts store dollars as `numeric(10,2)`).
- **The canonical draft has no price, stock or destination status**: those exist only in change sets.
- **A change set** targets one storefront and environment, states `requested_status` explicitly,
  requires `must_not_exist` on creates and `expected_row_hash` on updates, and a destination
  `status` value must be human-confirmed.
- **An approval** comes from a human with the approver role, and binds the change-set hash,
  canonical revision, asset manifest, mapping version and schema fingerprint.
- **Crop and background removal** derivatives are always marked consequential.
- **A reconciliation report** can only claim `SUCCEEDED` when every operation matched.

## Rules the schemas can't express

These are implemented in `packages/policy` (BACKLOG B-043). Their cases in
`tests/fixtures/contracts/invalid.json` (`semantic_cases`) are the specification:

- A color option exists only when the product type's `options.color` is `allowed`.
- No two variants of a product share the same option values, and each value is in its option definition.
- Each image is grouped exactly once.
- The approver didn't prepare the change set, and every approval binding equals its change set's.

## Versioning

Every document carries `contract` and `contract_version`. A breaking change bumps `contract_version`
and needs a migration note here. Fixtures live in `tests/fixtures/contracts/`: `valid/` documents for
every schema, and `invalid.json`, a list of patches that must each fail for a stated reason.

## Validating

`packages/policy.validate(doc, related, expected=...)` is the one entry point: the document's schema
first, then the semantic rules. It runs schemas with `packages/contracts/validator.py`, a strict stdlib
validator that supports exactly the keywords these schemas use. The suite fails if a schema uses any
other keyword, so nothing is silently ignored. The TypeScript dashboard validates the same schemas with
Ajv. If the Python backend takes on dependencies, the `jsonschema` library can replace the stdlib
validator without changing a schema.
