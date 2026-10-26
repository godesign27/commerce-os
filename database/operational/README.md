# Operational database

Commerce OS's own database (PRD §5, §8.3): submissions, snapshots, drafts, field evidence, jobs,
change sets, approvals, publication receipts and the audit trail. It lives in its own Supabase project
(BACKLOG B-009, B-042), separate from every storefront's project, including Storefront A's. Storefront schemas are never
migrated from here.

**Status: draft migrations, tested on Supabase.** They pass the static checks in
`tests/test_operational_schema.py`, and on 2026-10-26 applied cleanly to the CommerceOS Supabase
project with all 30 smoke checks passing, inside a rolled-back transaction (B-044). They haven't
been applied for real yet; that happens when Phase 1 code needs them.

## Migrations

| File | What it creates |
|---|---|
| `0001_foundation.sql` | `commerce_os` schema, tenants, the kill switch (writes start disabled), shared trigger functions |
| `0002_configuration.sql` | Connections (secret references only), storefronts, versioned product types and mappings |
| `0003_state_machines.sql` | Submission and per-destination publication states and allowed transitions, as data |
| `0004_intake.sql` | Notification inbox, Drive channels, submissions, immutable snapshots, files, blobs, derivatives |
| `0005_drafts.sql` | Proposals, canonical products and variants, field evidence, review issues, catalog candidates |
| `0006_destinations.sql` | Identity links, sealed change sets, per-destination publication state |
| `0007_review_and_approval.sql` | Append-only reviews; approvals bound to a sealed change set |
| `0008_jobs_publication_audit.sql` | Jobs with leases, attempts, outbox, publication attempts and receipts, append-only audit |
| `0009_tenant_isolation.sql` | Forced row-level security on every table with a `tenant_id` |

Each migration is forward-only. Change an applied migration only by adding a new one.

## What the database itself guarantees

These hold even if application code has a bug (PRD §8.3: "in the database, not only application code").

| Guarantee | How |
|---|---|
| States move only along allowed transitions, with an actor and reason, and are audited | `enforce_transition` trigger + transition tables; `audit_state_change` trigger |
| Approval can't be skipped | The only way into `APPROVED` is from `READY_FOR_APPROVAL` / `AWAITING_APPROVAL` |
| In-flight writes are reconciled, never cancelled | No transition from `WRITING`, `VERIFYING` or `OUTCOME_UNKNOWN` to `CANCELLED` |
| Concurrent edits conflict instead of overwriting | `require_next_revision`: every update must advance `revision` by exactly one |
| No duplicate work from repeated events | Unique notification, intake, image, job and publication keys |
| Competing workers never take the same job | `claim_job()` with `FOR UPDATE SKIP LOCKED` and leases |
| Unknown facts have no value; commercial facts are never observed or inferred | `field_evidence` CHECK constraints (evidence policy) |
| Variants have unique option combinations | Generated `option_values_key` + unique constraint |
| No price, stock or destination status in the canonical draft | `products` / `variants` have no such columns |
| A sealed change set never changes | `protect_sealed_change_set` trigger |
| Only a human approver approves, never their own change set, and only the exact payload | CHECKs on `approvals` + `check_approval_bindings` trigger |
| Approvals are never edited or deleted; they can be invalidated once | `protect_approval` trigger |
| Snapshots, evidence, reviews, receipts and audit rows are append-only | `forbid_mutation` triggers |
| No credential is stored | `connections.secret_ref` holds a secret's name; its format rejects URLs |
| Tenants can't see or write each other's rows | Forced RLS on `commerce_os.tenant_id` |
| Storefront writes start disabled | `system_settings.writes_disabled` defaults to `true` |

Blobs are content-addressed and shared, so they carry no `tenant_id`. Access to them always goes through a
tenant-scoped `source_files` or `asset_derivatives` row, and storage keys are private.

## Using it from the service

Every transaction sets the tenant, then uses compare-and-set updates:

```sql
SET LOCAL commerce_os.tenant_id = '<tenant uuid>';
UPDATE commerce_os.submissions
   SET state = 'SNAPSHOTTED', state_reason = 'ready manifest found',
       state_changed_by = 'service:drive-events', revision = revision + 1
 WHERE submission_id = $1 AND revision = $2;   -- 0 rows updated = someone else changed it first
```

## Testing

- `./run-tests.sh` runs the static checks every time.
- `python3 scripts/test_operational_db.py` applies all migrations plus
  [tests/smoke.sql](tests/smoke.sql) to a real Postgres 16, inside **one transaction that is rolled
  back**. It runs 30 behavioral checks: forbidden transitions, self-approval, duplicate jobs,
  cross-tenant reads, and more. It needs `COMMERCE_OS_TEST_DB_URL` in `.env`, pointing at an empty
  test database, such as a Supabase branch of the operational project. It refuses to run if the
  `commerce_os` schema already exists there.

## Roles (to create on the operational project)

Step-by-step SQL: [docs/runbooks/operational-db-roles.md](../../docs/runbooks/operational-db-roles.md).

Create these with SQL (`CREATE ROLE ... LOGIN`). Commerce OS never uses the `postgres` role or the
secret (service-role) key, and none of these roles gets BYPASSRLS. Migration 0009 also revokes
Supabase's `anon` and `authenticated` roles from the `commerce_os` schema, so the Data API can't reach it:

- `commerce_os_migrator`: owns the schema and runs migrations. Used only by deploys.
- `commerce_os_service`: SELECT/INSERT/UPDATE on the tables, EXECUTE on `claim_job`. No DDL.
- `commerce_os_dashboard_read`: read-only views for the dashboard backend, if needed.
