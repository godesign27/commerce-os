"""Updating a product Commerce OS already published (B-085). Pure: no store access, no network.

The owner chose that edits made in the store's own admin always win. So an update sends a field only when both:

  - it changed in Commerce OS since the last publish (the listing now differs from what was published), and
  - the store still has what Commerce OS published there (nobody edited it in the store's admin since).

A field changed in Commerce OS that was also edited in the store is kept as the store has it, and listed. Fields
Commerce OS never manages, the status, the web address and the product id are never sent: a product the owner
made live stays live, and its links keep working. Each field sent carries the value the store is expected to hold
(`precondition.expected_fields`), and the write checks them again inside its transaction, so a store edit made
after the owner approved stops the update instead of being overwritten.
"""
import decimal
import json
from typing import Callable, Dict, List, Optional

from packages.adapters.artstore_map import asset_manifest_hash
from packages.adapters.contract import change_set_hash
from packages.adapters.fake import seal

UPDATE_STATUS = "unchanged"          # an update never sends a status: whatever the store has stays
UPDATABLE = ("name", "short_description", "description", "medium", "dimensions", "price", "pricing_tiers",
             "is_original", "category_id", "tags", "images")
NOT_FOR_UPDATES = ("catalog.match", "product.slug")      # it's in the store: that's the product being updated
# Fields that only make sense together: the Original tier carries the price, so a price edited in the store keeps
# the tiers as the store has them too, and the other way round.
TOGETHER = (("price", "pricing_tiers"),)
NUMBER = __import__("re").compile(r"-?\d+(\.\d+)?")


def _norm(v):
    """One form for a value whether it came from a change set, the store's driver or JSON: numbers compare as
    numbers, JSON text as what it holds, and key order never matters."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float, decimal.Decimal)):
        return str(decimal.Decimal(str(v)).normalize())
    if isinstance(v, str):
        s = v.strip()
        if NUMBER.fullmatch(s):                  # the store's driver gives some numbers back as text ("499.00")
            return str(decimal.Decimal(s).normalize())
        if s[:1] in "[{":
            try:
                return _norm(json.loads(s))
            except ValueError:
                pass
        return v
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in sorted(v.items())}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    return str(v)


def same(a, b) -> bool:
    return _norm(a) == _norm(b)


def published_fields(change_sets: List[dict]) -> Dict[str, dict]:
    """What Commerce OS has put in the store, field by field: each published change set in order, later ones
    on top (a create sends everything; an update only what it changed)."""
    out: Dict[str, dict] = {}
    for cs in change_sets:
        op = cs["operations"][0]
        if op["op"] == "create":
            out = {}
        out.update(op.get("fields") or {})
    return out


def changed_here(published: Dict[str, dict], current: Dict[str, dict]) -> List[str]:
    """The fields the listing has changed since it was published, in UPDATABLE order."""
    return [c for c in UPDATABLE if c in current and not same(current[c]["value"], (published.get(c) or {}).get("value"))]


def plan(published: Dict[str, dict], current: Dict[str, dict], store_row: Optional[dict],
         to_store: Callable[[str, object], object]) -> dict:
    """What an update would send and keep. `to_store(column, value)` gives a change-set value in the store's own
    terms. Returns {"send": {col: field}, "expected": {col: store value}, "kept": [{column, store, ours}]}."""
    send, expected, kept = {}, {}, []
    changed = changed_here(published, current)
    was = {c: to_store(c, (published.get(c) or {}).get("value")) for c in UPDATABLE}
    edited = {c for c in UPDATABLE if not same((store_row or {}).get(c), was[c])}
    for group in TOGETHER:                        # one of a pair edited in the store keeps the pair
        if edited & set(group):
            edited |= set(group)
    for col in changed:
        if col in edited:
            kept.append({"column": col, "store": (store_row or {}).get(col), "ours": to_store(col, current[col]["value"])})
        else:
            send[col], expected[col] = current[col], was[col]
    return {"send": send, "expected": expected, "kept": kept}


def build(create_cs: dict, product_id: str, update: dict, problem: Optional[str] = None) -> dict:
    """The update change set for a published product, from the change set the listing gives now as a create.
    Bindings (revision, mapping, schema) stay those of the listing now; images are only delivered when sent."""
    op = create_cs["operations"][0]
    images = "images" in update["send"]
    blockers = [b for b in create_cs["blockers"] if b["target"] not in NOT_FOR_UPDATES
                and (images or b["target"] != "assets.delivery") and not b["target"].startswith("product.images")]
    if problem:
        blockers.append({"id": f"RI-{len(blockers) + 1}", "severity": "blocking", "gate": 3,
                         "destination": create_cs["destination"], "target": "store.read", "question": problem,
                         "resolver": "reviewer"})
    elif not update["send"]:
        blockers.append({"id": f"RI-{len(blockers) + 1}", "severity": "blocking", "gate": 3,
                         "destination": create_cs["destination"], "target": "update.nothing_to_send",
                         "question": "Everything you changed was also edited in the store, and the store's edits are "
                                     "kept, so there's nothing to send.", "resolver": "reviewer"})
    body = dict(create_cs,
                change_set_id="pending", change_set_hash=None, requested_status=UPDATE_STATUS,
                operations=[{"seq": 1, "op": "update", "entity": op["entity"], "key": product_id,
                             "precondition": {"expected_fields": update["expected"]}, "fields": update["send"]}],
                assets=create_cs["assets"] if images else [],
                asset_manifest_hash=create_cs["asset_manifest_hash"] if images else asset_manifest_hash([]),
                kept=update["kept"], blockers=blockers)
    body["change_set_id"] = f"cs-upd-{create_cs['submission_id'][4:90]}-{change_set_hash(dict(body, change_set_id=''))[:12]}"
    return seal(body)


def is_update(change_set: Optional[dict]) -> bool:
    return bool(change_set) and change_set["operations"][0]["op"] == "update"
