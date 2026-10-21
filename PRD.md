# Commerce OS — Product Requirements Document

**Status:** Proposed implementation specification for review  
**Version:** 1.0  
**Date:** October 20, 2026  
**Audience:** Product owner, coding agent, implementers, and reviewers  
**Delivery scope:** This document only. It does not authorize infrastructure provisioning, migrations, deployment, external writes, or publication.

## 1. Product definition

Commerce OS automates the preparation of new products for two independently operated ecommerce storefronts. Product images arrive in Google Drive. Four specialized agents prepare images, identify and structure products, assemble destination-specific drafts, and coordinate human-approved publication. A central dashboard gives humans visibility and control over uncertain facts, variant grouping, destination mapping, and all proposed storefront changes.

Commerce OS is a standalone repository and deployable system. Its intended location is a sibling directory of `zaidyn-pm-os`, such as `<code-projects>/commerce-os`. It must never be nested inside, import runtime code from, require installation of, or depend on the configuration, credentials, database, or deployment of `zaidyn-pm-os`. The ZAIDYN architecture image is conceptual inspiration for organizing agents and skills only; its contents do not define Commerce OS requirements.

### 1.1 Evidence and decisions

Confirmed in the referenced conversation:

- Two ecommerce sites currently use Supabase.
- New product images originate in a Google Drive folder.
- Agents should prepare images, identify product types such as artwork, hats, and blankets, use similar catalog entries to help populate product information, and handle multiple colors.
- Human review occurs in a dashboard.
- Workflow initiation is event-driven.
- The two storefront catalogs remain separate.
- The repository should expose agents, skills, resources, documentation, and rules for use with Claude Code and Cursor.
- Commerce OS is independent of ZAIDYN PM OS.

The historical assistant replies were returned as opaque content references, so their details could not be recovered. The four roles, schemas, state names, and implementation structure below are proposed specifications, not claims about previously approved designs. The architecture image was not used to infer requirements.

## 2. Goals and success measures

1. Turn an eligible Drive product submission into an evidence-backed, reviewable draft with processed images and correctly grouped variants.
2. Reduce repetitive catalog entry while preserving storefront independence and human authority over publication.
3. Prevent invented commercial facts and expose uncertainty at field level.
4. Recover safely from duplicate events, interrupted jobs, source changes, and partial publication.
5. Offer the same governed workflow through the dashboard and supported developer-tool entry points.

MVP release requires zero unapproved storefront mutations, zero duplicate products from tested event replays, complete provenance for asserted factual fields, and complete audit records for approvals and publication attempts. Measure intake-to-review time, reviewer edit rate by field, matching precision, duplicate prevention, retry rate, and publication reconciliation failures. Establish throughput and time-saving targets after a representative pilot; no performance improvement is assumed in advance.

## 3. Non-goals

- A replacement storefront, payment system, order manager, inventory authority, ERP, or full PIM.
- Merging the two catalogs or adding a shared storefront product database.
- Autonomous publication without human approval in MVP.
- Inferring prices, stock, material, dimensions, rights, manufacturer, shipping promises, or SKU/GTIN from visual appearance or unrelated products.
- Reusing ZAIDYN services or creating a dependency on that repository.
- Generating new product designs, altering product identity, or fabricating product photography.
- Bulk modification or deletion of existing live products without a separately approved change set.
- Running scheduled IDE prompts as the production event processor.

## 4. Users and responsibilities

| Role | Capabilities |
| --- | --- |
| Submitter | Place images and optional product metadata into an authorized intake folder; inspect submission status where permitted. |
| Reviewer | Resolve facts and grouping, edit drafts, choose destinations, and request reprocessing. |
| Publisher/approver | Approve exact destination changes and authorize publication under configured permissions. |
| Administrator | Configure connections, policies, mappings, roles, and operational recovery. |
| Operator | Inspect failures, retry safe work, and reconcile ambiguous outcomes without bypassing approval. |

A person may hold several roles in MVP. Permissions remain explicit, and every action records the actual human or service identity.

