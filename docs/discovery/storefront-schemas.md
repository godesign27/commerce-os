# Storefront schema discovery

Status: Phase 0b. Sources, all kept in `discovery/raw/` (gitignored):

- Schema-only dumps received 2026-10-21: Storefront A production and development; Storefront B
  production and development.
- Owner handoffs received 2026-10-21: each storefront's application schema (`shared/schema.ts`),
  Storefront A product samples from production, and written answers to B-024, B-025, B-026, B-031
  and B-032. See [Confirmed by the owner's handoffs](#confirmed-by-the-owners-handoffs).

Confirmed means read directly from the dumps. Inferred means a reasonable reading that still needs
the owner or the application code to confirm.

## Headline findings

1. **Neither storefront is on Supabase.** Both dumps identify Replit-managed PostgreSQL 16 on Neon
   (`neondb`, `heliumdb`). PRD §1.1 lists "two ecommerce sites currently use Supabase" as confirmed.
   That is contradicted by the dumps (BACKLOG B-023). It changes the adapter, not the architecture:
   both are plain Postgres, reached with a restricted SQL role.
2. **Both sites share one codebase lineage and have since diverged.** Same table set, same
   Drizzle-style constraint names (`*_fk`, `*_unique`). The product-relevant differences are below.
   PRD §15 still applies: separate adapters, mappings and credentials, no shared SQL path.
3. **There is no variants table.** A product is one `products` row. Options live in JSONB:
   `pricing_tiers` on both sites, `color_variants` on B only. Storefront A has no color field at all.
4. **Inserting a product makes it live by default.** `products.status` defaults to `'active'` and has
   no check constraint, so an insert that omits status publishes. Every change set must set status
   explicitly. The application's values are `active`, `draft` and `archived`, so a hidden create is
   `draft`.
5. **The catalog shares a database with customer data, without row-level security.** Each site has
   `users`, `orders` (names, emails, phone, shipping address), `sessions`, `messages`,
   `commission_requests` and subscription tables in the same `public` schema, and B's dump reports RLS
   disabled on every table. The Commerce OS read role must be limited by GRANT to catalog tables only
   (B-027).
6. **No triggers, functions, enums, RLS policies or check constraints** exist in any dump. `updated_at`
   defaults to `now()` but nothing updates it on change, so it is not a reliable concurrency token.

## Environments

| Storefront | Dumps | Difference |
|---|---|---|
| A | Production (`neondb`); development (`heliumdb`) | Identical tables, columns, constraints and indexes. |
| B | Production; development | Identical, except production also has Replit's `_system.replit_database_migrations_v1`. |

That migrations table means Replit deployments apply schema changes to production. A storefront
schema can change underneath a mapping without Commerce OS knowing (B-028).

## Catalog tables

| Table | Key columns | Notes |
|---|---|---|
| `products` | `id` varchar PK (default `gen_random_uuid()`), `slug` NOT NULL UNIQUE, `sku` UNIQUE nullable, `name` NOT NULL, `price` numeric(10,2) NOT NULL | The only product record. |
| `categories` | `id`, `name`, `slug` UNIQUE, `is_active`, `is_featured`, `sort_order` | `products.category_id` FK, nullable. |
| `tags` | `id`, `name` UNIQUE, `slug` UNIQUE | Not linked by FK; products carry a `tags` JSONB array (inferred: names or slugs). |
| `gallery_items` | `title`, `image_url`, `medium`, `dimensions`, `year`, `is_published` | Separate from products. Scope question (B-031). |

### `products` columns

| Column | Type / default | A | B | Commerce OS meaning | Evidence class |
|---|---|---|---|---|---|
| `id` | varchar, `gen_random_uuid()` | ✓ | ✓ | Destination product ID | Identity |
| `name` | text NOT NULL | ✓ | ✓ | title | Copy |
| `description`, `short_description` | text | ✓ | ✓ | description | Copy |
| `slug` | text NOT NULL UNIQUE | ✓ | ✓ | Destination URL key | Identity |
| `sku` | text UNIQUE | ✓ | ✓ | sku (product level) | Commercial |
| `price` | numeric(10,2) NOT NULL | ✓ | ✓ | Destination price; no currency column | Commercial |
| `stock` | integer, default 0 | ✓ | ✓ | Destination stock, storefront-owned | Commercial |
| `status` | text, default `'active'` | ✓ | ✓ | Destination visibility | Destination |
| `is_featured` | boolean, default false | ✓ | ✓ | Merchandising flag | Destination |
| `category_id` | FK `categories.id` | ✓ | ✓ | category mapping | Mapping |
| `images` | jsonb, default `[]` | ✓ | ✓ | Ordered asset references (shape unknown) | Asset |
| `tags` | jsonb, default `[]` | ✓ | ✓ | Tags | Mapping |
| `pricing_tiers` | jsonb, default `[]` | ✓ | ✓ | Option axis with per-tier price (inferred from `cart_items.tier_id`) | Commercial |
| `color_variants` | jsonb, default `[]` | — | ✓ | Color option axis (cart stores `color`, `color_hex`) | Observed/supplied |
| `dimensions` | text | ✓ | ✓ | dimensions, free text with no unit field | Commercial |
| `medium` | text | ✓ | ✓ | material / medium | Commercial |
| `year` | integer | ✓ | ✓ | year created | Supplied |
| `is_original` | boolean, default false | ✓ | ✓ | Original vs reproduction | Rights/authenticity |
| `rarity` | text | ✓ | ✓ | Edition / rarity claim | Rights/authenticity |
| `frame`, `packaging` | text | ✓ | ✓ | Product configuration and shipping detail | Commercial |
| `authenticity` | text | ✓ | ✓ | Authenticity claim | Rights/authenticity |
| `show_in_gallery` | boolean, default false | ✓ | — | Also list in gallery | Destination |
| `is_sold` | boolean, default false | ✓ | — | Sold flag (one-off pieces) | Commercial |
| `created_at`, `updated_at` | timestamp, `now()` | ✓ | ✓ | Operational only | — |

`rarity`, `authenticity` and `is_original` are claims the evidence policy treats like rights and
certification: they need `supplied` or `human_confirmed` evidence, never visual inference. `medium`
counts as material. Exact decimal `price` satisfies PRD §8.2, but currency is implicit per site (B-026).

### Other tables that reference products

`cart_items` (FK, no cascade), `favorites` (cascade), and on A only `board_items` and `board_stars`
(cascade). `orders.items` and `art_wall_simulations.artworks` hold product data in JSONB without an
FK. Deleting a product cascades into favorites and boards, which supports the PRD's no-delete default.

## Design implications

| Topic | Implication | Where it lands |
|---|---|---|
| Variants | Canonical variants map to JSONB entries, not rows. Variant SKU/GTIN have no column unless the JSONB holds them. | destination-mapping, adapters |
| Multi-color on A | A has no color field. A multi-color product for A needs a decision: separate products, one product with images only, or B only. | B-030 |
| Required at insert | `name`, `slug`, `price`. No destination product can exist without an approved price, which matches the evidence policy's blocking rule. | canonical-drafting, destination-mapping |
| Visibility | Always set `status` explicitly to the approved value. Never rely on the default. | change-set template, Gate 4 |
| Idempotent create | Commerce OS can supply the product `id` (UUID) and `slug` in the change set. A retry becomes a lookup by `id`, then an insert guarded by `ON CONFLICT (id) DO NOTHING`, with no duplicate. | publishing, reconciliation (AC-09) |
| Update preconditions | `updated_at` isn't maintained. Use a hash of the mapped columns as the expected-version precondition. | destination-mapping, Gate 4 (AC-11) |
| Schema drift | Record a schema fingerprint (catalog columns plus types) with each mapping version; Gate 4 refuses to write if it changed. | B-028 |
| Least privilege | Read role: SELECT on `products`, `categories`, `tags` only. Write role: INSERT/UPDATE on `products` (and `categories` only if approved). No access to customer tables. | B-027, docs/security.md |
| Test databases | The dumps load cleanly into an empty Postgres 16. Local A and B test databases built from them give real-schema adapter contract tests without touching either site. | B-029 |
| Images | `images` JSONB likely holds URLs. Where those files live, and whether Commerce OS may upload there, is unknown. | B-025 |

## Confirmed by the owner's handoffs

### JSONB shapes (B-024)

| Field | A | B |
|---|---|---|
| `images` | `string[]` of app-relative object paths, `/objects/uploads/<id>` | Same |
| `tags` | `string[]` of `tags.id` values, not names | Same |
| `pricing_tiers` | `{id, size, price, type, stock, description}[]` | Same, plus optional `quantity` |
| `color_variants` | Not defined; do not invent a mapping | `{id, name, hex, imageIndices}[]` |

- **Pricing tiers are the sellable variants.** Each tier has its own `price` and `stock`; the product's
  own `price` and `stock` mirror one tier (on A's samples, the Original). A canonical variant maps to
  one tier.
- **Tier `type` values on A production, case-sensitive:** `Original` (43), `Print` (138), `Canvas Print`
  (142). B's development samples use the same three types, including on non-art goods, so the type
  vocabulary is per storefront and per category, not a fixed list.
- **Tier `id` is the identity**, formatted `tier-<epoch milliseconds>`. `size` is free text and
  inconsistent (`16x20` beside `16 x 20 inches`), so it is never used to identify a tier.
- **Placeholder text is not data.** Many tier descriptions are the editor default `Enter description`.
  Catalog retrieval treats it as empty, and Commerce OS never writes it.
- **`is_original` doesn't reliably describe tiers.** A's samples have `Original` tiers with
  `is_original = false`. Never infer one from the other.
- **B's color variants point at images by position** (`imageIndices`). Reordering `images` changes
  which photos belong to which color, so the image order is part of the approved change set.
- **`is_sold` is separate from status (A).** A sold original stays visible with its Original tier
  unpurchasable while prints remain for sale. Marking an original sold is an update, not an unpublish.
- **Status values:** `active`, `draft`, `archived`. A production: 39 products, all `active`. B: `active`
  and `draft` observed in both environments.

### Images (B-025)

Both storefronts store product images in Replit App Storage (Google Cloud Storage underneath), served
through the app at `/objects/uploads/<id>` (A: 76 of 76 production references). Upload is an
admin-authorized flow: request a signed upload URL, PUT the file, then finalize with visibility, which
returns the object path. **Commerce OS has no upload permission on either storefront.** A's owner
also reports a development fallback credential in A's upload authorization code; it must be removed
before any external integration gets upload access (B-033).

### Currency (B-026)

Both storefronts use USD. Stored prices are major units in exact decimal (`995` means $995.00);
checkout converts to cents for Stripe.

### Scope (B-031)

`gallery_items` is editorial gallery content on both sites (A production: 3 rows, no price, SKU or
inventory). It is excluded from Commerce OS product mapping. `products.show_in_gallery` (A) is a
separate flag on products and is in scope.
