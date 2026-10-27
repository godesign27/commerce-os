# Product types

Commerce OS's own product types, shared by every storefront. A product type decides which options a
product can have and which facts are required. It's what PRD §6.1 calls a category template. A
storefront's own categories and tags are a separate list per storefront (see
[config/mappings/](../../config/mappings/README.md)), mapped to these types.

Add or edit types with `/edit-mappings product-types`, or by hand. Never delete a type: set
`status` to `retired`, because existing drafts record the type and version they used.

## Keys

| Key | Meaning |
|---|---|
| `id` | Lowercase slug; must equal the filename. |
| `display_name` | Shown to reviewers. |
| `version` | Integer; increase on every change. |
| `status` | `draft` (proposed, owner to confirm), `active`, or `retired`. |
| `kind` | `artwork` or `tangible`. |
| `aliases` | Other names reviewers and submitters use. Classification hints only, never evidence. |
| `options.color` | `allowed` or `not_applicable`. |
| `options.size` | `from_tiers`, `supplied_only` (never inferred from images), or `not_applicable`. |
| `variant_model` | How variants are formed for this type. |
| `required_facts` | Facts that must have authoritative evidence before approval. |

## The color rule (B-030)

Color is a property of the product type, not of the storefront:

- `not_applicable` (artwork): variant-grouping never creates a color option. Differently colored
  images are different artworks, or views of one artwork.
- `allowed` (tangible goods): each color that's clearly observed or supplied becomes a variant.
  Uneven lighting gets a review issue, not a new color.

When a product has more than one color, every destination it goes to must support colors (the
`color_variants` catalog-profile feature). If a destination doesn't, destination-mapping raises a
blocking issue for that destination only. The reviewer then chooses: publish a single color there, or
skip that destination. Commerce OS never splits colors into separate products on its own.

| Type | Kind | Color | Size |
|---|---|---|---|
| `artwork` | artwork | not_applicable | from_tiers |
| `bandana` | tangible | allowed | supplied_only |
| `hat` | tangible | allowed | supplied_only |
| `sunglasses` | tangible | allowed | not_applicable |
| `socks` | tangible | allowed | supplied_only |
| `blanket` | tangible | allowed | supplied_only |
| `hand-fan` | tangible | allowed | not_applicable |