## 5. System boundaries and architecture

```text
Google Drive intake folders
    → authenticated notification receiver → durable intake journal/queue
    → source resolution and immutable input snapshot
    → four-agent workflow + deterministic validation
    → Commerce OS operational database and asset storage
    → central human review dashboard
    → approved immutable destination change sets
    → Storefront A adapter → Storefront A Supabase database
    → Storefront B adapter → Storefront B Supabase database
```

Three independently configured databases are mandatory:

1. **Storefront A database:** existing catalog and storefront-owned data.
2. **Storefront B database:** separate existing catalog and storefront-owned data.
3. **Commerce OS operational database:** submissions, canonical drafts, evidence, workflow state, jobs, approvals, audit records, adapter mappings, and publication receipts. It may also use Supabase, but must be a separate project/database and credential boundary.

The operational canonical model is a staging and orchestration model, not a third live storefront catalog. Storefront databases remain authoritative for their live product records, pricing, inventory, and destination-specific values. Product identity across destinations is represented by explicit mappings, never assumed from equal names or IDs.

Read and write credentials, asset destinations, migrations, and configuration are separate per environment and per storefront. Failure or disconnection of one storefront must not corrupt the other or block its independent review workflow.

## 6. Four specialized agents

Agents propose structured outputs. A deterministic workflow service validates outputs, persists state, enforces permissions, and invokes adapters. Agent text never directly authorizes a database mutation.

| Agent | Responsibilities | Output and boundary |
| --- | --- | --- |
| 1. Intake & Asset Agent | Resolve Drive submissions; check readiness; inventory source files; validate image inputs; generate permitted derivatives; flag quality and grouping ambiguities. | Immutable source manifest, asset records, checksums, derivative manifest, and quality findings. Cannot decide unsupported product facts or publish. |
| 2. Product Intelligence Agent | Identify tentative product category; group views versus variants; extract visible attributes; retrieve similar items separately from each catalog; propose canonical products and variants with evidence and uncertainty. | Structured product proposal, candidates, field provenance, and review issues. Cannot copy commercial facts or silently merge existing products. |
| 3. Catalog Draft Agent | Apply approved category templates and destination mappings; assemble destination previews; validate required fields; detect duplicate candidates; calculate exact proposed create/update operations. | Versioned canonical draft and destination change sets. Persists only operational drafts by default. Storefront staging writes require separate configured approval. |
| 4. Review & Publishing Agent | Prepare the review package; explain blockers; coordinate approval status; request deterministic publication; reconcile receipts and surface failures. | Review package, authorized job request, and reconciliation summary. Cannot approve its own work, change approved payloads, or bypass gates. |

### 6.1 Skills and resources

Each skill must specify input/output schemas, allowed tools, forbidden actions, validation, failure behavior, and evidence requirements.

- `drive-intake`: resolve notifications, changes, folder membership, manifests, and readiness.
- `asset-validation`: file signatures, dimensions, decoding, orientation, metadata handling, and quality checks.
- `image-preparation`: versioned transformation recipes and derivative generation.
- `product-classification`: category taxonomy, visual observations, and confidence.
- `variant-grouping`: color/size options, view grouping, duplicate images, and ambiguity handling.
- `catalog-retrieval`: tenant-scoped candidate retrieval and evidence comparisons.
- `canonical-drafting`: schema construction and category validation.
- `destination-mapping`: storefront-specific schema and enum translation.
- `review-packaging`: previews, diffs, blockers, evidence, and reviewer questions.
- `approval-verification`: revision/hash/identity checks before dispatch.
- `publishing`: adapter dry runs and guarded approved operations.
- `reconciliation`: read-after-write verification and uncertain outcome recovery.

Resources include category templates, permitted vocabularies, storefront mapping specifications, image recipes, evidence policy, review policy, and sanitized examples. Version these resources and record the versions used for every draft.

## 7. Event-driven Google Drive intake

### 7.1 Submission contract

