# Changelog

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
