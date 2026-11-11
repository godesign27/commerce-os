"""The usual pricing tiers for an original, learned from the store's own products (B-078).

Most stores sell an original alongside the same prints at the same prices. This reads the active products' tiers,
groups them by the original's size, and proposes the most common set for each size. A proposal is never used on
its own: the owner confirms it on Getting started, and only then is it saved in the mapping and added to new
originals. Stdlib only.
"""
import re
from collections import Counter
from typing import Dict, List, Optional

ORIGINAL = "Original"
MIN_PRODUCTS = 2                    # a ladder seen on one product is a one-off, not the store's habit
PLACEHOLDER = "enter description"   # what the store's admin saves when a description is left alone
SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:\"|''|in(?:ches)?\.?)?\s*[x×X]\s*(\d+(?:\.\d+)?)")


def size_key(text) -> Optional[str]:
    """`16 x 20 inches`, `16x20` and `16"x20" Original` are all `16x20`. None when there's no W x H in it."""
    m = SIZE.search(str(text or ""))
    if not m:
        return None
    trim = lambda n: n[:-2] if n.endswith(".0") else n  # noqa: E731
    return f"{trim(m.group(1))}x{trim(m.group(2))}"


def label(key: str) -> str:
    return key.replace("x", " × ") + " in"


def read(pg) -> List[list]:
    """Each active product's tiers. `pg.rows(sql)` runs one read-only query."""
    rows = pg.rows("SELECT pricing_tiers FROM public.products "
                   "WHERE status = 'active' AND jsonb_typeof(pricing_tiers) = 'array' ORDER BY id")
    return [r["pricing_tiers"] for r in rows if isinstance(r.get("pricing_tiers"), list)]


def _text(v) -> str:
    return str(v).strip() if v is not None else ""


def _price(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return int(n) if n == int(n) else round(n, 2)


def _stock(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _tier_key(t: dict) -> tuple:
    return (_text(t.get("type")), size_key(t.get("size")) or _text(t.get("size")), _price(t.get("price")))


def _most_common(values: list):
    values = [v for v in values if v not in (None, "")]
    return Counter(values).most_common(1)[0][0] if values else None


def propose(products: List[list], min_products: int = MIN_PRODUCTS) -> List[dict]:
    """For each size of original, the set of other tiers most of those products have, with prices, descriptions
    and stock as the store most often has them. Sizes with no ladder seen on `min_products` products are left out."""
    groups: Dict[str, list] = {}
    described: Dict[tuple, Counter] = {}               # a description must be the store's habit, not a one-off
    for tiers in products:
        for x in tiers:
            if isinstance(x, dict) and _text(x.get("description")) and _text(x.get("description")).lower() != PLACEHOLDER:
                described.setdefault(_tier_key(x), Counter())[_text(x["description"])] += 1
    for tiers in products:
        tiers = [t for t in tiers if isinstance(t, dict)]
        original = next((t for t in tiers if _text(t.get("type")) == ORIGINAL), None)
        key = size_key(original.get("size")) if original else None
        if not key:
            continue
        extras = [t for t in tiers if t is not original and _text(t.get("type")) and _price(t.get("price")) is not None]
        extras.sort(key=_tier_key)                       # the same tiers in another order are the same ladder
        signature = tuple(_tier_key(t) for t in extras)
        groups.setdefault(key, []).append((signature, original, extras))
    out = []
    for key, rows in sorted(groups.items(), key=lambda kv: [float(n) for n in kv[0].split("x")]):
        signature, based_on = Counter(sig for sig, _, _ in rows).most_common(1)[0]
        if based_on < min_products or not signature:
            continue
        matching = [(o, e) for sig, o, e in rows if sig == signature]
        ladder = []
        for i, (kind, size, price) in enumerate(signature):
            seen = [e[i] for _, e in matching]
            habit = (described.get((kind, size, price)) or Counter()).most_common(1)
            ladder.append({"type": kind, "size": _most_common([_text(t.get("size")) for t in seen]) or size, "price": price,
                           "description": habit[0][0] if habit and habit[0][1] >= MIN_PRODUCTS else "",
                           "stock": _most_common([_stock(t.get("stock")) for t in seen])})
        ladder.sort(key=lambda x: (x["type"] != "Print", x["type"], x["price"]))   # prints, then the rest, cheapest first
        out.append({"size": key, "label": label(key), "tiers": ladder, "based_on": based_on, "of": len(rows),
                    "original_stock": _most_common([_stock(o.get("stock")) for o, _ in matching])})
    return out


def describe(tier: dict) -> str:
    """A tier's description, which the store requires on every tier: its own when it has one, otherwise its size and
    type the way the store's admin suggests them (`30 × 30 in original`). A blank or the admin's placeholder counts
    as none, or the store refuses to save the product the next time it's edited."""
    own = _text(tier.get("description"))
    if own and own.lower() != PLACEHOLDER:
        return own
    kind = _text(tier.get("type")) or "Piece"
    key = size_key(tier.get("size"))
    size = label(key) if key else _text(tier.get("size"))
    return f"{size} {kind.lower()}" if size else kind


def ladder_for(mapping: Optional[dict], dimensions) -> Optional[dict]:
    """The confirmed ladder for an original of this size, or None."""
    key = size_key(dimensions)
    return ((mapping or {}).get("tier_ladders") or {}).get(key) if key else None
