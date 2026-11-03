"""Draft one listing end to end: gather its inputs, call Claude, map, check, save a new revision.

Shared by `scripts/draft_listings.py` (batches) and the local dashboard API (one piece, or a redraft with
the owner's note), so both produce exactly the same records.
"""
import datetime
import json
from pathlib import Path
from typing import Optional

from packages.drafting import brand, learning, listing
from packages.drafting.store import Store, draft_facts

REPO = Path(__file__).resolve().parents[2]


def store_tags(storefront: str = "storefront-a", env: str = "production") -> list:
    """In-scope tag names from the storefront's local mapping (gitignored); none if it's absent."""
    p = REPO / "config" / "mappings" / f"{storefront}.local.json"
    if not p.exists():
        return []
    m = json.loads(p.read_text())
    return sorted({t["name"][env] for t in m.get("tags", [])
                   if t.get("status") == "in_scope" and t.get("name", {}).get(env)})


def resolve_art(item: dict) -> Path:
    p = Path(item["art_file"])
    return p if p.is_absolute() else REPO / p


def draft_item(client, item: dict, *, store: Store, ctx: Optional[dict], product_types: dict, tags: list,
               model: str = listing.MODEL, learn: Optional[learning.Learning] = None, call=None) -> dict:
    """Draft `item` (a review-page item with `art_file`) and save it as the next revision."""
    learn = learn or learning.Learning()
    entry = store.listing(item["id"])
    meanings = brand.meanings_in_scope(ctx, item["id"], entry.get("series")) if ctx else []
    others = store.corpus(exclude=item["id"])
    previous = store.draft(item["id"])
    category = previous["draft"]["product"]["attributes"].get("category", {}).get("value") if previous else None
    # edits the owner made to the previous revision are learning material: record them before they're
    # replaced, and before building the prompt, so this very redraft can learn from them
    if previous and entry.get("edits"):
        learn.record(item=item["id"], proposed=store.proposed(previous), final=store.effective(item["id"], previous),
                     revision=previous["draft"]["revision"], versions=previous["draft"]["policy_versions"],
                     event="redrafted", category=category)
    pairs = learning.pairs_text(learn.prompt_pairs(category))
    image, media = listing.encode_image(resolve_art(item))
    request = listing.build_request(image, media, product_types, tags, model, brand_ctx=ctx, meanings=meanings,
                                    facts=draft_facts(entry.get("facts")), note=entry.get("note", ""),
                                    series=entry.get("series", ""), others=others, edit_pairs=pairs)
    result = (call or listing.call_model)(client, request)
    revision = store.next_revision(item["id"])
    draft = listing.to_canonical_draft(result["output"], item_id=item["id"], file_id=f"file-{item['id']}",
                                       product_types=product_types, model=result["model"], store_tags=tags,
                                       brand_ctx=ctx, meanings=meanings, facts=draft_facts(entry.get("facts")),
                                       others=others, revision=revision)
    record = {
        "item": item["id"], "source": item["source"], "art_file": item["art_file"],
        "drafted_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": result["model"], "request_id": result["request_id"], "usage": result["usage"],
        "cost_usd": listing.estimate_cost(result["usage"], model),
        "inputs": {"note": entry.get("note", ""), "facts": draft_facts(entry.get("facts")), "series": entry.get("series", ""),
                   "meanings": [m["id"] for m in meanings], "catalog_size": len(others),
                   "edit_pairs": bool(pairs)},
        "model_output": result["output"], "draft": draft,
        "policy_violations": [str(v) for v in listing.check_draft(draft)],
    }
    store.save_draft(item["id"], record)
    return record


def approve(item_id: str, actor: str, *, store: Store, learn: Optional[learning.Learning] = None) -> dict:
    """Lock the copy and record what the owner changed (the learning loop's input)."""
    learn = learn or learning.Learning()
    res = store.approve(item_id, actor)
    d = res["record"]["draft"]
    category = d["product"]["attributes"].get("category", {}).get("value")
    records = learn.record(item=item_id, proposed=res["proposed"], final=res["final"], revision=d["revision"],
                           versions=d["policy_versions"], event="approved", category=category)
    return {"approval": res["approval"], "edits_recorded": sum(r["changed"] for r in records)}


def distil_lessons(client, storefront: str, actor: dict, *, learn: Optional[learning.Learning] = None,
                   model: str = listing.MODEL, call=None, brand_root=brand.BRAND_DIR) -> dict:
    """Ask Claude for lessons from the edits; add them to the brand context as proposals (new version)."""
    learn = learn or learning.Learning()
    ctx = brand.load(storefront, brand_root)
    if ctx is None:
        raise brand.BrandContextError("no brand context to add lessons to")
    edits = learn.changed()
    if not edits:
        return {"proposed": 0, "version": ctx["version"], "cost_usd": 0.0}
    result = (call or listing.call_model)(client, learning.lesson_request(edits, ctx, model))
    new = learning.add_proposed_lessons(ctx, result["output"]["lessons"], {e["id"] for e in learn.edits()})
    added = len(new["lessons"]) - len(ctx["lessons"])
    if added:
        new = brand.save(new, actor, brand_root)
    return {"proposed": added, "version": new["version"], "cost_usd": listing.estimate_cost(result["usage"], model)}
