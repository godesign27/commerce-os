# packages/

Shared libraries. Phase 1 onward; nothing here yet.

- `contracts/`: machine-readable schemas for skill inputs and outputs (BACKLOG B-020).
- `policy/`: evidence policy, transition whitelist, approval binding checks.
- `image-pipeline/`: validation and versioned transform recipes.
- `adapters/storefront-a/`, `adapters/storefront-b/`: one adapter per storefront, never shared code paths for SQL or mappings.