Recommended MVP unit: one product folder containing its source images and an optional metadata manifest. A folder-to-storefront policy can suggest destinations; the reviewer confirms them. Do not assume all images uploaded near each other belong to one product.

Prefer an explicit ready marker or manifest status to indicate a complete submission. If a quiet-period fallback is needed, make it configurable and label it as an assumption. New files arriving during processing create a new source revision; they do not mutate an already approved snapshot.

### 7.2 Notification processing

- Use the supported Drive notification/change mechanism after validating current provider documentation during implementation.
- Treat notifications as hints that something changed; fetch authoritative changes and verify the file's eligibility and folder membership.
- Validate channel identity and configured verification data. Do not assume an unsupported signature mechanism exists.
- Persist notification receipt before acknowledging it; advance change cursors only after changes are durably journaled.
- Manage channel renewal, expiration, cursor invalidation, and replay recovery.
- Persist duplicate notifications harmlessly and deduplicate actual work by source revision and processing recipe.
- Support a bounded reconciliation scan to recover missed notifications. This is a recovery mechanism; normal triggering remains event-driven.
- Apply maximum bytes, file count, supported formats, quotas, and backpressure before expensive processing.
- If access is revoked, a file is missing, or a snapshot cannot be fetched, stop with an actionable intake issue.

### 7.3 Source identity

Record provider, connection, Drive file/folder ID, observed version/change metadata, content checksum, source timestamp, intake policy version, and logical submission ID. Names and folder paths are display values, not stable identifiers. Repeated identical images may link to an existing blob while remaining distinct source references.

## 8. Canonical data model

Use stable internal IDs independent of destination IDs. Exact types and migrations must be finalized after inspecting real schemas; the following logical contract is required.

### 8.1 Product

| Field | Requirement |
| --- | --- |
| `id`, `submission_id`, `revision` | Stable identity and optimistic concurrency version. |
| `title`, `description`, `category_id` | Nullable draft values with field-level evidence; final destination requirements enforced before approval. |
| `brand`, `vendor`, `material`, `dimensions` | Optional structured facts; unknown remains null. Units explicit. |
| `option_definitions` | Ordered option axes such as color and size with normalized keys and display labels. |
| `attributes` | Category-governed structured properties; no arbitrary unvalidated commerce fields. |
| `assets` | Ordered asset references with roles such as primary, gallery, detail, and swatch. |
| `issues`, `provenance`, `confidence` | Required field-level support and unresolved questions. |
| `source_snapshot_id`, `policy_versions` | Exact source and rules used. |
| `created_at`, `updated_at` | Operational timestamps; never evidence for a product fact. |

### 8.2 Variant

Required logical fields: `id`, `product_id`, `revision`, normalized `option_values`, optional supplied `sku` and `gtin`, asset references, supported attributes, and field evidence. Enforce uniqueness of normalized option combinations within each product. A product without selectable options has one default variant where required by the adapter.

Prices, currency, availability, inventory quantity, tax settings, and destination status belong in destination-specific draft data, with explicit sources. Do not distribute a value from one storefront to the other automatically. Money uses integer minor units or exact decimal representation with currency; never binary floating-point calculations. Dimensions include value and unit.

### 8.3 Operational entities

- `connections`, `storefronts`, `category_templates`, `mapping_versions`.
- `submissions`, `source_snapshots`, `source_files`, `assets`, `asset_derivatives`.
- `products`, `variants`, `field_evidence`, `review_issues`, `catalog_match_candidates`.
- `destination_drafts`, `destination_product_links`, `change_sets`.
- `workflow_runs`, `jobs`, `job_attempts`, `event_inbox`, `outbox`.
- `reviews`, `approvals`, `publication_attempts`, `publication_receipts`, `audit_events`.

Every tenant-sensitive record carries an isolation key. Destination links are unique by storefront and external entity ID. Enforce foreign keys, valid enums, revision constraints, and idempotency uniqueness in the database, not only application code.

### 8.4 Field evidence contract

