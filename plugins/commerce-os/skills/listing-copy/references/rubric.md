# Listing copy rubric

Two halves. The model scores itself on the first; the drafting service runs the second in plain code,
and the code's verdict wins when they disagree.

## Self-review (the model, 0 to 2 each; 12 of 14 or better to recommend as-is)

| Criterion | 2 means |
|---|---|
| `brand_alignment` | Expresses the brand's idea (for an artist: the moment or quality), or the artist's confirmed meaning when there is one. |
| `visual_specificity` | Names concrete features a buyer can find in the image. |
| `interpretive_restraint` | No unsupported claim about meaning, intent, materials or biography; proposed readings are hedged and listed. |
| `distinctiveness` | Could not be pasted onto five other pieces; title and opening differ from the catalog memory. |
| `collector_appeal` | Evocative, readable, emotionally accessible, not pretentious. |
| `human_story` | Does this read like a small human story grounded in this particular piece, or like a visual inventory or generic art advertisement? 2 means a story only this piece could carry, opening on an encounter and resting on two or three visible details. |
| `catalog_readiness` | Title memorable; lengths inside the targets; polished. |

## Automatic checks (the drafting service)

Each finding becomes a review issue on the draft.

| Check | Severity | Rule |
|---|---|---|
| Unsupported claim | blocking | Medium, size, edition, handmade, original, a metallic or special surface (leaf, foil, shimmering, glinting) and similar, unless supplied as a fact. |
| Duplicate title | blocking | The recommended title equals one already taken (case-insensitive). |
| Watch phrase over its limit | warning | Using the phrase here would put it in more listings than `max_share` of the catalog allows (a limit above 0% always allows one). |
| Subject missing from title | warning | The piece shows an animal or character (`subject_name`) and the title doesn't name it. |
| Title word reused | warning | A distinctive title word already appears in two or more other titles (the subject's name doesn't count). |
| Shared phrasing | warning | Five or more consecutive words shared with another description in the catalog. |
| Same opening | warning | The collector description starts with the same three words as another. |
| Length | warning | A description outside the brand context's word or character limits. |
| Closing question | warning | The collector description ends on a question. |
| Stock phrase | warning | Art-marketing phrasing: timeless beauty, captivating, elevate your space, a testament to and similar. |
| Stacked hedges | warning | More than three hedges (perhaps, as if, seems, could be…) in the collector description. |
| Catalog meaning restated | warning | A sentence carries three or more key words of a catalog-wide meaning, at least one of them from what the meaning is about (its subject). |
| Copies the example | warning | Five or more consecutive words borrowed from the example in the writing standards. |
| Low self-review | warning | Self-review total more than 2 below the maximum (under 12 of 14). |
| Proposed reading | note | Each proposed interpretation, so the artist can confirm or correct it. |
