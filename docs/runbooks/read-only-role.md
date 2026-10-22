# Runbook: read-only catalog role for a storefront

Creates the login Commerce OS uses to read one storefront's catalog: `products`, `categories` and
`tags`, and nothing else. Customer tables (`users`, `orders`, `sessions`, `messages`, ...) share the
same database with row-level security off, so the role's grants are the only thing keeping customer
data out of reach (BACKLOG B-027, B-039).

Do this once per storefront database. The owner does it; Commerce OS never holds the owner login.

## 1. Generate a password, locally

```bash
openssl rand -base64 32 | tr -d '/+=' | cut -c1-40
```

Keep it in your password manager. Don't paste it into chat, tickets or committed files.

## 2. Create the role with SQL, not the console's Roles page

Neon grants roles created in the console, CLI or API membership in `neon_superuser`. Roles created
with SQL get only what you grant. Use the **SQL Editor** in the Neon console (project → branch →
database), or `psql -h pg.neon.tech` if you have psql installed.

First check which database you're in. Use this name in place of `<db>` below:

```sql
SELECT current_database();
```

Then:

```sql
CREATE ROLE commerce_os_read WITH LOGIN PASSWORD '<password from step 1>' CONNECTION LIMIT 3;
ALTER ROLE commerce_os_read SET default_transaction_read_only = on;
ALTER ROLE commerce_os_read SET statement_timeout = '15s';
GRANT CONNECT ON DATABASE <db> TO commerce_os_read;
GRANT USAGE ON SCHEMA public TO commerce_os_read;
GRANT SELECT ON public.products, public.categories, public.tags TO commerce_os_read;
```

Don't grant anything else, and don't run `ALTER DEFAULT PRIVILEGES` for this role.

## 3. Build the connection string

Copy the **host** from the project's existing connection string (Neon console → Connect). Use the
direct host, without `-pooler`. Then:

```text
postgresql://commerce_os_read:<password>@<host>/<db>?sslmode=require
```

## 4. Put it in `.env`, never anywhere else

In the repository root, in `.env` (gitignored), with the storefront's `env_prefix` from
`config/storefronts.local.json`:

```text
STOREFRONT_A_DB_URL=postgresql://commerce_os_read:...
```

## 5. Verify

```bash
python3 scripts/check_read_role.py storefront-a
```

The check connects in a read-only transaction and reports only pass/fail plus catalog lists. It never
prints the URL or password, and reads no customer rows. It confirms:

- the role is not a superuser and can't create roles, create databases, bypass RLS or replicate;
- the role is a member of no other role;
- SELECT is allowed on exactly `products`, `categories` and `tags`, and denied on every other table;
- INSERT, UPDATE, DELETE and TRUNCATE are denied everywhere;
- which live categories and tags differ from `config/mappings/<storefront>.local.json`.

It changes nothing. Apply differences with `/edit-mappings <storefront>`.

## Revoke

```sql
REVOKE ALL ON public.products, public.categories, public.tags FROM commerce_os_read;
REVOKE USAGE ON SCHEMA public FROM commerce_os_read;
REVOKE CONNECT ON DATABASE <db> FROM commerce_os_read;
DROP ROLE commerce_os_read;
```

Then remove the line from `.env`.
