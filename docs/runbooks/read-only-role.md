# Runbook: read-only catalog role for a storefront

Creates the login Commerce OS uses to read one storefront's catalog: `products`, `categories` and
`tags`, and nothing else. Customer tables (`users`, `orders`, `messages`, ...) share the same
database, so the role's grants (and on Supabase, its policies) are what keep customer data out of
reach (BACKLOG B-027, B-039).

Do this once per storefront database. The owner does it; Commerce OS never holds the owner login,
the `postgres` role or a Supabase secret key.

Pick the section for the storefront's provider (`config/storefronts.local.json`):

- **Supabase** (`supabase`): Storefront A.
- **Replit-managed Postgres or Neon** (`replit-postgres`, `neon`): Storefront B.

## 1. Generate a password, locally

```bash
openssl rand -base64 32 | tr -d '/+=' | cut -c1-40
```

Keep it in your password manager. Don't paste it into chat, tickets or committed files.

## 2a. Supabase

In the Supabase dashboard, open the storefront's project → **SQL Editor**. Check you're in the right
project first:

```sql
SELECT current_database(), (SELECT count(*) FROM public.products) AS products;
```

The database is named `postgres` on Supabase. The product count tells you which data you're looking
at (Storefront A's copy of production has 39).

Then create the role. Replace the password:

```sql
CREATE ROLE commerce_os_read WITH LOGIN PASSWORD '<password from step 1>' CONNECTION LIMIT 3;
ALTER ROLE commerce_os_read SET default_transaction_read_only = on;
ALTER ROLE commerce_os_read SET statement_timeout = '15s';
GRANT CONNECT ON DATABASE postgres TO commerce_os_read;
GRANT USAGE ON SCHEMA public TO commerce_os_read;
GRANT SELECT ON public.products, public.categories, public.tags TO commerce_os_read;

-- Row-level security is on for every table with no policies, so the role also needs a read policy
-- on exactly these three tables. Every other table stays closed to it.
CREATE POLICY commerce_os_read_catalog ON public.products   FOR SELECT TO commerce_os_read USING (true);
CREATE POLICY commerce_os_read_catalog ON public.categories FOR SELECT TO commerce_os_read USING (true);
CREATE POLICY commerce_os_read_catalog ON public.tags       FOR SELECT TO commerce_os_read USING (true);
```

Don't grant anything else. Never give this role `BYPASSRLS`, and don't add it to any other role.

**Connection string.** Use the **session pooler** (port 5432). The pooler username is the role name
plus the project ref:

```text
postgresql://commerce_os_read.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

The project ref is in the dashboard URL (Storefront A's is noted in your local
`discovery/raw/README.md`). Copy the host from **Connect** → **Session pooler** in the dashboard.

## 2b. Replit-managed Postgres or Neon

Use the Neon console's **SQL Editor**, not its Roles page: Neon adds roles created in the console, CLI
or API to `neon_superuser`. Check the database first with `SELECT current_database();`, then run the same
`CREATE ROLE`, `ALTER ROLE`, `GRANT CONNECT` (with that database's name), `GRANT USAGE` and
`GRANT SELECT` statements as 2a, without the policies. RLS is off on these databases.

**Connection string.** Use the direct host from **Connect**, without `-pooler`:

```text
postgresql://commerce_os_read:<password>@<host>/<db>?sslmode=require
```

## 3. Put it in `.env`, never anywhere else

In the repository root, in `.env` (gitignored), with the storefront's `env_prefix`:

```text
STOREFRONT_A_DB_URL=postgresql://commerce_os_read.<project-ref>:...
```

## 4. Verify

```bash
python3 scripts/check_read_role.py storefront-a
```

The check connects in a read-only session and reports pass/fail, row counts for the three catalog
tables and catalog lists. It never prints the URL or password, and reads no customer rows. It
confirms:

- the role is not a superuser and can't create roles, create databases, bypass RLS or replicate;
- the role is a member of no other role;
- SELECT is allowed on exactly `products`, `categories` and `tags`, and denied on every other table;
- INSERT, UPDATE, DELETE and TRUNCATE are denied everywhere;
- wherever row-level security is on for a catalog table, a policy actually lets this role read it;
- which live categories and tags differ from `config/mappings/<storefront>.local.json`.

It changes nothing. Apply differences with `/edit-mappings <storefront>`.

**If the check says "password authentication failed"**, try the direct host
(`db.<project-ref>.supabase.co`) as well as the pooler:

- **Both fail:** the database holds a different password. Most often, a placeholder or masked copy was
  pasted in place of the real one. Set it again with
  `ALTER ROLE commerce_os_read WITH PASSWORD '...'`, copying from the generated file only.
- **Only the pooler fails:** it can serve a cached password for a minute or two after a change. Retry.

## Revoke

```sql
DROP POLICY IF EXISTS commerce_os_read_catalog ON public.products;     -- Supabase only
DROP POLICY IF EXISTS commerce_os_read_catalog ON public.categories;   -- Supabase only
DROP POLICY IF EXISTS commerce_os_read_catalog ON public.tags;         -- Supabase only
REVOKE ALL ON public.products, public.categories, public.tags FROM commerce_os_read;
REVOKE USAGE ON SCHEMA public FROM commerce_os_read;
REVOKE CONNECT ON DATABASE <db> FROM commerce_os_read;
DROP ROLE commerce_os_read;
```

Then remove the line from `.env`.
