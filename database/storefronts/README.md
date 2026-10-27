# Local storefront stand-ins

Throwaway local copies of a storefront's catalog tables, for adapter and contract tests (BACKLOG
B-029). Each copy reproduces the real `products`, `categories` and `tags` structure exactly, holds
invented seed data, and sits next to stand-in customer tables. Tests can then prove the read-only
role can't reach those tables.

**These files are never applied to a real storefront.** Commerce OS doesn't migrate storefront
schemas (PRD §18). `scripts/local_storefront_db.py` loads them only into a private local Postgres
cluster that listens on a Unix socket, never on a network port.

## Storefront A

| File | What it is |
|---|---|
| `storefront-a/catalog-structure.json` | The catalog tables' recorded structure: every column's type, default and nullability, every constraint, and a fingerprint of the whole. Recorded from the live database through the read-only role, and verified against the production schema dump. |
| `storefront-a/schema.sql` | Builds that structure, plus the stand-in `users` and `orders` tables and the Supabase lock-down (row-level security on every table, no policies). |
| `storefront-a/seed.json` | An invented catalog. Each product's `case` says what it exercises: an original with prints, a sold original, a draft with the placeholder description, an archived product, merchandise, and an out-of-stock product. |

The structure snapshot ignores column order; the Supabase copy and the production dump differ only
there. Storefront B is deferred (B-045). Its stand-in will add the `color_variants` feature column.

## Commands

```bash
python3 scripts/local_storefront_db.py up storefront-a      # fresh copy: schema, seed, runbook read role
python3 scripts/local_storefront_db.py status storefront-a  # how to connect
python3 scripts/local_storefront_db.py down storefront-a    # stop and delete
python3 scripts/local_storefront_db.py drift storefront-a   # has the real catalog structure changed?
```

`up` rebuilds from scratch every time. It refuses to finish if `schema.sql` doesn't reproduce
`catalog-structure.json`. The read role is created by running the SQL from
[docs/runbooks/read-only-role.md](../../docs/runbooks/read-only-role.md) §2a, so the runbook itself
is what gets tested.

`drift` connects to the real storefront with its read-only login in a read-only session. It reads
table structure from the system catalogs, never rows, and lists every difference. When the real
tables change, review the change, then update `schema.sql`, `catalog-structure.json` and the catalog
profile together. `snapshot` prints the live structure as JSON to help with that.

Requires PostgreSQL server binaries (`brew install postgresql@16`). `tests/test_local_storefront_db.py`
starts its own cluster for the live checks, and skips them when the binaries aren't installed.
