# packages/

Shared libraries. Contracts exist; everything else is Phase 1 onward.

- `contracts/`: JSON Schema contracts for every document between pipeline stages, shared by the
  Python backend and the TypeScript dashboard. Written (B-020); see [contracts/README.md](contracts/README.md).
- `policy/`: evidence policy, transition whitelist, approval binding checks.
- `image-pipeline/`: validation and versioned transform recipes.
- `adapters/`: the adapter contract (PRD §15) and the in-memory fake (B-019).
  - `contract.py`: the interface (`capabilities`, `read_catalog`, `validate`, `plan`, `dry_run`,
    `publish_approved`, `reconcile`) and the storefront-neutral guards every adapter runs: the sealed
    change-set hash, approval bindings, human approver and no self-approval.
  - `fake.py`: `FakeStorefront`, a stand-in that never touches a real store. It's built from the same
    structure snapshot and seed as the local database stand-in (`database/storefronts/`), and enforces
    the kill switch, preconditions, explicit status, known columns and atomic writes. It can be told
    to fail before writing, or to lose the response after writing (`OUTCOME_UNKNOWN`).
  - `tests/test_adapter_contract.py` is written against the interface only. Each real adapter
    (`adapters/storefront-a/`, `adapters/storefront-b/`, Phase 3) must pass it, and never shares
    SQL or mapping code with another storefront's adapter.
