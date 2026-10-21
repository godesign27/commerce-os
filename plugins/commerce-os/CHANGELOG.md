# Changelog

## [0.2.0] - 2026-10-21

### Added

- `storefront-setup` skill and `/setup-storefront` command: choose a database provider and catalog
  profile for a storefront or the operational database, writing a credential-free entry to
  `config/storefronts.local.json`. Never connects and never handles a credential.
- CONNECTORS.md: a database-providers section; storefront rows note the provider comes from config.

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
