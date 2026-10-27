-- 0001 Foundation: schema, tenants, kill switch, shared trigger functions.
-- Commerce OS operational database only (PRD §5). Never run against a storefront database.

CREATE SCHEMA IF NOT EXISTS commerce_os;

-- Isolation key for every tenant-sensitive record (PRD §8.3). One tenant today; kept for B-013.
CREATE TABLE commerce_os.tenants (
    tenant_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text NOT NULL UNIQUE CHECK (slug ~ '^[a-z][a-z0-9-]*$'),
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Global kill switch (PRD §13): stops new storefront writes without discarding jobs or audit.
CREATE TABLE commerce_os.system_settings (
    singleton        boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    writes_disabled  boolean NOT NULL DEFAULT true,
    changed_by       text NOT NULL DEFAULT 'migration',
    changed_at       timestamptz NOT NULL DEFAULT now(),
    reason           text NOT NULL DEFAULT 'Initial state: writes disabled until Phase 3 approval.'
);
INSERT INTO commerce_os.system_settings DEFAULT VALUES;

-- Rejects UPDATE and DELETE: used for append-only tables (audit, reviews, attempts).
CREATE FUNCTION commerce_os.forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'commerce_os.%: rows are append-only (% rejected)', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

-- Optimistic concurrency (PRD §12): every update must advance revision by exactly one.
-- Callers update with `WHERE id = $1 AND revision = $expected` and set revision = revision + 1.
CREATE FUNCTION commerce_os.require_next_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.revision IS DISTINCT FROM OLD.revision + 1 THEN
        RAISE EXCEPTION 'commerce_os.%: revision must go from % to %, got %',
            TG_TABLE_NAME, OLD.revision, OLD.revision + 1, NEW.revision
            USING ERRCODE = 'serialization_failure';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- Tenant used by row-level security. The service sets it per transaction:
--   SET LOCAL commerce_os.tenant_id = '<uuid>';
CREATE FUNCTION commerce_os.current_tenant() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('commerce_os.tenant_id', true), '')::uuid
$$;
