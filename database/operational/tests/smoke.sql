-- Behavioral smoke test for the operational migrations. Run ONLY through
-- scripts/test_operational_db.py, which wraps the migrations and this file in one transaction and
-- rolls back, so nothing persists. Every check raises on failure (psql runs with ON_ERROR_STOP).

-- `expect` is a fragment of the expected error message, so a check can't pass on an unrelated error
-- (a typo in its own SQL, a missing fixture). The actual SQLSTATE and message are printed either way.
CREATE FUNCTION pg_temp.expect_error(stmt text, label text, expect text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE stmt;
    EXCEPTION WHEN OTHERS THEN
        IF position(expect IN SQLERRM) = 0 THEN
            RAISE EXCEPTION 'SMOKE FAIL: % was rejected for the wrong reason [%] %', label, SQLSTATE, SQLERRM;
        END IF;
        RAISE NOTICE 'ok (rejected): % [%] %', label, SQLSTATE, SQLERRM;
        RETURN;
    END;
    RAISE EXCEPTION 'SMOKE FAIL: expected an error for: %', label;
END;
$$;

CREATE FUNCTION pg_temp.expect(ok boolean, label text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT coalesce(ok, false) THEN
        RAISE EXCEPTION 'SMOKE FAIL: %', label;
    END IF;
    RAISE NOTICE 'ok: %', label;
END;
$$;

-- ---------------------------------------------------------------- fixture data (fake)
-- IDs: tenant ...0001, intake connection ...00c1, read connection ...00c2, submission ...00a1,
-- snapshot ...00b1, product ...00d1, change set ...00e1, destination draft ...00f1.
INSERT INTO commerce_os.tenants (tenant_id, slug) VALUES ('00000000-0000-4000-8000-000000000001', 'smoke');
SET LOCAL commerce_os.tenant_id = '00000000-0000-4000-8000-000000000001';

INSERT INTO commerce_os.connections (connection_id, tenant_id, kind, provider, secret_ref) VALUES
    ('00000000-0000-4000-8000-0000000000c1', '00000000-0000-4000-8000-000000000001', 'intake', 'google-drive', 'DRIVE_TEST'),
    ('00000000-0000-4000-8000-0000000000c2', '00000000-0000-4000-8000-000000000001', 'storefront_read', 'neon', 'STOREFRONT_X_DB_URL');
INSERT INTO commerce_os.storefronts (storefront_id, tenant_id, display_name, provider, catalog_profile, currency, read_connection_id)
VALUES ('storefront-x', '00000000-0000-4000-8000-000000000001', 'Storefront X', 'neon', 'replit-artstore-v1', 'USD',
        '00000000-0000-4000-8000-0000000000c2');
INSERT INTO commerce_os.product_type_versions (product_type_id, version, definition)
VALUES ('hat', 1, '{"options": {"color": "allowed"}}');
INSERT INTO commerce_os.mapping_versions (storefront_id, version, tenant_id, document, schema_fingerprint) VALUES
    ('storefront-x', 1, '00000000-0000-4000-8000-000000000001', '{}', repeat('a', 64)),
    ('storefront-x', 2, '00000000-0000-4000-8000-000000000001', '{}', repeat('a', 64));
INSERT INTO commerce_os.submissions (submission_id, tenant_id, connection_id, folder_id)
VALUES ('00000000-0000-4000-8000-0000000000a1', '00000000-0000-4000-8000-000000000001',
        '00000000-0000-4000-8000-0000000000c1', 'folder-1');

-- ---------------------------------------------------------------- configuration
SELECT pg_temp.expect((SELECT writes_disabled FROM commerce_os.system_settings), 'kill switch starts with writes disabled');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.connections (tenant_id, kind, provider, secret_ref)
    VALUES ('00000000-0000-4000-8000-000000000001', 'intake', 'neon', 'postgresql://user:pw@host/db')$$,
    'a connection stores a secret value instead of a reference', 'connections_secret_ref_check');
SELECT pg_temp.expect_error($$UPDATE commerce_os.storefronts SET writes_enabled = true WHERE storefront_id = 'storefront-x'$$,
    'writes enabled without a write connection', 'storefronts_writes_need_write_connection');
SELECT pg_temp.expect_error($$UPDATE commerce_os.mapping_versions SET document = '{"x":1}' WHERE version = 1$$,
    'a mapping version is edited in place', 'append-only');

-- ---------------------------------------------------------------- state machine and revisions
SELECT pg_temp.expect_error($$UPDATE commerce_os.submissions SET state = 'PUBLISHED', state_reason = 'skip', revision = revision + 1
    WHERE submission_id = '00000000-0000-4000-8000-0000000000a1'$$, 'RECEIVED → PUBLISHED skips the gates', 'is not allowed');
SELECT pg_temp.expect_error($$UPDATE commerce_os.submissions SET display_name = 'x'
    WHERE submission_id = '00000000-0000-4000-8000-0000000000a1'$$, 'an update without a revision bump', 'revision must go from');
UPDATE commerce_os.submissions SET state = 'SNAPSHOTTED', state_reason = 'ready manifest found',
       state_changed_by = 'service:drive-events', revision = revision + 1
 WHERE submission_id = '00000000-0000-4000-8000-0000000000a1';
SELECT pg_temp.expect((SELECT count(*) = 1 FROM commerce_os.audit_events WHERE action = 'state_change'
                        AND subject_id = '00000000-0000-4000-8000-0000000000a1' AND details ->> 'to' = 'SNAPSHOTTED'),
    'a valid transition is audited');
SELECT pg_temp.expect_error($$UPDATE commerce_os.audit_events SET actor = 'someone-else'$$, 'audit rows are edited', 'append-only');
SELECT pg_temp.expect_error($$DELETE FROM commerce_os.audit_events$$, 'audit rows are deleted', 'append-only');

-- ---------------------------------------------------------------- intake
INSERT INTO commerce_os.event_inbox (tenant_id, connection_id, provider, channel_id, message_number, resource_state)
VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000c1', 'google-drive', 'ch-1', 7, 'change');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.event_inbox (tenant_id, connection_id, provider, channel_id, message_number, resource_state)
    VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000c1', 'google-drive', 'ch-1', 7, 'change')$$,
    'a duplicate notification is stored twice', 'event_inbox_provider_channel_id_message_number_key');