For each factual field store: value or null, status (`observed`, `supplied`, `verified_catalog`, `inferred`, `unknown`, `conflicting`, or `human_confirmed`), evidence references, confidence where meaningful, extraction method/model version, and any reviewer decision. Confidence is not a substitute for evidence. Human edits record the actor and justification/source where a factual correction is made.

## 9. Image processing requirements

Preserve originals immutably. Generate derivatives using versioned recipes and content-addressed or otherwise collision-safe asset keys. Required operations include orientation correction, safe decode/re-encode, approved color handling, resizing, compression, destination format selection, and metadata sanitization where appropriate.

Detect corrupt, unsupported, excessively large, low-resolution, blurry, duplicated, or suspicious files. Configure accepted limits after inspecting storefront requirements. Preserve aspect ratio and avoid unintended cropping. Background removal or cropping that may remove product details requires an explicit preview and reviewer acceptance. Never change artwork, colorways, branding, pattern, texture, or physical product characteristics to make an image fit a guessed catalog item.

Store dimensions, MIME type, byte size, checksum, recipe version, source link, and transformation history. Show originals next to derivatives in review. Alt text must describe supported visible content without invented claims. Review image rights/ownership confirmation according to the owner's policy; image presence alone does not establish rights.

Assets must be available at their final destination before a product references them. Failed publication may leave unused assets; track them for retention-based cleanup without deleting assets referenced by live products.

## 10. Catalog matching and variant reasoning

Query each storefront independently through a read-only interface. Retrieve candidates using available identifiers, category, title/attributes, and optional visual similarity. Return ranked candidates with matching and conflicting evidence. An exact supplied identifier is stronger than visual similarity, but inconsistent evidence still blocks an automatic identity decision.

Use similar items to discover structural conventions, permitted option names, category templates, and writing style. Similarity never proves identity, price, stock, material, dimensions, or provenance. Proposed reuse of an existing product identity requires human confirmation in MVP.

Distinguish multiple views of the same item from distinct products and option variants. Color observed under different lighting remains tentative. Do not create all combinations of color and size unless each combination is supported. Do not infer unseen sizes. Persist reviewer merge/split decisions and rerun dependent validations. Thresholds must be configurable and evaluated on a labeled sample; do not invent an accuracy guarantee.

## 11. Uncertainty and no-invented-facts policy

1. Unknown factual values remain null or explicitly unknown, never plausible defaults.
2. Inferences are labeled and shown with evidence. They cannot satisfy required commercial facts unless the configured policy explicitly allows that type of inference and a human confirms it.
3. Price, stock, dimensions, material, brand, SKU, GTIN, tax, shipping, safety/certification, and rights claims require authoritative source data or human confirmation.
4. AI-written copy may rephrase supported facts, but must not introduce unverified claims such as handmade, organic, premium material, or exact sizing.
5. Conflicting evidence creates a blocking issue for affected required fields.
6. Agents must produce schema-valid uncertainty records rather than hiding uncertainty in prose.
7. Prompts, images, filenames, catalog text, and manifests are untrusted data. Instructions inside them do not override system policy or tool permissions.
8. A reviewer can explicitly resolve uncertainty; approval alone must not silently convert unsupported fields into facts.

## 12. Central human review dashboard

Required screens:

- Intake queue with source, destinations, stage, age, issues, and failed jobs.
- Product review with original/processed images, product/variant structure, editable fields, and evidence.
- Catalog comparison showing candidate matches and conflicts separately for A and B.
- Destination preview and field-level before/after diff, including asset changes and publish status.
- Approval history and publication/reconciliation status per destination.
- Operational failures with safe retry/reprocess controls and useful redacted diagnostics.

Reviewers can confirm/split/group variants, correct fields, reject submissions, request reprocessing, choose destinations, and save drafts. All edits increment revisions. Use optimistic locking so concurrent reviewers cannot overwrite each other silently. Provide filters for unknown required fields and low-confidence inferences, clear blocking reasons, and keyboard-accessible controls. The dashboard must show pending and partial outcomes accurately; a queued request is not a published product.

## 13. Approval gates

