# services/

Server-side runtime.

- `local_api/`: a local stand-in for the workflow service's API, for the review dashboard (B-057). Local
  files only, 127.0.0.1 only, never writes to a storefront. Replaced by `workflow/` in Phase 2.
- `workflow/`: the deterministic workflow service; the only component that moves state.
- `workers/`: durable job workers, including the publishing worker (Gate 4, write credentials).
- `drive-events/`: Google Drive notification receiver and reconciliation scan (Phase 2).