INSERT INTO commerce_os.source_snapshots (snapshot_id, tenant_id, submission_id, revision, manifest_hash, intake_policy_version, manifest)
VALUES ('00000000-0000-4000-8000-0000000000b1', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000a1',
        1, repeat('b', 64), '0.1.0', '{}');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.source_snapshots (tenant_id, submission_id, revision, manifest_hash, intake_policy_version, manifest)
    VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000a1', 2, repeat('b', 64), '0.1.0', '{}')$$,
    'the same source revision is snapshotted twice', 'source_snapshots_submission_id_manifest_hash_intake_policy__key');
SELECT pg_temp.expect_error($$UPDATE commerce_os.source_snapshots SET manifest = '{"changed": true}'$$, 'a snapshot is mutated', 'append-only');

-- ---------------------------------------------------------------- drafts and evidence
INSERT INTO commerce_os.products (product_id, tenant_id, submission_id, source_snapshot_id, product_type_id, product_type_version, policy_versions)
VALUES ('00000000-0000-4000-8000-0000000000d1', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000a1',
        '00000000-0000-4000-8000-0000000000b1', 'hat', 1, '{"evidence-policy": "0.1.0"}');
INSERT INTO commerce_os.variants (tenant_id, product_id, option_values)
VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000d1', '{"color": "navy", "size": "m"}');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.variants (tenant_id, product_id, option_values)
    VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000d1', '{"size": "m", "color": "navy"}')$$,
    'two variants with the same options in a different key order', 'variants_product_id_option_values_key_key');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.field_evidence (tenant_id, product_id, product_revision, field_path, is_commercial, value, status, evidence)
    VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000d1', 1, 'material', true, '"cotton"', 'inferred', '[{"kind":"asset","ref":"f1"}]')$$,
    'a commercial fact inferred from a photo', 'field_evidence_commercial_never_guessed');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.field_evidence (tenant_id, product_id, product_revision, field_path, is_commercial, value, status)
    VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000d1', 1, 'brand', true, '"Acme"', 'unknown')$$,
    'an unknown fact with a value', 'field_evidence_unknown_has_no_value');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.field_evidence (tenant_id, product_id, product_revision, field_path, is_commercial, value, status)
    VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000d1', 1, 'title', false, '"Cap"', 'observed')$$,
    'an observed value without evidence', 'field_evidence_value_cites_evidence');
INSERT INTO commerce_os.field_evidence (tenant_id, product_id, product_revision, field_path, is_commercial, value, status)
VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000d1', 1, 'brand', true, NULL, 'unknown');

-- ---------------------------------------------------------------- change sets and approvals
INSERT INTO commerce_os.change_sets (change_set_id, tenant_id, submission_id, product_id, canonical_revision, storefront_id, environment,
       mapping_version, schema_fingerprint, asset_manifest_hash, requested_status, document, change_set_hash, sealed_at, prepared_by)
VALUES ('00000000-0000-4000-8000-0000000000e1', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000a1',
        '00000000-0000-4000-8000-0000000000d1', 1, 'storefront-x', 'production', 2, repeat('a', 64), repeat('c', 64), 'draft',
        '{}', repeat('d', 64), now(), 'agent:catalog-draft');
