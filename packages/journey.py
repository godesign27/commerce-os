"""One status for each piece, in one place, so every page says the same thing (B-074).

A status describes a piece and decides nothing: the approval and publishing rules live elsewhere and don't read
it. Pure: no files, no network, and it writes nothing.
"""
from typing import Dict, List, Optional

# In the order a piece moves through them. `tone`: what the person has to do about it.
STATUSES = [
    {"id": "review-photo", "label": "Review photo", "tone": "todo"},
    {"id": "ready-to-draft", "label": "Ready to draft", "tone": "wait"},
    {"id": "review-copy", "label": "Review copy", "tone": "todo"},
    {"id": "add-details", "label": "Add details", "tone": "todo"},
    {"id": "approve-for-store", "label": "Approve for store", "tone": "todo"},
    {"id": "ready-to-publish", "label": "Ready to publish", "tone": "todo"},
    {"id": "publishing", "label": "Publishing", "tone": "wait"},
    {"id": "published", "label": "Published", "tone": "done"},
    {"id": "changed", "label": "Changed since published", "tone": "todo"},     # B-085: an update is waiting
    {"id": "ready-to-update", "label": "Update ready", "tone": "todo"},
    {"id": "needs-look", "label": "Needs a look", "tone": "bad"},
    {"id": "rejected", "label": "Rejected", "tone": "off"},
]
LABELS = {s["id"]: s for s in STATUSES}
# The steps a piece passes through, for the pipeline and the Listing page's tracker.
PIPELINE = ["review-photo", "ready-to-draft", "review-copy", "add-details", "approve-for-store", "ready-to-publish",
            "published"]

AFTER_APPROVAL = "assets.delivery"       # copied from packages/adapters/artstore_map.py (AFTER_APPROVAL)
COPY_TARGETS = ("copy.draft", "copy.approval")
SHORT = {"product.price": "price", "product.sold_as": "sold as"}


def open_blockers(blockers: List[dict]) -> List[dict]:
    """What the person still has to resolve. The image upload happens after approval, and approving the copy is
    its own status."""
    return [b for b in blockers if b.get("severity") == "blocking" and b.get("target") != AFTER_APPROVAL
            and b.get("target") not in COPY_TARGETS]


