# database/

Operational database only (Commerce OS's own project). Storefront schemas are never migrated from here;
any storefront change needs a separate reviewed migration plan (PRD §18).

- `operational/migrations/`: draft migrations for the operational database (B-018). See
  [operational/README.md](operational/README.md).
