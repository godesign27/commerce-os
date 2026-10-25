-- 0009 Tenant isolation (PRD §8.3, §17). Every table with a tenant_id gets row-level security that
-- only shows rows for the transaction's tenant:
--   SET LOCAL commerce_os.tenant_id = '<uuid>';
-- FORCE applies the policy to the table owner too, so a forgotten setting returns nothing rather than
-- everything. Runs last so it covers every table created above; new tables with tenant_id must be
-- added to a later migration that repeats this loop (tests/test_operational_schema.py checks coverage).

DO $$
DECLARE
    t record;
BEGIN
    FOR t IN
        SELECT c.table_name
          FROM information_schema.columns c
          JOIN information_schema.tables tb
            ON tb.table_schema = c.table_schema AND tb.table_name = c.table_name AND tb.table_type = 'BASE TABLE'
         WHERE c.table_schema = 'commerce_os' AND c.column_name = 'tenant_id' AND c.table_name <> 'tenants'
    LOOP
        EXECUTE format('ALTER TABLE commerce_os.%I ENABLE ROW LEVEL SECURITY', t.table_name);
        EXECUTE format('ALTER TABLE commerce_os.%I FORCE ROW LEVEL SECURITY', t.table_name);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON commerce_os.%I USING (tenant_id = commerce_os.current_tenant()) '
            'WITH CHECK (tenant_id = commerce_os.current_tenant())', t.table_name);
    END LOOP;
END;
$$;