SELECT pg_temp.expect_error($$UPDATE commerce_os.change_sets SET requested_status = 'active'$$, 'a sealed change set is edited', 'is sealed');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.approvals (tenant_id, change_set_id, storefront_id, environment, actor_kind, actor_role,
    actor_id, prepared_by, change_set_hash, canonical_revision, asset_manifest_hash, mapping_version, schema_fingerprint, requested_status)
    VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000e1', 'storefront-x', 'production', 'agent', 'approver',
    'agent:review-publishing', 'agent:catalog-draft', repeat('d', 64), 1, repeat('c', 64), 2, repeat('a', 64), 'draft')$$,
    'an agent approves', 'approvals_actor_kind_check');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.approvals (tenant_id, change_set_id, storefront_id, environment, actor_kind, actor_role,
    actor_id, prepared_by, change_set_hash, canonical_revision, asset_manifest_hash, mapping_version, schema_fingerprint, requested_status)
    VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000e1', 'storefront-x', 'production', 'human', 'approver',
    'agent:catalog-draft', 'agent:catalog-draft', repeat('d', 64), 1, repeat('c', 64), 2, repeat('a', 64), 'draft')$$,
    'the preparer approves their own change set', 'approvals_no_self_approval');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.approvals (tenant_id, change_set_id, storefront_id, environment, actor_kind, actor_role,
    actor_id, prepared_by, change_set_hash, canonical_revision, asset_manifest_hash, mapping_version, schema_fingerprint, requested_status)
    VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000e1', 'storefront-x', 'production', 'human', 'approver',
    'user:approver-1', 'agent:catalog-draft', repeat('d', 64), 1, repeat('c', 64), 1, repeat('a', 64), 'draft')$$,
    'an approval bound to a different mapping version', 'bindings do not match');
INSERT INTO commerce_os.approvals (approval_id, tenant_id, change_set_id, storefront_id, environment, actor_kind, actor_role,
       actor_id, prepared_by, change_set_hash, canonical_revision, asset_manifest_hash, mapping_version, schema_fingerprint, requested_status)
VALUES ('00000000-0000-4000-8000-0000000000aa', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000e1',
        'storefront-x', 'production', 'human', 'approver', 'user:approver-1', 'agent:catalog-draft',
        repeat('d', 64), 1, repeat('c', 64), 2, repeat('a', 64), 'draft');
SELECT pg_temp.expect_error($$UPDATE commerce_os.approvals SET requested_status = 'active'$$, 'an approval is re-pointed', 'only a one-time invalidation');
UPDATE commerce_os.approvals SET invalidated_at = now(), invalidated_reason = 'reviewer edited the title';
SELECT pg_temp.expect_error($$UPDATE commerce_os.approvals SET invalidated_reason = 'changed my mind'$$, 'an invalidation is rewritten', 'only a one-time invalidation');
SELECT pg_temp.expect_error($$DELETE FROM commerce_os.approvals$$, 'an approval is deleted', 'never deleted');

-- ---------------------------------------------------------------- per-destination publication
INSERT INTO commerce_os.destination_drafts (destination_draft_id, tenant_id, submission_id, storefront_id, environment)
VALUES ('00000000-0000-4000-8000-0000000000f1', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000a1',
        'storefront-x', 'production');
SELECT pg_temp.expect_error($$UPDATE commerce_os.destination_drafts SET state = 'QUEUED', state_reason = 'skip', revision = revision + 1$$,
    'NOT_SELECTED → QUEUED skips approval', 'is not allowed');
UPDATE commerce_os.destination_drafts SET state = 'DRAFT', state_reason = 'selected by reviewer',
       state_changed_by = 'user:reviewer-1', revision = revision + 1;
SELECT pg_temp.expect((SELECT count(*) = 1 FROM commerce_os.audit_events WHERE subject_type = 'destination_drafts'),
    'a destination state change is audited');

-- ---------------------------------------------------------------- jobs
INSERT INTO commerce_os.jobs (tenant_id, kind, idempotency_key) VALUES ('00000000-0000-4000-8000-000000000001', 'draft', 'sub-a1@r1');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.jobs (tenant_id, kind, idempotency_key)
    VALUES ('00000000-0000-4000-8000-000000000001', 'draft', 'sub-a1@r1')$$, 'the same job is enqueued twice', 'jobs_tenant_id_kind_idempotency_key_key');
SELECT pg_temp.expect((SELECT count(*) = 1 FROM commerce_os.claim_job('draft', 'worker-1', interval '5 minutes')), 'first claim gets the job');
SELECT pg_temp.expect((SELECT count(*) = 0 FROM commerce_os.claim_job('draft', 'worker-2', interval '5 minutes')), 'a second worker gets nothing');

-- ---------------------------------------------------------------- tenant isolation
SET LOCAL commerce_os.tenant_id = '00000000-0000-4000-8000-000000000999';
SELECT pg_temp.expect((SELECT count(*) = 0 FROM commerce_os.submissions), 'another tenant sees no submissions');
SELECT pg_temp.expect_error($$INSERT INTO commerce_os.jobs (tenant_id, kind, idempotency_key)
    VALUES ('00000000-0000-4000-8000-000000000001', 'draft', 'cross-tenant')$$, 'writing into another tenant', 'row-level security');

SELECT 'SMOKE PASSED' AS result;
