-- 0002 Configuration: connections, storefronts, product types and mapping versions.
-- No credential is ever stored here: connections name a secret by reference only (PRD §17).

CREATE TABLE commerce_os.connections (
    connection_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    kind           text NOT NULL CHECK (kind IN ('intake', 'storefront_read', 'storefront_write', 'asset_store')),
    provider       text NOT NULL CHECK (provider ~ '^[a-z][a-z0-9-]*$'),
    secret_ref     text NOT NULL CHECK (secret_ref ~ '^[A-Z][A-Z0-9_]*$'),  -- an env var / secret-manager name, never a value
    settings       jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    disabled_at    timestamptz
);

CREATE TABLE commerce_os.storefronts (
    storefront_id    text PRIMARY KEY CHECK (storefront_id ~ '^[a-z][a-z0-9-]*$'),
    tenant_id        uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    display_name     text NOT NULL,
    provider         text NOT NULL,
    catalog_profile  text NOT NULL,
    features         text[] NOT NULL DEFAULT '{}',
    currency         char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    read_connection_id   uuid REFERENCES commerce_os.connections (connection_id),
    write_connection_id  uuid REFERENCES commerce_os.connections (connection_id),
    writes_enabled   boolean NOT NULL DEFAULT false,
    asset_upload     text NOT NULL DEFAULT 'not_authorized' CHECK (asset_upload IN ('not_authorized', 'authorized')),
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (read_connection_id IS DISTINCT FROM write_connection_id OR read_connection_id IS NULL),
    CONSTRAINT storefronts_writes_need_write_connection CHECK (NOT writes_enabled OR write_connection_id IS NOT NULL)
);

-- Versioned product types (resources/product-types/*.json). Drafts record the version they used.
CREATE TABLE commerce_os.product_type_versions (
    product_type_id  text NOT NULL CHECK (product_type_id ~ '^[a-z][a-z0-9-]*$'),
    version          integer NOT NULL CHECK (version >= 1),
    definition       jsonb NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (product_type_id, version)
);
CREATE TRIGGER product_type_versions_immutable BEFORE UPDATE OR DELETE ON commerce_os.product_type_versions
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();

-- Versioned storefront mappings (config/mappings/<id>.local.json) bound to a schema fingerprint (B-028).
CREATE TABLE commerce_os.mapping_versions (
    storefront_id       text NOT NULL REFERENCES commerce_os.storefronts (storefront_id),
    version             integer NOT NULL CHECK (version >= 1),
    tenant_id           uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    document            jsonb NOT NULL,
    schema_fingerprint  char(64) NOT NULL CHECK (schema_fingerprint ~ '^[0-9a-f]{64}$'),
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (storefront_id, version)
);
CREATE TRIGGER mapping_versions_immutable BEFORE UPDATE OR DELETE ON commerce_os.mapping_versions
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();
