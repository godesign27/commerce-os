# services/

Server-side runtime. Phase 1 onward; nothing here yet.

- `workflow/`: the deterministic workflow service; the only component that moves state.
- `workers/`: durable job workers, including the publishing worker (Gate 4, write credentials).
- `drive-events/`: Google Drive notification receiver and reconciliation scan (Phase 2).
