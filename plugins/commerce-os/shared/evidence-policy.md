# Evidence policy

Version: `evidence-policy@0.1.0`. Record this version on every draft that applies it.

This is the canonical no-invented-facts policy (PRD §8.4 and §11). Every skill that produces or edits
a product, variant or destination field applies it.

## Field evidence record

Every factual field is stored as a record, never as a bare value:

| Key | Meaning |
|---|---|
| `value` | The value, or `null` when unknown. |
| `status` | One of the statuses below. |
| `evidence` | References to the source: asset ID and region, manifest field, catalog record, or human decision. |
| `confidence` | Optional, only where meaningful. Never a substitute for evidence. |
| `method` | How the value was produced: extraction method, model and version, or `human`. |
| `decision` | Reviewer decision, actor and justification, when a human confirmed or corrected it. |

## Statuses

| Status | Use when | Can satisfy a required commercial fact? |
|---|---|---|
| `observed` | Directly visible in a submitted image. | Only for visual attributes (e.g. visible color), never for commercial facts. |
| `supplied` | Given in the submission manifest or by the submitter. | Yes, if the manifest is an authorized source for that field. |
| `verified_catalog` | Matches an authoritative record in the same destination's catalog, for a confirmed identity. | Yes, for that destination only. |
| `inferred` | Reasoned from other evidence, not directly observed or supplied. | No, unless policy explicitly allows that inference type and a human confirms it. |
| `unknown` | No supporting evidence. `value` is `null`. | No. |
| `conflicting` | Two or more sources disagree. | No. Creates a blocking issue. |
| `human_confirmed` | A named reviewer confirmed or corrected the value. | Yes. |

## Rules

1. Unknown values stay `null` with status `unknown`. Never fill a plausible default.
2. **Commercial facts** need `supplied`, `verified_catalog` or `human_confirmed`: price, currency,
   stock, availability, dimensions, material, brand, vendor, SKU, GTIN, tax, shipping,
   safety/certification, and image rights.
3. A **similar** catalog item is never evidence for any field of a new product. Similar items may only
   inform structure, option names, product type and writing style.
4. Copy may rephrase supported facts. It must not add unverified claims such as "handmade", "organic",
   "premium", "one of a kind", or exact sizing.
5. Color seen under uneven lighting is `observed` with low confidence and a review issue, not a fact.
6. Never infer unseen sizes or create option combinations that no evidence supports.
7. Conflicting evidence on a required field creates a **blocking** review issue.
8. Uncertainty goes in structured records and review issues, never only in prose.
9. Approval alone never converts an unsupported field into a fact. Only an explicit reviewer decision
   on that field does.
10. Values for one storefront are never copied to the other.
