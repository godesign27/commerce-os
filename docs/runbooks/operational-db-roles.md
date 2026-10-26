# Runbook: operational database roles (Supabase)

Logins for Commerce OS's own Supabase project, never a storefront's. Create them with SQL in the
project's **SQL Editor**. Commerce OS never uses the `postgres` role, the secret (service-role) key or
any role with `BYPASSRLS`, and the `commerce_os` schema is never exposed through the Data API.

## 1. Migrator: owns the schema and runs migrations

Used by deploys, and by `scripts/test_operational_db.py` to test migrations in a rolled-back
transaction. Generate a password locally first:

```bash
openssl rand -base64 32 | tr -d '/+=' | cut -c1-40
```

Then, in the SQL Editor:

```sql
CREATE ROLE commerce_os_migrator WITH LOGIN PASSWORD '<password>' CONNECTION LIMIT 3;
GRANT CONNECT, CREATE ON DATABASE postgres TO commerce_os_migrator;
```

`CREATE ON DATABASE` lets it create the `commerce_os` schema, which it then owns. It gets nothing in
`public`, `auth` or `storage`.

**Connection string.** Use **Connect → Session pooler** (port 5432) for the host. The username is the
role plus the project ref:

```text
postgresql://commerce_os_migrator.<project-ref>:<password>@<session-pooler-host>:5432/postgres?sslmode=require
```

## 2. Test the migrations

Put the connection string in `.env` as `COMMERCE_OS_TEST_DB_URL`, then:

```bash
python3 scripts/test_operational_db.py
```

It applies migrations 0001–0009 and `database/operational/tests/smoke.sql` in one transaction, then
rolls back. The project stays empty. It refuses to run if `commerce_os` already exists.

## 3. Service login (Phase 1)

Created after the migrations are applied for real:

```sql
CREATE ROLE commerce_os_service WITH LOGIN PASSWORD '<password>' CONNECTION LIMIT 20;
GRANT CONNECT ON DATABASE postgres TO commerce_os_service;
GRANT USAGE ON SCHEMA commerce_os TO commerce_os_service;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA commerce_os TO commerce_os_service;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA commerce_os TO commerce_os_service;
GRANT EXECUTE ON FUNCTION commerce_os.claim_job(text, text, interval) TO commerce_os_service;
```

No `DELETE`, no DDL. Append-only tables also reject updates through their triggers.

## Revoke

```sql
REASSIGN OWNED BY commerce_os_migrator TO postgres;   -- only if the schema should be kept
DROP OWNED BY commerce_os_migrator;
DROP ROLE commerce_os_migrator;
```
