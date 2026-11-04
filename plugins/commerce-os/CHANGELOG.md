# Changelog

## [0.8.0] - 2026-11-04

### Changed

- storefront-setup: a first-time setup now points to the dashboard's Getting started page (`./start.sh`),
  which connects and checks the store. The skill itself still never handles a credential and never
  connects to anything.

## [0.7.0] - 2026-10-29

### Changed

- listing-copy: when a piece shows an animal or a character, every title option contains its plain,
  searchable name ("Lion", "Rooster", "Unicorn"), so a shopper searching for it finds the piece. The
  model reports it as `subject_name` ("" for abstracts); real people and branded characters are never
  guessed. The subject's name no longer counts as a reused or shared title word. Prompt version
  `listing-draft@4`.

### Added

- Automatic warning: subject missing from title, on drafts and on titles the owner saves.

## [0.6.0] - 2026-10-29

### Changed

- listing-copy: collector descriptions are written as a small human story grounded in the piece. They
  open on a moment, feeling or encounter, let two or three visible details carry it, hedge once or
  twice, and end on a resonant thought or image rather than a routine question. The writing standards
  carry a worked example for tone (never a template), and the short description stays concise for
  browsing. Prompt version `listing-draft@3`.
- listing-copy rubric: new self-review criterion `human_story` ("Does this read like a small human
  story grounded in this particular piece, or like a visual inventory or generic art advertisement?");
  the recommend-as-is bar is now 12 of 14.
- listing-copy: a metallic or special surface (leaf, foil, shimmering, glinting, iridescent) is an
  unsupported claim unless the supplied medium says so.

### Added

- Automatic voice warnings on collector descriptions: closing question, stock art-marketing phrase,
  stacked hedges, a catalog-wide meaning restated, and wording borrowed from the worked example.

## [0.5.0] - 2026-10-28

### Added

- `listing-edit` administrator skill and `/listing-edit` command: change a drafted listing's title,
  descriptions, tags or keywords to the owner's own words from Claude Code ("change the wolf's title to
  …", "use this description instead", "pick the second title", "go back to the draft"). Saves the text
  exactly as given through `scripts/listing_edit.py`, runs the claim and repetition checks on it, and
  never approves, unlocks, redrafts or publishes.

### Changed

- commerce-lead points owner edits to `/listing-edit`.

## [0.4.0] - 2026-10-28

### Added

- `listing-copy` skill (catalog-draft): titles, descriptions, store tags and search keywords in the
  storefront's own voice. Three title options and a recommendation; every statement sorted into
  visible, artist-confirmed or proposed; questions for the artist; a self-review rubric. The craft is in
  `references/writing-standards.md` and `references/rubric.md`, which the drafting service also reads.
- `brand-context` administrator skill and `/brand-context` command: asks whether the storefront is an
  artist site or a product site, interviews the owner or imports a style guide, records meanings with a
  scope (one artwork, a series, the whole catalog), and reviews lessons learned from the owner's edits.
  Versioned, gitignored `config/brand/` files (contract `brand-context`).

### Changed

- storefront-setup asks the site kind and records `site_kind` and `brand_context` on the entry.
- canonical-drafting step 3 follows the listing-copy skill; commerce-lead routes `/brand-context`.

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
