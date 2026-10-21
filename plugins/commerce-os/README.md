# Commerce OS plugin

Governed product preparation for two independent storefronts. A router and four specialist agents run
twelve skills that turn a product submission into an evidence-backed draft for human review. No agent
writes to a storefront; publication is server-side and human-approved.

> **Phase 0a.** Skills are specifications. Nothing is connected: no Drive, no storefront, no workflow
> service. Skills that need those stop and say so.

## Agents

| Agent | Skills |
|---|---|
| `commerce-lead` (router) | Dispatches to the specialists below |
| `intake-assets` | drive-intake, asset-validation, image-preparation |
| `product-intelligence` | product-classification, variant-grouping, catalog-retrieval |
| `catalog-draft` | canonical-drafting, destination-mapping |
| `review-publishing` | review-packaging, approval-verification, publishing, reconciliation |

## Commands

| Command | Runs |
|---|---|
| `/intake <folder>` | drive-intake, then asset-validation |
| `/review <submission>` | review-packaging |
| `/dry-run <submission> <storefront>` | publishing, dry-run mode |
| `/publish <submission> <storefront>` | publishing, request mode (needs a valid human approval) |

## Shared policies

- [COMMERCE-CONTEXT.md](shared/COMMERCE-CONTEXT.md): operating constraints.
- [evidence-policy.md](shared/evidence-policy.md): field evidence and no-invented-facts rules.
- [WORKFLOW.md](shared/WORKFLOW.md): states, gates, transitions.
- [CONNECTORS.md](shared/CONNECTORS.md): tool categories and what is connected (nothing yet).

Local output goes to `.commerce-os/out/<submission-id>/` in your working directory.

How it's built: [docs/DEV-README.md](docs/DEV-README.md).
