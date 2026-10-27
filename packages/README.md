# packages/

Shared libraries. Contracts exist; everything else is Phase 1 onward.

- `contracts/`: JSON Schema contracts for every document between pipeline stages, shared by the
  Python backend and the TypeScript dashboard. Written (B-020); see [contracts/README.md](contracts/README.md).
- `policy/`: evidence policy, transition whitelist, approval binding checks.
- `image-pipeline/`: validation and versioned transform recipes.
- `adapters/storefront-a/`, `adapters/storefront-b/`: one adapter per storefront, never shared code paths for SQL or mappings.
