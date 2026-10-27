-- 0004 Intake: Drive notification inbox, channels, submissions, immutable snapshots, files and blobs
-- (PRD §7, §16). Notifications are hints; work is deduplicated by source revision.

-- Durable inbox: a notification is persisted before it is acknowledged. Duplicates land harmlessly.
CREATE TABLE commerce_os.event_inbox (
    event_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    connection_id   uuid NOT NULL REFERENCES commerce_os.connections (connection_id),
    provider        text NOT NULL,
    channel_id      text NOT NULL,
    message_number  bigint NOT NULL,
    resource_state  text NOT NULL,
    payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
    received_at     timestamptz NOT NULL DEFAULT now(),
    processed_at    timestamptz,
    UNIQUE (provider, channel_id, message_number)
);

-- Notification channels and change cursors. The cursor only advances after changes are journaled.
CREATE TABLE commerce_os.drive_channels (
    channel_id      text PRIMARY KEY,
    tenant_id       uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    connection_id   uuid NOT NULL REFERENCES commerce_os.connections (connection_id),
    resource_id     text NOT NULL,
    expires_at      timestamptz NOT NULL,
    page_token      text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    stopped_at      timestamptz
);

-- One logical submission per intake folder. Names and paths are display values, never identifiers.
CREATE TABLE commerce_os.submissions (
    submission_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    connection_id    uuid NOT NULL REFERENCES commerce_os.connections (connection_id),
    folder_id        text NOT NULL,
    display_name     text,
    state            text NOT NULL DEFAULT 'RECEIVED' REFERENCES commerce_os.submission_states (state),
    state_reason     text NOT NULL DEFAULT 'received',
    state_changed_by text NOT NULL DEFAULT 'service:drive-events',
    state_changed_at timestamptz NOT NULL DEFAULT now(),
    revision         integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, connection_id, folder_id)
);
CREATE TRIGGER submissions_revision BEFORE UPDATE ON commerce_os.submissions
    FOR EACH ROW EXECUTE FUNCTION commerce_os.require_next_revision();
CREATE TRIGGER submissions_transition BEFORE UPDATE OF state ON commerce_os.submissions
    FOR EACH ROW EXECUTE FUNCTION commerce_os.enforce_transition('submission_transitions');

-- Immutable input snapshot (the source-manifest contract). A changed file set is a new snapshot.
CREATE TABLE commerce_os.source_snapshots (
    snapshot_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    submission_id   uuid NOT NULL REFERENCES commerce_os.submissions (submission_id),
    revision        integer NOT NULL CHECK (revision >= 1),
    manifest_hash   char(64) NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    intake_policy_version text NOT NULL,
    manifest        jsonb NOT NULL,
    supersedes_snapshot_id uuid REFERENCES commerce_os.source_snapshots (snapshot_id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (submission_id, revision),
    UNIQUE (submission_id, manifest_hash, intake_policy_version)   -- intake work key (PRD §16)
);
CREATE TRIGGER source_snapshots_immutable BEFORE UPDATE OR DELETE ON commerce_os.source_snapshots
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();

-- Content-addressed blobs: repeated identical images share one blob (PRD §7.3).
CREATE TABLE commerce_os.blobs (
    sha256       char(64) PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    bytes        bigint NOT NULL CHECK (bytes >= 0),
    mime         text NOT NULL,
    storage_key  text NOT NULL UNIQUE,
    visibility   text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'signed')),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE commerce_os.source_files (
    snapshot_id        uuid NOT NULL REFERENCES commerce_os.source_snapshots (snapshot_id),
    file_id            text NOT NULL,
    tenant_id          uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    display_name       text,
    provider_version   text,
    sha256             char(64) NOT NULL REFERENCES commerce_os.blobs (sha256),
    mime_by_signature  text,
    width              integer CHECK (width > 0),
    height             integer CHECK (height > 0),
    accepted           boolean NOT NULL,
    rejection_reason   text,
    PRIMARY KEY (snapshot_id, file_id),
    CHECK (accepted OR rejection_reason IS NOT NULL)
);
CREATE TRIGGER source_files_immutable BEFORE UPDATE OR DELETE ON commerce_os.source_files
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();

-- Derivatives from versioned recipes (the derivative-manifest contract). Originals are never changed.
CREATE TABLE commerce_os.asset_derivatives (
    derivative_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    source_sha256    char(64) NOT NULL REFERENCES commerce_os.blobs (sha256),
    recipe_id        text NOT NULL,
    recipe_version   integer NOT NULL CHECK (recipe_version >= 1),
    destination      text NOT NULL,   -- a storefront_id, or 'review'
    output_sha256    char(64) NOT NULL REFERENCES commerce_os.blobs (sha256),
    consequential    boolean NOT NULL,
    accepted_by      text,
    accepted_at      timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, source_sha256, recipe_id, recipe_version, destination),   -- image work key (PRD §16)
    CHECK ((accepted_by IS NULL) = (accepted_at IS NULL))
);
