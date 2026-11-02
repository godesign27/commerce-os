"""Saving the owner's own copy, one field at a time (B-059).

The dashboard's per-section Save buttons and the `/listing-edit` command both come through here, so they
apply the same rules: only the named fields change, approved copy stays locked, and the copy is checked
against the catalog before it is saved. A check never stops the owner's words being saved; it is
reported back so they can decide.
"""
from typing import Dict, List, Optional

from packages.drafting import checks
from packages.drafting.store import COPY_FIELDS, LIST_FIELDS, Store

FIELDS = COPY_FIELDS + LIST_FIELDS
ALIASES = {
    "title": "title", "name": "title",
    "short": "short_description", "short description": "short_description", "short_description": "short_description",
    "summary": "short_description",
    "collector": "collector_description", "collector description": "collector_description",
    "collector_description": "collector_description", "long": "collector_description",
    "long description": "collector_description", "description": "collector_description",
    "tags": "store_tags", "store tags": "store_tags", "store_tags": "store_tags",
    "keywords": "search_keywords", "search keywords": "search_keywords", "search_keywords": "search_keywords",
}
LABELS = {"title": "Title", "short_description": "Short description", "collector_description": "Collector description",
          "store_tags": "Store tags", "search_keywords": "Search keywords"}
TITLE_CHECKS = {"duplicate_title", "title_word_reused", "subject_missing_from_title"}
VOICE_CHECKS = {"closing_question", "stock_phrase", "hedge_stack", "catalog_meaning_restated", "copies_example"}
PROSE_CHECKS = {"watch_phrase", "shared_phrasing", "same_opening", "length", "rejected_style_word"} | VOICE_CHECKS


def field_name(name: str) -> str:
    key = " ".join(name.replace("-", " ").lower().split())
    if key in ALIASES:
        return ALIASES[key]
    raise ValueError(f"unknown field {name!r}: use one of title, short, collector, tags, keywords")


def find_items(items: List[dict], store: Store, query: str) -> List[str]:
    """Item IDs matching `query`: an exact ID wins; otherwise a case-insensitive match on the ID, the
    source file name, or the current title. Only drafted items can be edited, so only they match."""
    drafted = [it for it in items if store.draft(it["id"])]
    q = query.strip().lower()
    exact = [it["id"] for it in drafted if it["id"].lower() == q]
    if exact:
        return exact
    out = []
    for it in drafted:
        copy = store.effective(it["id"]) or {}
        hay = " ".join([it["id"], it.get("source", ""), copy.get("title", "")]).lower()
        if q and q in hay:
            out.append(it["id"])
    return out


def review(store: Store, item: str, changed: List[str], ctx: Optional[dict]) -> List[dict]:
    """The checks that concern the fields just changed: unsupported claims in new prose, and the
    repetition checks for the title or the descriptions."""
    copy = store.effective(item) or {}
    facts = store.listing(item).get("facts", {})
    out = []
    for k in changed:
        if k in ("short_description", "collector_description"):
            for v in checks.claim_violations(copy.get(k, ""), facts):
                out.append({"severity": "blocking", "field": k, "check": "unsupported_claim",
                            "message": f"{LABELS[k]} makes a claim nobody has supplied ({v}). Add it under "
                                       "facts, or reword it."})
    wanted = (TITLE_CHECKS if "title" in changed else set()) | \
             (PROSE_CHECKS if {"short_description", "collector_description"} & set(changed) else set())
    if wanted:
        rec = store.draft(item) or {}
        name = (rec.get("draft", {}).get("product", {}).get("attributes", {}).get("subject_name") or {}).get("value") or ""
        for f in checks.check_copy(dict(copy, item=item), store.corpus(exclude=item), ctx, subject_name=name):
            if f["check"] in wanted:
                field = "title" if f["check"] in TITLE_CHECKS else (
                    "short_description" if f["target"].endswith("short_description") else "collector_description")
                out.append({"severity": f["severity"], "field": field, "check": f["check"], "message": f["message"]})
    return out


def save(store: Store, item: str, fields: Dict[str, object], ctx: Optional[dict]) -> dict:
    """Save the named fields (None reverts one to the draft) and report the checks on them."""
    clean = {field_name(k): v for k, v in fields.items()}
    if not clean:
        raise ValueError("nothing to save")
    store.set_fields(item, clean)
    copy = store.effective(item)
    changed = [k for k, v in clean.items() if v is not None]
    return {"item": item, "copy": copy, "saved": sorted(clean), "checks": review(store, item, changed, ctx)}
