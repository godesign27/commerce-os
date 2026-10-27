# database/

Commerce OS never migrates a storefront's schema. Any storefront change needs a separate reviewed
migration plan (PRD §18).

- `operational/`: draft migrations for the operational database, Commerce OS's own project (B-018).
  See [operational/README.md](operational/README.md).
- `storefronts/`: local stand-ins for storefront catalog tables, loaded only into a throwaway local
  cluster for tests (B-029). See [storefronts/README.md](storefronts/README.md).