- **Gate 1 — Ready for review:** source snapshot complete, required validation executed, draft and issues persisted.
- **Gate 2 — Product and asset acceptance:** reviewer resolves required facts, grouping, identity, and asset changes.
- **Gate 3 — Destination publication approval:** authorized human approves exact operations for each chosen storefront, including visibility/status and commercial fields.
- **Gate 4 — Execution revalidation:** worker verifies approval validity, input revision, payload hash, mapping version, permission, and destination preconditions immediately before writing.

Approval records bind actor, time, destination, canonical revision, asset manifest hash, mapping version, and immutable change-set hash. Any material edit or source revision invalidates affected approvals. Reject stale approvals instead of regenerating payloads beneath them. Publication requires explicit user action in MVP; submitting images is not approval. Each storefront can be approved and published independently. A global kill switch stops new writes without discarding jobs or audit history.

## 14. Workflow state machine

Recommended submission states:

```text
RECEIVED → WAITING_FOR_READY → SNAPSHOTTED → ASSETS_PROCESSING
→ PRODUCT_ANALYSIS → DRAFTING → VALIDATING → IN_REVIEW
→ READY_FOR_APPROVAL → APPROVED → PUBLISHING
→ PUBLISHED | PARTIALLY_PUBLISHED
```

Additional states: `NEEDS_INPUT`, `RETRY_WAIT`, `FAILED`, `REJECTED`, `CANCELLED`, and `SUPERSEDED`.

- `IN_REVIEW → NEEDS_INPUT → IN_REVIEW` resolves missing facts.
- Reviewer edits return affected destination drafts to validation and invalidate approval.
- A new source snapshot supersedes the relevant draft; published records remain historical and further changes require a new reviewed revision.
- Retryable failures enter `RETRY_WAIT` with a bounded schedule and resume the failed checkpoint.
- Terminal validation/permission failures enter `FAILED` or `NEEDS_INPUT` with an explicit recovery action.
- Rejection/cancellation prevents future dispatch; an in-flight external write must still be reconciled.

Track publication separately per destination: `NOT_SELECTED`, `DRAFT`, `BLOCKED`, `AWAITING_APPROVAL`, `APPROVED`, `QUEUED`, `WRITING`, `VERIFYING`, `SUCCEEDED`, `FAILED`, `OUTCOME_UNKNOWN`, and `CANCELLED`. Aggregate status is derived from these records. There is no atomic transaction across the two storefronts. Do not automatically undo a successful publication because the other storefront failed.

All transitions require expected revision/state checks, authorized actor/service, persisted reason, and audit event. Only validated transitions are allowed; agents cannot set arbitrary state labels.

## 15. Publishing adapters

Define an adapter contract with `capabilities`, `readCatalog`, `validate`, `plan`, `dryRun`, `publishApprovedChangeSet`, and `reconcile`. Actual method names may vary, but separation is mandatory.

Each adapter owns destination schema translation, category/enum mappings, required fields, asset delivery, identity resolution, concurrency preconditions, transaction boundaries, and result verification. Inspect each real storefront schema before implementation; do not assume matching tables or directly reuse one adapter's SQL for the other.

Default behavior is operational draft persistence only. Live storefront writes occur only through guarded adapters after approval. If a storefront requires a staging record, document its visibility and side effects and obtain the appropriate explicit staging approval. Publication may mean creating a hidden product or making it visible; the approved change set must state the exact requested status.

Use a destination transaction for related rows where supported. For multi-step writes without a single transaction, persist checkpoints and reconcile each step. Updates require expected destination version/hash or equivalent conflict detection. Unexpected live changes block execution and require a refreshed diff and approval. Never overwrite storefront-owned stock or pricing incidentally.

## 16. Idempotency, retries, and recovery

