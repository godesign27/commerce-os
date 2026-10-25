-- 0003 State machines (PRD §14). States and allowed transitions are data, enforced by triggers, so
-- no caller (and no agent) can set an arbitrary state label. Must match
-- plugins/commerce-os/shared/WORKFLOW.md; tests/test_operational_schema.py checks it.

CREATE TABLE commerce_os.submission_states (
    state        text PRIMARY KEY,
    is_terminal  boolean NOT NULL DEFAULT false
);
INSERT INTO commerce_os.submission_states (state, is_terminal) VALUES
    ('RECEIVED', false), ('WAITING_FOR_READY', false), ('SNAPSHOTTED', false),
    ('ASSETS_PROCESSING', false), ('PRODUCT_ANALYSIS', false), ('DRAFTING', false),
    ('VALIDATING', false), ('IN_REVIEW', false), ('READY_FOR_APPROVAL', false),
    ('APPROVED', false), ('PUBLISHING', false), ('PUBLISHED', true), ('PARTIALLY_PUBLISHED', false),
    ('NEEDS_INPUT', false), ('RETRY_WAIT', false), ('FAILED', false),
    ('REJECTED', true), ('CANCELLED', true), ('SUPERSEDED', true);

CREATE TABLE commerce_os.submission_transitions (
    from_state  text NOT NULL REFERENCES commerce_os.submission_states (state),
    to_state    text NOT NULL REFERENCES commerce_os.submission_states (state),
    PRIMARY KEY (from_state, to_state),
    CHECK (from_state <> to_state)
);
INSERT INTO commerce_os.submission_transitions (from_state, to_state) VALUES
    -- main path
    ('RECEIVED', 'WAITING_FOR_READY'), ('RECEIVED', 'SNAPSHOTTED'), ('WAITING_FOR_READY', 'SNAPSHOTTED'),
    ('SNAPSHOTTED', 'ASSETS_PROCESSING'), ('ASSETS_PROCESSING', 'PRODUCT_ANALYSIS'),
    ('PRODUCT_ANALYSIS', 'DRAFTING'), ('DRAFTING', 'VALIDATING'), ('VALIDATING', 'IN_REVIEW'),
    ('IN_REVIEW', 'READY_FOR_APPROVAL'), ('READY_FOR_APPROVAL', 'APPROVED'), ('APPROVED', 'PUBLISHING'),
    ('PUBLISHING', 'PUBLISHED'), ('PUBLISHING', 'PARTIALLY_PUBLISHED'), ('PARTIALLY_PUBLISHED', 'PUBLISHING'),
    -- missing facts
    ('IN_REVIEW', 'NEEDS_INPUT'), ('NEEDS_INPUT', 'IN_REVIEW'), ('VALIDATING', 'NEEDS_INPUT'),
    -- reviewer edits send affected drafts back to validation (and invalidate approvals)
    ('IN_REVIEW', 'VALIDATING'), ('READY_FOR_APPROVAL', 'VALIDATING'), ('APPROVED', 'VALIDATING'),
    -- retryable failures resume the failed checkpoint
    ('SNAPSHOTTED', 'RETRY_WAIT'), ('ASSETS_PROCESSING', 'RETRY_WAIT'), ('PRODUCT_ANALYSIS', 'RETRY_WAIT'),
    ('DRAFTING', 'RETRY_WAIT'), ('VALIDATING', 'RETRY_WAIT'), ('PUBLISHING', 'RETRY_WAIT'),
    ('RETRY_WAIT', 'SNAPSHOTTED'), ('RETRY_WAIT', 'ASSETS_PROCESSING'), ('RETRY_WAIT', 'PRODUCT_ANALYSIS'),
    ('RETRY_WAIT', 'DRAFTING'), ('RETRY_WAIT', 'VALIDATING'), ('RETRY_WAIT', 'PUBLISHING'),
    -- terminal validation or permission failures; an operator can retry from FAILED
    ('SNAPSHOTTED', 'FAILED'), ('ASSETS_PROCESSING', 'FAILED'), ('PRODUCT_ANALYSIS', 'FAILED'),
    ('DRAFTING', 'FAILED'), ('VALIDATING', 'FAILED'), ('PUBLISHING', 'FAILED'), ('RETRY_WAIT', 'FAILED'),
    ('FAILED', 'RETRY_WAIT'), ('FAILED', 'NEEDS_INPUT'),
    -- human decisions before publishing; a new source snapshot supersedes
    ('RECEIVED', 'REJECTED'), ('WAITING_FOR_READY', 'REJECTED'), ('IN_REVIEW', 'REJECTED'),
    ('NEEDS_INPUT', 'REJECTED'), ('READY_FOR_APPROVAL', 'REJECTED'), ('FAILED', 'REJECTED'),
    ('RECEIVED', 'CANCELLED'), ('WAITING_FOR_READY', 'CANCELLED'), ('IN_REVIEW', 'CANCELLED'),
    ('NEEDS_INPUT', 'CANCELLED'), ('READY_FOR_APPROVAL', 'CANCELLED'), ('APPROVED', 'CANCELLED'),
    ('FAILED', 'CANCELLED'), ('RETRY_WAIT', 'CANCELLED'),
    ('WAITING_FOR_READY', 'SUPERSEDED'), ('IN_REVIEW', 'SUPERSEDED'), ('NEEDS_INPUT', 'SUPERSEDED'),
    ('READY_FOR_APPROVAL', 'SUPERSEDED'), ('APPROVED', 'SUPERSEDED'), ('FAILED', 'SUPERSEDED');

