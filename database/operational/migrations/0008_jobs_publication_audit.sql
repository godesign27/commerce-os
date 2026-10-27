-- 0008 Jobs, publication and audit (PRD §16, §17). At-least-once delivery is assumed everywhere:
-- work is keyed for idempotency, claims use leases, and the audit trail is append-only.

CREATE TABLE commerce_os.workflow_runs (
    run_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    submission_id  uuid NOT NULL REFERENCES commerce_os.submissions (submission_id),
    snapshot_id    uuid REFERENCES commerce_os.source_snapshots (snapshot_id),
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz
);

CREATE TABLE commerce_os.jobs (
    job_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    run_id            uuid REFERENCES commerce_os.workflow_runs (run_id),
    kind              text NOT NULL CHECK (kind IN ('intake', 'snapshot', 'validate_assets', 'prepare_images',
                                                    'analyze_product', 'draft', 'map_destination', 'validate',
                                                    'publish', 'reconcile', 'reconciliation_scan', 'renew_channel')),
    idempotency_key   text NOT NULL,
    payload           jsonb NOT NULL DEFAULT '{}'::jsonb,
    state             text NOT NULL DEFAULT 'queued'
                        CHECK (state IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'dead_letter', 'cancelled')),
    attempts          integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts      integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
    run_after         timestamptz NOT NULL DEFAULT now(),
    lease_owner       text,
    lease_expires_at  timestamptz,
    last_error        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, kind, idempotency_key),
    CHECK ((state = 'running') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK (attempts <= max_attempts)
);
CREATE INDEX jobs_claimable ON commerce_os.jobs (kind, run_after) WHERE state IN ('queued', 'retry_wait');

-- Atomic claim with a lease. Expired leases are reclaimable; competing workers never get the same job.
CREATE FUNCTION commerce_os.claim_job(p_kind text, p_worker text, p_lease interval)
RETURNS SETOF commerce_os.jobs
LANGUAGE sql AS $$
    UPDATE commerce_os.jobs j
       SET state = 'running', lease_owner = p_worker, lease_expires_at = now() + p_lease,
           attempts = j.attempts + 1, updated_at = now()
     WHERE j.job_id = (
           SELECT job_id FROM commerce_os.jobs
            WHERE kind = p_kind
              AND attempts < max_attempts
              AND ((state IN ('queued', 'retry_wait') AND run_after <= now())
                   OR (state = 'running' AND lease_expires_at < now()))
            ORDER BY run_after
            LIMIT 1
            FOR UPDATE SKIP LOCKED)
    RETURNING j.*
$$;

CREATE TABLE commerce_os.job_attempts (
    job_id       uuid NOT NULL REFERENCES commerce_os.jobs (job_id),
    attempt      integer NOT NULL CHECK (attempt >= 1),
    tenant_id    uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    worker       text NOT NULL,
    started_at   timestamptz NOT NULL,
    finished_at  timestamptz,
    outcome      text CHECK (outcome IN ('succeeded', 'retryable_error', 'terminal_error', 'lease_expired')),
    diagnostics  jsonb NOT NULL DEFAULT '{}'::jsonb,   -- redacted: no secrets or customer data
    PRIMARY KEY (job_id, attempt)
);
CREATE TRIGGER job_attempts_append_only BEFORE DELETE ON commerce_os.job_attempts
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();

-- Transactional outbox: jobs and notifications created in the same transaction as a state change.
CREATE TABLE commerce_os.outbox (
    outbox_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id      uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    topic          text NOT NULL,
    payload        jsonb NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    dispatched_at  timestamptz
);
CREATE INDEX outbox_pending ON commerce_os.outbox (outbox_id) WHERE dispatched_at IS NULL;

-- One attempt per approved change set: the publication key binds destination and change-set hash.
CREATE TABLE commerce_os.publication_attempts (
    attempt_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    change_set_id     uuid NOT NULL REFERENCES commerce_os.change_sets (change_set_id),
    approval_id       uuid NOT NULL REFERENCES commerce_os.approvals (approval_id),
    storefront_id     text NOT NULL,
    environment       text NOT NULL,
    change_set_hash   char(64) NOT NULL,
    try_number        integer NOT NULL DEFAULT 1 CHECK (try_number >= 1),
    state             text NOT NULL REFERENCES commerce_os.publication_states (state),
    gate4_checked_at  timestamptz NOT NULL,     -- execution revalidation happened before writing
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    error             text,
    UNIQUE (storefront_id, environment, change_set_hash, try_number)
);

CREATE TABLE commerce_os.publication_receipts (
    attempt_id          uuid NOT NULL REFERENCES commerce_os.publication_attempts (attempt_id),
    seq                 integer NOT NULL CHECK (seq >= 1),
    tenant_id           uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    external_id         text NOT NULL,
    result              text NOT NULL CHECK (result IN ('written', 'already_present', 'precondition_failed', 'error', 'unknown')),
    verified            text CHECK (verified IN ('match', 'mismatch', 'not_found', 'not_checked')),
    details             jsonb NOT NULL DEFAULT '{}'::jsonb,
    recorded_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (attempt_id, seq)
);
CREATE TRIGGER publication_receipts_append_only BEFORE UPDATE OR DELETE ON commerce_os.publication_receipts
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();

-- Append-only audit trail (PRD §17): source → draft → human decision → change set → receipt.
CREATE TABLE commerce_os.audit_events (
    audit_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    occurred_at   timestamptz NOT NULL DEFAULT now(),
    actor         text NOT NULL,
    action        text NOT NULL,
    subject_type  text NOT NULL,
    subject_id    text NOT NULL,
    details       jsonb NOT NULL DEFAULT '{}'::jsonb   -- redacted: no secrets or unnecessary personal data
);
CREATE INDEX audit_events_subject ON commerce_os.audit_events (subject_type, subject_id, occurred_at);
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON commerce_os.audit_events
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();

-- Every state change on submissions and destination drafts is audited in the same transaction.
CREATE FUNCTION commerce_os.audit_state_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO commerce_os.audit_events (tenant_id, actor, action, subject_type, subject_id, details)
    VALUES (NEW.tenant_id, NEW.state_changed_by, 'state_change', TG_TABLE_NAME,
            to_jsonb(NEW) ->> TG_ARGV[0],   -- the table's id column, passed by each trigger
            jsonb_build_object('from', OLD.state, 'to', NEW.state, 'reason', NEW.state_reason));
    RETURN NEW;
END;
$$;
CREATE TRIGGER submissions_audit AFTER UPDATE OF state ON commerce_os.submissions
    FOR EACH ROW WHEN (OLD.state IS DISTINCT FROM NEW.state)
    EXECUTE FUNCTION commerce_os.audit_state_change('submission_id');
CREATE TRIGGER destination_drafts_audit AFTER UPDATE OF state ON commerce_os.destination_drafts
    FOR EACH ROW WHEN (OLD.state IS DISTINCT FROM NEW.state)
    EXECUTE FUNCTION commerce_os.audit_state_change('destination_draft_id');
