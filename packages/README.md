# packages/

Shared libraries. Contracts exist; everything else is Phase 1 onward.

- `contracts/`: JSON Schema contracts for every document between pipeline stages, shared by the
  Python backend and the TypeScript dashboard. Written (B-020); see [contracts/README.md](contracts/README.md).
- `policy/`: whether a contract document is acceptable (B-043). `validate(doc, related, expected=...)`
  runs the schema, then the rules schemas can't express: product-type option rules, unique option
  combinations, each image grouped once, no self-approval, and approval bindings. `approvals.py` is
  the single definition of the bindings; the adapters call it, and migration 0007's trigger binds the
  same fields (a test pins all three). Transition rules stay in the database (migration 0003).
- `image_pipeline/`: versioned derivative recipes. `framing.py` builds the framed listing image (B-050):
  `layout()` is pure arithmetic; `render()` uses Pillow. The artwork is only resized, and the original
  is never written. Try it with `.venv/bin/python scripts/frame_artwork.py <image>`. `crop.py` proposes a
  straightened crop of the artwork in a photo, with a review image and a confidence check (B-053).
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