-- Per-destination publication states. The submission's aggregate is derived from these.
CREATE TABLE commerce_os.publication_states (
    state        text PRIMARY KEY,
    is_terminal  boolean NOT NULL DEFAULT false
);
INSERT INTO commerce_os.publication_states (state, is_terminal) VALUES
    ('NOT_SELECTED', false), ('DRAFT', false), ('BLOCKED', false), ('AWAITING_APPROVAL', false),
    ('APPROVED', false), ('QUEUED', false), ('WRITING', false), ('VERIFYING', false),
    ('SUCCEEDED', true), ('FAILED', false), ('OUTCOME_UNKNOWN', false), ('CANCELLED', true);

CREATE TABLE commerce_os.publication_transitions (
    from_state  text NOT NULL REFERENCES commerce_os.publication_states (state),
    to_state    text NOT NULL REFERENCES commerce_os.publication_states (state),
    PRIMARY KEY (from_state, to_state),
    CHECK (from_state <> to_state)
);
INSERT INTO commerce_os.publication_transitions (from_state, to_state) VALUES
    ('NOT_SELECTED', 'DRAFT'), ('DRAFT', 'NOT_SELECTED'),
    ('DRAFT', 'BLOCKED'), ('BLOCKED', 'DRAFT'), ('DRAFT', 'AWAITING_APPROVAL'),
    ('AWAITING_APPROVAL', 'APPROVED'), ('AWAITING_APPROVAL', 'DRAFT'),
    ('APPROVED', 'DRAFT'),                       -- approval invalidated by an edit or new snapshot
    ('APPROVED', 'QUEUED'), ('QUEUED', 'WRITING'),
    ('WRITING', 'VERIFYING'), ('WRITING', 'FAILED'), ('WRITING', 'OUTCOME_UNKNOWN'),
    ('VERIFYING', 'SUCCEEDED'), ('VERIFYING', 'FAILED'), ('VERIFYING', 'OUTCOME_UNKNOWN'),
    ('OUTCOME_UNKNOWN', 'VERIFYING'), ('OUTCOME_UNKNOWN', 'SUCCEEDED'), ('OUTCOME_UNKNOWN', 'FAILED'),
    ('FAILED', 'QUEUED'),                        -- retry, only while the approval is still valid
    ('FAILED', 'DRAFT'),
    ('NOT_SELECTED', 'CANCELLED'), ('DRAFT', 'CANCELLED'), ('BLOCKED', 'CANCELLED'),
    ('AWAITING_APPROVAL', 'CANCELLED'), ('APPROVED', 'CANCELLED'), ('QUEUED', 'CANCELLED'),
    ('FAILED', 'CANCELLED');
    -- WRITING, VERIFYING and OUTCOME_UNKNOWN cannot be cancelled: an in-flight write is always reconciled.

CREATE TRIGGER submission_states_immutable BEFORE UPDATE OR DELETE ON commerce_os.submission_states
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();
CREATE TRIGGER submission_transitions_immutable BEFORE UPDATE OR DELETE ON commerce_os.submission_transitions
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();
CREATE TRIGGER publication_states_immutable BEFORE UPDATE OR DELETE ON commerce_os.publication_states
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();
CREATE TRIGGER publication_transitions_immutable BEFORE UPDATE OR DELETE ON commerce_os.publication_transitions
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();

-- Generic guard: a state column may only change along an allowed transition, and every change must
-- name who made it and why (PRD §14). The same trigger records the change in audit_events (0008).
-- TG_ARGV[0] names the transitions table.
CREATE FUNCTION commerce_os.enforce_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    allowed boolean;
BEGIN
    IF NEW.state IS DISTINCT FROM OLD.state THEN
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM commerce_os.%I WHERE from_state = $1 AND to_state = $2)', TG_ARGV[0])
            INTO allowed USING OLD.state, NEW.state;
        IF NOT allowed THEN
            RAISE EXCEPTION 'commerce_os.%: transition % → % is not allowed', TG_TABLE_NAME, OLD.state, NEW.state
                USING ERRCODE = 'check_violation';
        END IF;
        IF coalesce(NEW.state_reason, '') = '' OR coalesce(NEW.state_changed_by, '') = '' THEN
            RAISE EXCEPTION 'commerce_os.%: a state change needs state_reason and state_changed_by', TG_TABLE_NAME
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.state_changed_at := now();
    END IF;
    RETURN NEW;
END;
$$;