- Assume at-least-once delivery and repeated worker execution.
- Use a durable inbox for source changes and an outbox for jobs created with state transitions.
- Intake work key binds connection/source revision and policy; image key binds source checksum and recipe; publication key binds destination and approved immutable change set.
- Enforce unique keys and atomic job claims with leases. Expired leases can be recovered; competing workers must not publish the same operation twice.
- Persist external IDs and operation receipts. On timeout after a possible write, mark `OUTCOME_UNKNOWN` and reconcile before retrying creation.
- Prefer destination-supported idempotency or unique external reference constraints. If unavailable, require a reliable lookup/reconciliation strategy before enabling publication.
- Retry transient failures with bounded backoff/jitter. Validation, authorization, and approval failures need intervention, not endless retries.
- Resume from committed checkpoints. Preserve failed attempts, diagnostics, and dead-letter records.
- Never promise exactly-once external effects without a destination mechanism that enforces them.

## 17. Audit, security, and privacy

Use least-privilege connections and separate read/write identities where practical. Keep publication credentials server-side and unavailable to prompts, browser clients, and untrusted agent tools. Store secrets in environment/secret management, never in repository examples or logs. Use separate development, test, and production configuration; all examples must be fake.

Require dashboard authentication and server-enforced roles. Enforce tenant/storefront isolation in application access and database policies where applicable. Signed asset access or public URLs follow an explicit visibility policy; draft images must not become public accidentally. Validate uploads and protect image processing against resource exhaustion and malicious inputs. Restrict outbound fetches and tool permissions to avoid arbitrary URL access or credential exfiltration.

Audit source events, model outputs and versions, evidence changes, reviewer edits, approvals, rejected writes, adapter requests/results, and reconciliation decisions. Redact secrets and unnecessary personal data. Audit history is append-only for application actors; administrative retention/deletion remains controlled and itself recorded. Define retention for originals, rejected drafts, operational logs, and backups before production. Verify restore procedures and document incident response and credential revocation.

## 18. Repository and plugin scaffold

Illustrative standalone structure; verify current Claude Code/Cursor configuration conventions during implementation before claiming compatibility.

```text
commerce-os/
  PRD.md
  README.md
  AGENTS.md
  CLAUDE.md
  .env.example
  .gitignore
  .claude-plugin/
    plugin.json
  .cursor/
    rules/
      commerce-os.mdc
  agents/
    intake-assets.md
    product-intelligence.md
    catalog-draft.md
    review-publishing.md
  skills/
    drive-intake/SKILL.md
    image-preparation/SKILL.md
    product-classification/SKILL.md
    variant-grouping/SKILL.md
    catalog-retrieval/SKILL.md
    canonical-drafting/SKILL.md
    review-packaging/SKILL.md
    publishing/SKILL.md
    reconciliation/SKILL.md
  commands/
    intake.md
    review.md
    dry-run.md
    publish.md
  apps/
    review-dashboard/
  services/
    workflow/
    workers/
    drive-events/
  packages/
    contracts/
    policy/
    image-pipeline/
    adapters/storefront-a/
    adapters/storefront-b/
  database/
    operational/migrations/
  resources/
    categories/
    image-recipes/
    storefront-mappings/
    evidence-policy.md
  docs/
    architecture.md
    state-machine.md
    security.md
    runbooks/
  tests/
    fixtures/
    contract/
    integration/
    e2e/
```

`AGENTS.md` contains tool-neutral boundaries. `CLAUDE.md` and Cursor rules reference the same canonical policies rather than duplicating business logic. Claude plugin metadata packages supported agents/skills/commands; Cursor exposes equivalent documented entry points through its supported rules/tools. Do not assume the same plugin manifest is executable in both tools.

Production notifications and durable jobs run in services. Claude Code/Cursor can invoke inspection, draft processing, and dry runs through authenticated workflow interfaces. A local agent cannot bypass server-side approval by running the publish command. Keep storefront schema changes outside the operational migration directory and require a separate reviewed migration plan if needed.

## 19. Implementation phases

### Phase 0 — Discovery and reviewable scaffold

Inspect the two catalog schemas read-only, collect representative images, document authoritative metadata sources, finalize category and destination mappings, and verify current integration documentation. Create the standalone repository scaffold and local fake adapters. Deliver architecture, schema proposal, sample review package, and an explicit unresolved-decision log. No live writes.

