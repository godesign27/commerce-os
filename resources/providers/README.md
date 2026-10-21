# Providers

One JSON file per database provider type. The model is explained in
[docs/storefront-connections.md](../../docs/storefront-connections.md).

## Required keys

| Key | Meaning |
|---|---|
| `id` | Lowercase slug; must equal the filename. |
| `display_name` | Shown during storefront setup. |
| `engine` | Database engine, e.g. `postgresql`. |
| `status` | `documented` (spec only), `adapter-built`, or `verified` (contract tests pass against a real test instance). |
| `used_for` | Any of `storefront`, `operational`. |
| `connection` | How the adapter connects and which environment variable suffixes it reads. Never values. |
| `roles` | The least-privilege read and write roles the adapter expects. |
| `assets` | Where product images live, the reference format, and how uploads work. |
| `schema_changes` | How the schema changes on this provider, and what that means for mapping fingerprints. |
| `verify_before_use` | Facts that must be checked against current provider documentation before an adapter is built. |
