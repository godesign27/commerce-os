-- 0006 Destinations: per-storefront publication tracking, immutable change sets, and explicit identity
-- links (PRD §5, §14, §15). There is no transaction across storefronts: each one is tracked on its own.

-- Product identity across destinations is an explicit link, never inferred from equal names or IDs.
CREATE TABLE commerce_os.destination_product_links (
    link_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    product_id     uuid NOT NULL REFERENCES commerce_os.products (product_id),
    storefront_id  text NOT NULL REFERENCES commerce_os.storefronts (storefront_id),
    environment    text NOT NULL CHECK (environment IN ('development', 'production', 'test')),
    external_id    text NOT NULL,
    linked_by      text NOT NULL,
    linked_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (storefront_id, environment, external_id),
    UNIQUE (product_id, storefront_id, environment)
);

-- Change sets (the change-set contract). Sealed change sets are immutable; any edit is a new one.
CREATE TABLE commerce_os.change_sets (
    change_set_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    submission_id        uuid NOT NULL REFERENCES commerce_os.submissions (submission_id),
    product_id           uuid NOT NULL REFERENCES commerce_os.products (product_id),
    canonical_revision   integer NOT NULL CHECK (canonical_revision >= 1),
    storefront_id        text NOT NULL,
    environment          text NOT NULL CHECK (environment IN ('development', 'production', 'test')),
    mapping_version      integer NOT NULL,
    schema_fingerprint   char(64) NOT NULL CHECK (schema_fingerprint ~ '^[0-9a-f]{64}$'),
    asset_manifest_hash  char(64) NOT NULL CHECK (asset_manifest_hash ~ '^[0-9a-f]{64}$'),
    requested_status     text NOT NULL CHECK (requested_status <> ''),
    document             jsonb NOT NULL,
    change_set_hash      char(64) CHECK (change_set_hash ~ '^[0-9a-f]{64}$'),   -- set when sealed
    sealed_at            timestamptz,
    prepared_by          text NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (storefront_id, mapping_version)
        REFERENCES commerce_os.mapping_versions (storefront_id, version),
    CHECK ((change_set_hash IS NULL) = (sealed_at IS NULL)),
    UNIQUE (change_set_id, storefront_id, environment)   -- lets approvals reference both together
);
CREATE UNIQUE INDEX change_sets_hash_per_destination
    ON commerce_os.change_sets (storefront_id, environment, change_set_hash) WHERE change_set_hash IS NOT NULL;

CREATE FUNCTION commerce_os.protect_sealed_change_set() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.sealed_at IS NOT NULL THEN
            RAISE EXCEPTION 'commerce_os.change_sets: a sealed change set cannot be deleted' USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.sealed_at IS NOT NULL THEN
        RAISE EXCEPTION 'commerce_os.change_sets: change set % is sealed; create a new one', OLD.change_set_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER change_sets_sealed BEFORE UPDATE OR DELETE ON commerce_os.change_sets
    FOR EACH ROW EXECUTE FUNCTION commerce_os.protect_sealed_change_set();

-- Per-destination publication state (PRD §14). The submission's aggregate is derived from these rows.
CREATE TABLE commerce_os.destination_drafts (
    destination_draft_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    submission_id         uuid NOT NULL REFERENCES commerce_os.submissions (submission_id),
    storefront_id         text NOT NULL REFERENCES commerce_os.storefronts (storefront_id),
    environment           text NOT NULL CHECK (environment IN ('development', 'production', 'test')),
    current_change_set_id uuid REFERENCES commerce_os.change_sets (change_set_id),
    state                 text NOT NULL DEFAULT 'NOT_SELECTED' REFERENCES commerce_os.publication_states (state),
    state_reason          text NOT NULL DEFAULT 'created',
    state_changed_by      text NOT NULL DEFAULT 'service:workflow',
    state_changed_at      timestamptz NOT NULL DEFAULT now(),
    revision              integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (submission_id, storefront_id, environment)
);
CREATE TRIGGER destination_drafts_revision BEFORE UPDATE ON commerce_os.destination_drafts
    FOR EACH ROW EXECUTE FUNCTION commerce_os.require_next_revision();
CREATE TRIGGER destination_drafts_transition BEFORE UPDATE OF state ON commerce_os.destination_drafts
    FOR EACH ROW EXECUTE FUNCTION commerce_os.enforce_transition('publication_transitions');
