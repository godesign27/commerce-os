# config

`storefronts.example.json` is the committed template. Your real configuration goes in
`storefronts.local.json`, which is gitignored because it holds real storefront names. Neither file ever
holds a credential: each entry names an `env_prefix`, and the values live in `.env`.

Create or change entries with `/setup-storefront`, or by hand following
[docs/storefront-connections.md](../docs/storefront-connections.md).

| Key | Meaning |
|---|---|
| `operational_database.provider` | Provider for Commerce OS's own database: any provider whose `used_for` includes `operational`. Always a separate project from every storefront. |
| `storefronts[].provider` | A file in `resources/providers/`. |
| `storefronts[].catalog_profile` | A file in `resources/catalog-profiles/`. |
| `storefronts[].features` | A subset of the profile's `optional_features`. |
| `storefronts[].env_prefix` | Unique per entry. The adapter reads `<prefix>_DB_URL`, and later `<prefix>_WRITE_DB_URL`. |
| `storefronts[].asset_upload` | `not_authorized` or `authorized`. Only an administrator changes it, after the provider's upload flow is approved. |
| `storefronts[].writes_enabled` | `false` until Phase 3 approval. |
