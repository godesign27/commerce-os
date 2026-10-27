# Storefront mappings

One file per storefront, `<storefront-id>.local.json` (gitignored, because it holds the storefront's
real category and tag names and IDs). [storefront.example.json](storefront.example.json) shows the
shape with fake values.

A mapping holds the storefront's **own lists** (categories, tags, tier types) and how Commerce OS's
[product types](../../resources/product-types/README.md) map onto them. Lists are per storefront and
per environment: an ID from one storefront or environment is never used for another.

## Add or edit a list

Run `/edit-mappings <storefront-id>` (or follow the `catalog-mappings` skill). It can:

- **Add** a category or tag that already exists in the storefront.
- **Edit** a name, slug, ID, status or product-type mapping.
- **Retire** an entry by setting `status: "excluded"`. Entries are never deleted, because approvals
  record the mapping version they used.
- **Merge** two entries that are the same thing (for example, different names in development and
  production): the survivor takes both environments' names and IDs, and the other is retired with
  `merged_into` pointing at the survivor.
- **Propose** a category or tag the storefront doesn't have yet (`status: "proposed_new"`). Creating
  it in the storefront is a storefront write, so it waits for an approved change set (Phase 3).

Every edit increases `version` and appends to `changes`. Once a read connection exists (Phase 2),
the same skill can refresh a list from the storefront and show the differences before saving.

## Shape

| Key | Meaning |
|---|---|
| `storefront`, `version`, `environments`, `changes` | Identity, integer version, the storefront's environments, and the edit history. |
| `tier_types` | The storefront's pricing-tier `type` values, case-sensitive. |
| `categories[]`, `tags[]` | `key` (stable within this file), `name` per environment, `slug` (or `null` if not verified), `id` per environment, `status` (`in_scope`, `excluded`, `proposed_new`), optional `merged_into` and `notes`. Tags also have `kind`: `type` or `descriptive`. |
| `product_types` | For each product type: its `category` key, optional `alternative_categories`, `type_tags` keys, and `proposed` (`true` until the owner confirms). |

At plan time, destination-mapping resolves each entry to the target environment's ID: the recorded
`id` first, then a verified `slug`, then the exact `name`. Anything it can't resolve is a blocking issue.
