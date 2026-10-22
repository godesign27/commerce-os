# Changelog

## [0.3.0] - 2026-10-21

### Added

- `catalog-mappings` skill and `/edit-mappings` command: add, edit, retire or propose a storefront's
  categories, tags and tier types, and Commerce OS's product types. Versioned, local files only; never
  creates anything in a storefront.
- catalog-mappings can merge two entries that are the same thing (survivor keeps both environments'
  names and IDs; the other is retired with `merged_into`).

### Changed

- Product types (`resources/product-types/`) replace category templates. Each type sets whether a color
  option is allowed: artwork none, tangible goods allowed (B-030).
- variant-grouping creates a color option only when the product type allows it; sizes follow the type.
- destination-mapping resolves categories and tags per environment from the storefront's mapping, and
  blocks multi-color products only for destinations without color support.
- product-classification and canonical-drafting use product types.

## [0.2.0] - 2026-10-21

### Added

- `storefront-setup` skill and `/setup-storefront` command: choose a database provider and catalog
  profile for a storefront or the operational database, writing a credential-free entry to
  `config/storefronts.local.json`. Never connects and never handles a credential.
- CONNECTORS.md: a database-providers section (now listing `replit-postgres`, `neon`, `supabase`); storefront rows note the provider comes from config.

### Changed

- Every skill's status section is now `Current status` instead of `Phase 0a status`.
- catalog-retrieval and destination-mapping status updated: schemas are known; mappings are not written yet.
- commerce-lead sends setup requests to `/setup-storefront` rather than a specialist.

## [0.1.0] - 2026-10-20

### Added

- Phase 0a scaffold: router agent `commerce-lead` and four specialist agents (`intake-assets`,
  `product-intelligence`, `catalog-draft`, `review-publishing`).
- Twelve skill specifications from PRD §6.1, each with inputs, outputs, allowed tools, forbidden
  actions, validation, failure behavior and evidence requirements.
- Commands `/intake`, `/review`, `/dry-run`, `/publish` as thin pointers to skills.
- Shared policies: `COMMERCE-CONTEXT.md`, `evidence-policy.md`, `WORKFLOW.md`, `CONNECTORS.md`, and
  output templates.
- No MCP connectors and no write capability. No runtime system yet.
