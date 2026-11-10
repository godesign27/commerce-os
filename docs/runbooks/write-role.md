# Runbook: connect Publish to a live store

This lets Commerce OS add **Draft** products to one live store. The owner does every step here. An agent never
creates, sees or handles these logins, and they never go through the browser. Commerce OS never holds the
database owner login, the `postgres` role or a Supabase secret key.

Do this only after the store hides Drafts from the public (BACKLOG B-072).

## 1. Create the write login

Generate a password and keep it in your password manager:

```bash
openssl rand -base64 32 | tr -d '/+=' | cut -c1-40
```

In the Supabase dashboard, open the store's project, then **SQL Editor**. Replace the password and run this:

```sql
CREATE ROLE commerce_os_write WITH LOGIN PASSWORD '<password>' CONNECTION LIMIT 3;
ALTER ROLE commerce_os_write SET statement_timeout = '15s';
GRANT USAGE ON SCHEMA public TO commerce_os_write;
GRANT SELECT ON public.products, public.categories, public.tags TO commerce_os_write;
GRANT INSERT ON public.products TO commerce_os_write;
CREATE POLICY commerce_os_write_read ON public.products FOR SELECT TO commerce_os_write USING (true);
CREATE POLICY commerce_os_write_read ON public.categories FOR SELECT TO commerce_os_write USING (true);
CREATE POLICY commerce_os_write_read ON public.tags FOR SELECT TO commerce_os_write USING (true);
CREATE POLICY commerce_os_write_add ON public.products FOR INSERT TO commerce_os_write WITH CHECK (status = 'draft');
```

The last line is what forces Draft: the database refuses anything else from this login, even if Commerce OS had a
bug. The login can't edit or delete anything, and it can't see customers or orders.

Don't grant anything else. Never give this role `BYPASSRLS`, and don't add it to any other role.

## 2. Create the upload login

1. In **Authentication**, then **Users**, choose **Add user**, then **Create new user**.
2. Use an address only for this, such as `commerce-os-uploads@` on your own domain. Give it its own long password
   and auto-confirm it.
3. Copy the new user's **UID**.

Then, in the **SQL Editor**, put that UID in place of `<uid>` (keep the quotes around it), change the bucket if yours
isn't `artwork`, and run this:

```sql
CREATE POLICY commerce_os_upload ON storage.objects FOR INSERT TO authenticated
  WITH CHECK (bucket_id = 'artwork' AND auth.uid() = '<uid>'::uuid AND (name LIKE 'uploads/%' OR name LIKE '_meta/uploads/%'));
```

If it stops with `invalid input syntax for type uuid: "<uid>"`, the UID wasn't filled in: nothing was saved, so fill
it in and run it again.

This user can add images to those two folders. It can't read, replace or delete anything, and your store signs in
with Clerk, so it gets no access to the store itself.

## 3. Save the settings

Add these to `.env` in the Commerce OS folder, with a text editor. `STOREFRONT_A` is this store's `env_prefix`. The
read login is already there from Getting started.

```text
STOREFRONT_A_WRITE_DB_URL=postgresql://commerce_os_write.<project-ref>:<password>@<pooler host>:5432/postgres?sslmode=require
STOREFRONT_A_SUPABASE_URL=https://<project-ref>.supabase.co
STOREFRONT_A_SUPABASE_PUBLISHABLE_KEY=<publishable key from Settings, then API Keys>
STOREFRONT_A_UPLOAD_EMAIL=<the upload login's address>
STOREFRONT_A_UPLOAD_PASSWORD=<the upload login's password>
STOREFRONT_A_STORAGE_BUCKET=artwork
```

Use the same pooler host as the read login. Use the publishable key, never the secret key.

## 4. Check everything

This only reads, and it never prints a login:

```bash
.venv/bin/python scripts/go_live.py storefront-a
```

It lists anything that's wrong. Fix each item and run it again.

## 5. Turn it on

```bash
.venv/bin/python scripts/go_live.py storefront-a --on
```

Stop Commerce OS with Ctrl-C and start it again with `./start.sh`.

Listings approved for the test store need approving again, because an approval names where it goes. Publish **one**
piece first, and confirm in store admin that it's a Draft and its images show. Then confirm it isn't on the art wall
or the shop, and that its direct link says not found when you're signed out.

## Turning it off

```bash
.venv/bin/python scripts/go_live.py storefront-a --off
```

Then restart. Publish goes back to the local test store. To stop writing right away, press **Stop all writing** on the
Publish page. To remove access completely, run this in the SQL Editor and delete the upload user:

```sql
DROP POLICY commerce_os_upload ON storage.objects;
DROP POLICY commerce_os_write_add ON public.products;
DROP POLICY commerce_os_write_read ON public.products;
DROP POLICY commerce_os_write_read ON public.categories;
DROP POLICY commerce_os_write_read ON public.tags;
REVOKE ALL ON public.products, public.categories, public.tags FROM commerce_os_write;
REVOKE USAGE ON SCHEMA public FROM commerce_os_write;
DROP ROLE commerce_os_write;
```
