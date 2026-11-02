# Listing copy: using and maintaining it

How titles, descriptions and tags are written, what each part is for, and where to change what.
Backlog: B-056 (copy and brand context), B-057 (local dashboard), B-058 (learning loop), B-059 (saving your own copy), B-060 (collector descriptions as small stories), B-061 (the animal's name in the title), B-062 (the Photos page), B-063 (room views).

## The three parts, and who changes each

| Part | Where | Changes when | Who |
|---|---|---|---|
| The craft: process, structure, hedging, what never to claim | `plugins/commerce-os/skills/listing-copy/references/writing-standards.md`, `rubric.md` | The writing approach itself improves, for every storefront | Maintainer (plugin version bump) |
| The voice: philosophy, kinds of work, tone, confirmed meanings, phrases to watch, examples, lessons | `config/brand/<storefront>.local.json` (gitignored; history in `config/brand/history/`) | The owner explains something new, approves a lesson or example | The owner, through the dashboard or `/brand-context` |
| The checks: claims and repetition | `packages/drafting/checks.py` | A new kind of repetition or claim shows up | Maintainer, with a test and a mutant |

The service sends the writing standards to the model word for word, so the skill and the service
can't drift apart. Keep the standards storefront-neutral: a test fails if they name the artist.

## Day to day

0. **Photos:** the **Photos** page shows every photo from the source folder, where it is (to review, not
   applied, ready to draft, drafted, copy approved, rejected) and when each step happened. Accept,
   reject or rotate a photo there. Click a photo to open it: drag the four corners onto the artwork's
   edges (or click to bring the nearest corner there; Tab to a corner and nudge it with the arrow keys),
   then **Save corners** and **Apply changes** to re-crop and re-frame. The cropped and framed results
   sit beside it. Rejected photos are never drafted.

   **Rooms:** the **Rooms** page holds room photos for showing each framed piece on a wall. Press **Add a room** to
   upload photos (or put them in `.commerce-os/rooms/inbox/` and press **Look for new rooms**). Each new room is named from its photo and gets a
   suggested hanging area and width. Open it, check the box and the width (the checklist at the top says
   what's left), record its licence if you didn't when adding it, and press **Save room**: a room is only used
   once all three are saved. **Preview** it with a piece. Each piece is shown in one room: on a photo's
   page, **In a room** hangs it on the wall of the ready room that best suits its shape and size, and
   **Change room** opens a drawer to choose another (or go back to **Pick for me**). **Hang every piece in
   its room** on the Rooms page does them all. A piece hangs at its real size once its size
   is given; otherwise the size is a guess and the page says so. **About this piece** (series, edition,
   medium, size) is on both the photo page and the listing page, saved in one place. The size is entered as
   width × height with inches or cm, and saving it hangs the piece again at that size. Room
   photos stay on this computer (gitignored).

1. **First run:** the dashboard asks whether this is an artist site or a product site, then asks
   about the artist (or brand), the kinds of work, and the voice. `/brand-context <id> interview`
   does the same in Claude Code, and `/brand-context <id> import <file>` splits an existing guide.
2. **Draft:** use "Draft next 5" on the Listings page, or
   `.venv/bin/python scripts/draft_listings.py --limit 5`. Pieces are drafted one at a time, so each
   one sees the titles the previous ones took.
3. **Review a listing:** pick one of the three titles, or **Other** to write your own, then edit the
   descriptions and tags. Nothing saves until you press that section's **Save changes** (or **Save
   title**); **Discard** puts it back. A section you've changed shows "Not saved"; one you've saved
   shows "Your edit" and a **Back to the draft** link. The page warns you before you leave or redraft
   with unsaved sections. After a save, the checks for that section appear under it. Under the image, fill in **About this piece** (series, edition, medium, size) if you know them; that clears the blocking items and
   allows those words in the copy. The **Checks** and **Visible, confirmed and proposed** tabs sit under that. On the right, "What this piece means" shows the questions for the artist next to where you answer them:
   - **Note for the writer:** applies to this piece only and is used on the next redraft.
   - **Record a confirmed meaning:** a lasting entry. "This piece" applies only to this piece; "This
     series" applies to every piece with the same series name; "Whole catalog" applies to everything.
     Catalog-wide meanings shape the reading but are not repeated in each listing.
4. **Redraft with my note:** makes a new revision. Your edits to the old one are recorded for learning
   first.
5. **Approve copy:** locks the copy and records what you changed. A redraft is refused while it's
   approved; use "Unlock to edit" to change it again. Approval publishes nothing.
6. **Learning:** "Learn from my edits" proposes general lessons. Approve, reword or reject each one.
   Only approved lessons reach the writer. The table shows how much of each draft survives approval;
   if the "latest 10" column climbs, the drafts are getting closer to your voice.

## Changing copy from Claude Code

`/listing-edit` saves your own words without opening the dashboard:

- `/listing-edit wolf title "The Wolf's Gaze"`
- `/listing-edit wolf use this collector description instead: …`
- `/listing-edit wolf pick the second title`
- `/listing-edit wolf go back to the drafted short description`

It finds the listing by ID, title or file name and asks if more than one matches. It saves your text
exactly as given, prints the checks, and links the listing. Refresh the dashboard to see it. It can't
change approved copy (unlock it on the dashboard first), and it never redrafts or publishes. The engine
is `scripts/listing_edit.py` (`find`, `show`, `set`, `choose`, `revert`), which you can also run directly.

Both the dashboard's Save buttons and `/listing-edit` go through `packages/drafting/editing.py`, so they
follow the same rules. A check never stops your words being saved: an unsupported claim or a title
already in use is saved and flagged, and needs fixing or a supplied fact before you approve.

## How a collector description should read (B-060)

A small human story grounded in this piece, not an inventory of what's in the picture and not an art
advertisement: it opens on a moment or encounter, rests on two or three visible details, hedges once or
twice, and ends on a thought or image rather than a question. The full direction and a worked example
are in `writing-standards.md`; the model scores itself on it (`human_story`), and the checks warn about
a closing question, stock phrases, stacked hedges, a catalog-wide meaning restated, or wording borrowed
from the example. The short description stays plain and concise.

## Titles name the animal

When a piece shows an animal or a character, every title option contains its everyday name ("Lion",
"Rooster"), so it turns up when a shopper searches for it. Abstracts are exempt. A title you save
without the name is kept, with a warning.

## What the copy may and may not say

- Visible details: always fine.
- Confirmed meanings: written with confidence, but only within their scope.
- Proposed readings: hedged, and listed for the artist to confirm.
- Medium, size, edition, "original", "handmade", a metallic or leafed surface and similar: only when supplied. Otherwise they become a
  blocking issue, whatever the model wrote.

## Cost

About 10 cents a piece with Claude Opus 5.5 at high effort (one image, the brand context and a long
draft; the brand context is cached across a batch). The script and the dashboard show the cost of
each run. Lessons cost a few cents per run.

## Maintaining

- Change the writing approach: edit the standards or rubric, bump `PROMPT_VERSION` in
  `packages/drafting/listing.py` if the output changes, bump the plugin version, and run the tests.
- Add a check: `checks.check_copy`, plus a test in `tests/test_listing_copy.py` and a mutant.
- Change the brand-context shape: the contract
  (`packages/contracts/schemas/brand-context.schema.json`), its fixture, `brand.render`, and the
  dashboard's `BrandContext` type in `apps/review-dashboard/src/api.ts`.
- Every draft records the brand-context version and prompt version it used, and every edit record
  carries both. That shows whether a change helped.
