# Catalog profiles

One JSON file per product-data shape a storefront application can have. A profile describes
structure only. Each storefront's actual values (categories, tier types, tag IDs) live in its own
mapping under `resources/storefront-mappings/<storefront-id>/`.

Profiles are written from a storefront's application schema and sanitized samples, never from
guesses. The model is explained in [docs/storefront-connections.md](../../docs/storefront-connections.md).

## Required keys

| Key | Meaning |
|---|---|
| `id` | Lowercase slug with a version suffix; must equal the filename. |
| `display_name` | Shown during storefront setup. |
| `sources` | What the profile was written from. |
| `catalog_tables` | Tables an adapter may read. Nothing else. |
| `write_tables` | Tables an adapter may write after approval. |
| `product` | Required insert columns, identity, money, status values, hidden status, concurrency. |
| `variants` | Where sellable variants live and their shape. |
| `optional_features` | Feature name → column and meaning. A storefront entry enables a subset. |
| `placeholders` | Values that mean "empty" and are never treated as data or written. |
