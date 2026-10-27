-- 0005 Drafts: product proposals, canonical products and variants, field evidence, review issues and
-- catalog candidates (PRD §8). The canonical model is staging only, not a third live catalog: it has no
-- price, stock, tax or destination status columns.

CREATE TABLE commerce_os.product_proposals (
    proposal_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    snapshot_id    uuid NOT NULL REFERENCES commerce_os.source_snapshots (snapshot_id),
    revision       integer NOT NULL CHECK (revision >= 1),
    document       jsonb NOT NULL,          -- product-proposal contract
    model_version  text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (snapshot_id, revision)
);
CREATE TRIGGER product_proposals_immutable BEFORE UPDATE OR DELETE ON commerce_os.product_proposals
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();

-- One row per canonical product draft. Each reviewer edit advances revision (optimistic locking).
CREATE TABLE commerce_os.products (
    product_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    submission_id       uuid NOT NULL REFERENCES commerce_os.submissions (submission_id),
    source_snapshot_id  uuid NOT NULL REFERENCES commerce_os.source_snapshots (snapshot_id),
    product_type_id     text NOT NULL,
    product_type_version integer NOT NULL,
    option_definitions  jsonb NOT NULL DEFAULT '[]'::jsonb,
    assets              jsonb NOT NULL DEFAULT '[]'::jsonb,   -- ordered [{file_id, role, position}]
    policy_versions     jsonb NOT NULL,
    status              text NOT NULL DEFAULT 'current' CHECK (status IN ('current', 'superseded', 'rejected')),
    revision            integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (product_type_id, product_type_version)
        REFERENCES commerce_os.product_type_versions (product_type_id, version)
);
CREATE TRIGGER products_revision BEFORE UPDATE ON commerce_os.products
    FOR EACH ROW EXECUTE FUNCTION commerce_os.require_next_revision();
-- Only one current canonical product per submission at a time.
CREATE UNIQUE INDEX products_one_current_per_submission
    ON commerce_os.products (submission_id) WHERE status = 'current';

CREATE TABLE commerce_os.variants (
    variant_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    product_id         uuid NOT NULL REFERENCES commerce_os.products (product_id),
    option_values      jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(option_values) = 'object'),
    -- jsonb text output is canonical (sorted keys), so equal option combinations give equal keys.
    option_values_key  text GENERATED ALWAYS AS (option_values::text) STORED,
    file_ids           text[] NOT NULL DEFAULT '{}',
    revision           integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (product_id, option_values_key)   -- PRD §8.2: unique option combinations per product
);
CREATE TRIGGER variants_revision BEFORE UPDATE ON commerce_os.variants
    FOR EACH ROW EXECUTE FUNCTION commerce_os.require_next_revision();

-- Field evidence (PRD §8.4, evidence policy). One row per field per product revision; history is kept.
CREATE TABLE commerce_os.field_evidence (
    evidence_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    product_id        uuid NOT NULL REFERENCES commerce_os.products (product_id),
    variant_id        uuid REFERENCES commerce_os.variants (variant_id),
    product_revision  integer NOT NULL,
    field_path        text NOT NULL,
    is_commercial     boolean NOT NULL,
    value             jsonb,
    status            text NOT NULL CHECK (status IN ('observed', 'supplied', 'verified_catalog', 'inferred',
                                                      'unknown', 'conflicting', 'human_confirmed')),
    evidence          jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(evidence) = 'array'),
    confidence        numeric(4, 3) CHECK (confidence BETWEEN 0 AND 1),
    method            text,
    decided_by        text,
    decided_at        timestamptz,
    justification     text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (product_id, variant_id, product_revision, field_path),
    -- unknown and conflicting fields have no value
    CONSTRAINT field_evidence_unknown_has_no_value CHECK (status NOT IN ('unknown', 'conflicting') OR value IS NULL OR value = 'null'::jsonb),
    -- a value from observation, a source or inference cites evidence
    CONSTRAINT field_evidence_value_cites_evidence CHECK (status NOT IN ('observed', 'supplied', 'verified_catalog', 'inferred') OR jsonb_array_length(evidence) > 0),
    -- a human confirmation records who and when
    CONSTRAINT field_evidence_confirmation_recorded CHECK (status <> 'human_confirmed' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)),
    -- commercial facts are never observed or inferred (evidence policy rule 2)
    CONSTRAINT field_evidence_commercial_never_guessed CHECK (NOT is_commercial OR status IN ('supplied', 'verified_catalog', 'human_confirmed', 'unknown', 'conflicting'))
);
CREATE TRIGGER field_evidence_immutable BEFORE UPDATE OR DELETE ON commerce_os.field_evidence
    FOR EACH ROW EXECUTE FUNCTION commerce_os.forbid_mutation();

CREATE TABLE commerce_os.review_issues (
    issue_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    submission_id uuid NOT NULL REFERENCES commerce_os.submissions (submission_id),
    product_id    uuid REFERENCES commerce_os.products (product_id),
    issue_key     text NOT NULL CHECK (issue_key ~ '^RI-\d+$'),
    severity      text NOT NULL CHECK (severity IN ('blocking', 'warning', 'note')),
    gate          smallint CHECK (gate BETWEEN 1 AND 4),
    destination   text REFERENCES commerce_os.storefronts (storefront_id),
    target        text NOT NULL,
    question      text NOT NULL,
    resolver      text CHECK (resolver IN ('submitter', 'reviewer', 'approver', 'administrator', 'operator')),
    resolved_by   text,
    resolved_at   timestamptz,
    resolution    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (submission_id, issue_key),
    CHECK ((resolved_by IS NULL) = (resolved_at IS NULL))
);

-- Candidates per storefront, never merged across storefronts (PRD §10).
CREATE TABLE commerce_os.catalog_match_candidates (
    candidate_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES commerce_os.tenants (tenant_id),
    proposal_id    uuid NOT NULL REFERENCES commerce_os.product_proposals (proposal_id),
    storefront_id  text NOT NULL REFERENCES commerce_os.storefronts (storefront_id),
    environment    text NOT NULL CHECK (environment IN ('development', 'production', 'test')),
    external_id    text NOT NULL,
    rank           integer NOT NULL CHECK (rank >= 1),
    matching       jsonb NOT NULL DEFAULT '[]'::jsonb,
    conflicting    jsonb NOT NULL DEFAULT '[]'::jsonb,
    proposed_use   text NOT NULL CHECK (proposed_use IN ('structure_only', 'possible_same_product')),
    identity_confirmed_by text,       -- identity reuse requires a human (PRD §10)
    identity_confirmed_at timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (proposal_id, storefront_id, environment, external_id),
    CHECK ((identity_confirmed_by IS NULL) = (identity_confirmed_at IS NULL))
);