### Phase 1 — Offline vertical slice

Process fixture submissions through image preparation, canonical draft, evidence validation, destination previews, and review UI using local/test data. Implement state transitions, audit, revisioning, and approval invalidation before publication code is enabled.

### Phase 2 — Event intake and read-only catalog integration

Implement durable Drive intake, renewal/reconciliation, source snapshots, isolated catalog reads, candidate matching, and recoverable workers in approved test infrastructure. Exercise duplicate events and missed-event recovery.

### Phase 3 — Approved sandbox publication

Implement each adapter independently. Add immutable approvals, guarded writes, asset delivery, destination preconditions, receipts, and unknown-outcome reconciliation. Demonstrate A-success/B-failure recovery and kill-switch behavior.

### Phase 4 — Controlled production pilot

After explicit deployment and connection approval, enable a small representative product set and named reviewers. Measure accuracy, reviewer edits, processing latency, and reliability. Expand only after acceptance criteria pass. Bulk publication and increased autonomy require a separate decision.

## 20. Acceptance criteria

| ID | Required evidence |
| --- | --- |
| AC-01 | Repository runs with ZAIDYN absent; no imports, paths, shared credentials, or deployment dependencies reference it. |
| AC-02 | Configuration proves three separate database boundaries; A/B identities and data remain isolated. |
| AC-03 | An eligible Drive event creates one logical source revision; duplicate delivery/restart does not duplicate products or jobs. |
| AC-04 | A multi-image product produces traceable derivatives while originals remain intact; corrupt inputs are blocked. |
| AC-05 | Multiple views, true color variants, ambiguous lighting, and separate products are reviewable without invented combinations. |
| AC-06 | Missing price/material/size/stock remain unknown; similarity cannot populate them as confirmed facts. |
| AC-07 | Dashboard shows evidence, blockers, image previews, candidate matches, and per-destination diffs. |
| AC-08 | Unapproved publication is rejected server-side; changed fields/assets/mappings invalidate relevant approvals. |
| AC-09 | Repeated approved publication and timeout recovery produce no duplicate destination products. |
| AC-10 | A successful A publication and failed B publication remain separately recorded and safely recoverable. |
| AC-11 | Concurrent review/live destination edits produce a conflict rather than lost changes. |
| AC-12 | Audit reconstructs source → draft → human decision → exact change set → destination receipt. |
| AC-13 | Unauthorized cross-storefront access, client secret access, and prompt-injection attempts fail in tests. |
| AC-14 | Claude Code and Cursor documented entry points can inspect and dry-run the same sample workflow using shared contracts. |
| AC-15 | Reconciliation detects remote mismatches; queued, unknown, and verified-success states are displayed distinctly. |

## 21. Test plan

### Unit and contract tests

Validate canonical schemas, option uniqueness, category rules, evidence requirements, money/units, state guards, approval hashes, adapter mappings, and source/recipe idempotency keys. Contract-test adapters against representative schema fixtures including different enum and variant models.

### Integration tests

Use isolated test databases and controlled Drive fixtures. Exercise notification duplicates, expired channels/cursors, incomplete folders, source changes mid-run, revoked access, queue crashes, lease expiry, retries, outbox recovery, and assets uploaded before database failure. Verify no test can reach production credentials.

### End-to-end review and publication

Cover artwork, hat, blanket, one default variant, multiple colors, partial metadata, invalid image, duplicate product candidate, reviewer split/merge, rejected submission, stale approval, concurrent review, destination conflict, partial publication, and timeout after successful remote commit. Verify read-after-write receipts and safe retry behavior.

### Evaluation and security

Use an owner-labeled representative corpus to assess category classification, variant grouping, catalog matching, unsupported-fact rate, and reviewer correction rate. Include misleading filenames, conflicting metadata, embedded instructions, inaccessible assets, unauthorized roles, tenant leaks, secret logging, oversized images, and malicious file content. Any asserted unsupported commercial fact is a release blocker.