def _words(items: List[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def summary(blockers: List[dict]) -> str:
    """One line for a card: the real blocker, in plain words."""
    if not blockers:
        return ""
    targets = [b.get("target") for b in blockers]
    if all(t in SHORT for t in targets):
        return f"Needs {_words([SHORT[t] for t in SHORT if t in targets])}"
    if len(blockers) == 1:
        return blockers[0]["question"]
    return f"{len(blockers)} things to resolve"


def status(*, stage: str, drafted: bool, copy_approved: bool, publish_state: Optional[str], store_state: Optional[str],
           blockers: Optional[List[dict]] = None, changes: Optional[List[str]] = None, published: bool = False,
           update: bool = False) -> dict:
    """`stage` is the photo's (image_pipeline/stages.py), `store_state` the listing's against the store (blocked,
    ready, approved, out_of_date, or None with no store connected). What's already happened comes first. A piece
    already in the store (`published`) stays Published until its listing changes (`update`); then the change waits
    for an approved update (B-085)."""
    blocking = open_blockers(blockers or [])

    def make(sid: str, next_step: str, detail: str = "", failing: Optional[List[dict]] = None) -> dict:
        failing = failing or []
        return dict(LABELS[sid], next=next_step, detail=detail or summary(failing),
                    blockers=[{"target": b.get("target"), "question": b.get("question")} for b in failing])

    if stage == "rejected":
        return make("rejected", "Undo the rejection on its photo page to use this piece.")
    if publish_state in ("QUEUED", "WRITING"):
        return make("publishing", "The worker has it. This updates by itself.")
    if publish_state == "OUTCOME_UNKNOWN":
        return make("needs-look", "Check the store before publishing again.", "The publish result wasn't seen")
    if published or publish_state == "SUCCEEDED":
        if not update:
            return make("published", "Nothing to do: it's in the store.")
        if store_state == "approved":
            if publish_state == "FAILED":
                return make("needs-look", "See what went wrong, then send the update again.", "The last update failed")
            return make("ready-to-update", "Send the update from the Publish page.")
        changed = f"Changed: {', '.join(changes)}." if changes else "Changed since it was published."
        return make("changed", f"{changed} Check what would change in the store, then approve the update.",
                    failing=open_blockers(blockers or []))
    if stage == "not-applied":
        return make("review-photo", "Apply your saved changes on the Photos page.", "Saved changes not applied")
    if stage == "to-review":
        return make("review-photo", "Accept the photo, or correct its corners.")
    if not drafted:
        return make("ready-to-draft", "Draft its copy on the Listings page.")
    if not copy_approved:
        return make("review-copy", "Read the draft, change what you like, then approve the copy.", failing=blocking)
    if store_state == "out_of_date":
        changed = f"Changed since you approved it: {', '.join(changes)}." if changes else "Changed since you approved it."
        return make("needs-look", f"{changed} Approve this version.", "Approval out of date")
    if store_state == "approved":
        if publish_state == "FAILED":
            return make("needs-look", "See what went wrong, then publish again.", "The last publish failed")
        return make("ready-to-publish", "Send it from the Publish page.")
    if store_state == "ready":
        return make("approve-for-store", "Check what the store would receive, then approve it.")
    if store_state == "blocked":
        return make("add-details", "Add what's missing so this can go to the store.", failing=blocking)
    return make("approve-for-store", "Finish Getting started to connect the store.", "The store isn't connected yet")


def next_step(pieces: List[dict], *, setup_done: bool, can_draft: bool) -> Optional[dict]:
    """The one thing to do next on the start page. `pieces` are {"id", "status"}. Problems first, then the piece
    furthest along, so work already started gets finished first. None means nothing is waiting."""
    by: Dict[str, List[dict]] = {}
    for p in pieces:
        by.setdefault(p["status"]["id"], []).append(p)
    count = lambda sid: len(by.get(sid, []))  # noqa: E731
    plural = lambda n, one, many: one if n == 1 else many  # noqa: E731
    if not setup_done:
        return {"headline": "Finish setting up", "detail": "A few steps are left before you can draft and publish.",
                "label": "Getting started", "href": "#/start"}
    if count("needs-look"):
        n = count("needs-look")
        first = by["needs-look"][0]
        return {"headline": f"{n} {plural(n, 'piece needs', 'pieces need')} a look",
                "detail": first["status"]["next"], "label": "Open it", "href": f"#/listings/{first['id']}"}
    if count("ready-to-publish"):
        n = count("ready-to-publish")
        return {"headline": f"{n} {plural(n, 'piece is', 'pieces are')} ready to publish",
                "detail": "They're approved and waiting on the Publish page.", "label": "Go to Publish", "href": "#/publish"}
    if count("approve-for-store"):
        n = count("approve-for-store")
        return {"headline": f"{n} {plural(n, 'piece is', 'pieces are')} ready for your approval",
                "detail": "Check what the store would receive, then approve it.", "label": "Review them",
                "href": f"#/listings/{by['approve-for-store'][0]['id']}"}
    if count("add-details"):
        n = count("add-details")
        lines = {p["status"]["detail"] for p in by["add-details"]}
        need = next(iter(lines))[len("Needs "):] if len(lines) == 1 and next(iter(lines)).startswith("Needs ") else None
        need = need.replace("price", "a price") if need else None
        return {"headline": f"{n} {plural(n, 'piece needs', 'pieces need')} {need or 'more details'}",
                "detail": "Their copy is approved. Add the details, then you can approve them for the store.",
                "label": "Add details", "href": f"#/listings/{by['add-details'][0]['id']}"}
    if count("review-copy"):
        n = count("review-copy")
        return {"headline": f"{n} {plural(n, 'draft is', 'drafts are')} ready to read",
                "detail": "Change what you like, then approve the copy.", "label": "Review copy",
                "href": f"#/listings/{by['review-copy'][0]['id']}"}
    if count("review-photo"):
        n = count("review-photo")
        return {"headline": f"{n} {plural(n, 'photo needs', 'photos need')} a look",
                "detail": "Accept each one, or correct its corners.", "label": "Review photos", "href": "#/photos"}
    if count("ready-to-draft"):
        n = count("ready-to-draft")
        return {"headline": f"{n} {plural(n, 'piece is', 'pieces are')} ready to draft",
                "detail": "Claude writes the first draft of each listing." if can_draft
                else "Add a Claude API key to start drafting.",
                "label": "Go to Listings" if can_draft else "Add a key", "href": "#/listings" if can_draft else "#/start"}
    return None
