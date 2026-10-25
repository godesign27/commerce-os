-- 0007 Review and approval (PRD §12, §13). Reviews are append-only. An approval is a human approver's
-- binding to one sealed change set, checked against it on insert, and can only ever be invalidated.

CREATE TABLE commerce_os.reviews (
    review_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    submission_id  uuid NOT NULL REFERENCES commerce_os.submissions (submission_id),
    product_id     uuid REFERENCES commerce_os.products (product_id),
    product_revision integer,
    actor_id       text NOT NULL,
    action         text NOT NULL CHECK (action IN ('confirm_field', 'correct_field', 'confirm_grouping', 'split', 'merge',
                                                   'confirm_identity', 'accept_asset_edit', 'choose_destinations',
                                                   'request_reprocess', 'reject', 'save_draft', 'resolve_issue')),
    payload        jsonb NOT NULL DEFAULT '{}'::jsonb,
    justification  text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (action <> 'correct_field' OR justification IS NOT NULL)   -- factual corrections say why (PRD §8.4)
);
CREATE TRIGGER reviews_append_only BEFORE UPDATE OR DELETE ON commerce_os.reviews
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();

CREATE TABLE commerce_os.approvals (
    approval_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    change_set_id        uuid NOT NULL,
    storefront_id        text NOT NULL,
    environment          text NOT NULL,
    actor_kind           text NOT NULL CHECK (actor_kind = 'human'),
    actor_role           text NOT NULL CHECK (actor_role = 'approver'),
    actor_id             text NOT NULL,
    prepared_by          text NOT NULL,
    approved_at          timestamptz NOT NULL DEFAULT now(),
    change_set_hash      char(64) NOT NULL,
    canonical_revision   integer NOT NULL,
    asset_manifest_hash  char(64) NOT NULL,
    mapping_version      integer NOT NULL,
    schema_fingerprint   char(64) NOT NULL,
    requested_status     text NOT NULL,
    invalidated_at       timestamptz,
    invalidated_reason   text,
    FOREIGN KEY (change_set_id, storefront_id, environment)
        REFERENCES commerce_os.change_sets (change_set_id, storefront_id, environment),
    CHECK (actor_id <> prepared_by),                                  -- no self-approval
    CHECK ((invalidated_at IS NULL) = (invalidated_reason IS NULL))
);
-- At most one live approval per change set.
CREATE UNIQUE INDEX approvals_one_live_per_change_set
    ON commerce_os.approvals (change_set_id) WHERE invalidated_at IS NULL;

-- Every binding must equal the sealed change set's: approvals can't be re-pointed at a different payload.
CREATE FUNCTION commerce_os.check_approval_bindings() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    cs commerce_os.change_sets%ROWTYPE;
BEGIN
    SELECT * INTO cs FROM commerce_os.change_sets WHERE change_set_id = NEW.change_set_id;
    IF cs.sealed_at IS NULL THEN
        RAISE EXCEPTION 'commerce_os.approvals: change set % is not sealed', NEW.change_set_id USING ERRCODE = 'check_violation';
    END IF;
    IF (NEW.change_set_hash, NEW.canonical_revision, NEW.asset_manifest_hash, NEW.mapping_version,
        NEW.schema_fingerprint, NEW.requested_status, NEW.prepared_by)
       IS DISTINCT FROM
       (cs.change_set_hash, cs.canonical_revision, cs.asset_manifest_hash, cs.mapping_version,
        cs.schema_fingerprint, cs.requested_status, cs.prepared_by) THEN
        RAISE EXCEPTION 'commerce_os.approvals: bindings do not match change set %', NEW.change_set_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER approvals_bindings BEFORE INSERT ON commerce_os.approvals
    FOR EACH ROW EXECUTE FUNCTION commerce_os.check_approval_bindings();

-- Approvals are immutable except for a one-time invalidation.
CREATE FUNCTION commerce_os.protect_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'commerce_os.approvals: approvals are never deleted' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF OLD.invalidated_at IS NOT NULL
       OR (to_jsonb(NEW) - 'invalidated_at' - 'invalidated_reason') IS DISTINCT FROM
          (to_jsonb(OLD) - 'invalidated_at' - 'invalidated_reason') THEN
        RAISE EXCEPTION 'commerce_os.approvals: only a one-time invalidation is allowed' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER approvals_protect BEFORE UPDATE OR DELETE ON commerce_os.approvals
    FOR EACH ROW EXECUTE FUNCTION commerce_os.protect_approval();