### Operational validation

Demonstrate backup restore, audit reconstruction, kill switch, channel renewal, dead-letter recovery, bounded retries, and reconciliation after worker outage. Load-test against an agreed expected workload; define service objectives after that workload is known.

## 22. Unresolved questions and default posture

1. What are the two storefront names, schemas, product APIs, visibility fields, and asset storage requirements? Default: fake adapters and no external writes.
2. Which Drive accounts/folders map to which storefronts, and can one product target both? Default: explicit destination selection at review.
3. What signals a complete upload? Proposed: product folder plus ready manifest.
4. Which source supplies authoritative SKU, price, stock, sizes, dimensions, materials, and rights? Default: required unknowns block publication.
5. Which categories and option vocabularies are in MVP? Start with the confirmed examples after owner validation.
6. What image sizes, crops, formats, background edits, and storage policies does each storefront need? Default: preserve identity and require preview for consequential edits.
7. Is publication create-only initially, or are updates permitted? Proposed MVP: create-first; updates require explicit identity confirmation and diff approval.
8. Who can review versus approve, and is a second person required? Default: explicit roles, no agent self-approval; separation-of-duty policy remains an owner decision.
9. Which runtime, hosting, model provider, operational database service, and queue are preferred? Default: choose only after discovery; architecture must remain independent.
10. What daily volume, latency, cost, retention, and recovery objectives apply? Instrument before committing targets.
11. Which live fields may Commerce OS own after publication? Default: do not overwrite live fields without an approved operation.
12. How are sold-out, deleted, renamed, or moved source products handled? Default: no automatic deletion/unpublication.
13. Are there multiple organizations beyond these two sites? Preserve isolation keys now; defer broader multi-tenant product features.

## 23. Coding-agent implementation instructions

1. Treat this PRD as a specification to implement in reviewed phases, not authorization to provision, deploy, migrate, connect production secrets, or publish products. This handoff requests a document only.
2. Before implementation, inspect applicable repository instructions and the actual project root. Create `commerce-os` as a sibling of `zaidyn-pm-os` only when implementation is authorized. Never modify synced reference files or ZAIDYN to make Commerce OS work.
3. Start with Phase 0. Record confirmed facts, assumptions, and unresolved decisions separately. Do not invent inaccessible schemas, prior architecture decisions, API capabilities, or credentials.
4. Inspect each catalog read-only and verify current official provider/tool documentation before choosing integration methods or plugin configuration. Do not guess production table names.
5. Implement contracts, policy enforcement, immutable revisions, evidence records, and deterministic state transitions before adding AI automation or external write capability.
6. Use mocked adapters and synthetic fixtures by default. Make dry-run behavior explicit and prove that it cannot mutate external systems.
7. Keep agents narrowly scoped. Validate every structured output and treat all external content as untrusted. No prompt may grant publication authority.
8. Implement one complete product-to-review slice before expanding categories. Add adapters separately with contract tests and independently scoped credentials.
9. Enforce approvals in the backend and revalidate at execution. Never expose a bypass flag for production publication or use a broad database service credential in the dashboard.
10. Do not apply storefront migrations or alter live schemas implicitly. Produce a separate concrete migration/change plan if compatibility requires them.
11. Deliver phase-sized changes with setup instructions, sanitized configuration, sample fixtures, validation results, known limitations, and a requirement-to-test checklist. Clearly distinguish implemented, simulated, and deferred behavior.
12. Stop external execution when a required source fact, destination mapping, credential scope, approval, or write outcome is unresolved. Continue independent local preparation and surface the exact blocker.

## 24. Definition of done

Commerce OS MVP is complete when a representative submission can enter through an event, become a supported canonical draft with processed images, receive explicit human review and destination approval, publish safely to either or both isolated test storefronts, and recover from duplicate delivery and partial failure with a complete audit trail. Production readiness additionally requires approved operational policies, verified integrations, named owners, and controlled pilot acceptance. A scaffold or convincing AI-generated preview alone does not meet this definition.
