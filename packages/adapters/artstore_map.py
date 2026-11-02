"""A listing as the change set an art-store storefront would receive (catalog profile replit-artstore-v1, B-064).

This is the schema translation for one catalog profile, so it lives with the adapters (PRD §15): approved
copy, the owner's supplied facts and the listing images become one `create` operation on `products`. It
never decides anything the owner hasn't: a missing price, medium, size or "sold as" becomes a named
blocker, never a value, and the status is always set explicitly (Draft: hidden on create).

Phase 1 runs it against the fake test storefront only. Its categories and tags come from the owner's
mapping, with test ids (`test_seed`), so a preview matches the owner's real choices without reading or
touching the real site. Image upload isn't authorized yet (B-025), so every image is listed as not
delivered; that is the one blocker an approval may be given over, because it can't change what's approved.

Stdlib only; Python 3.9+.
"""
import decimal
import hashlib
import json
import re
from pathlib import Path
from typing import List, Optional

from packages.adapters.contract import canonical_json, change_set_hash, sha256_hex
from packages.adapters.fake import FakeStorefront, seal

REPO = Path(__file__).resolve().parents[2]
ENVIRONMENT = "test"
STATUS = "draft"                     # new products go in hidden; the owner sets them live on the site
ORIGINAL = "Original"                # the tier type that makes a piece an original (is_original, category)
PREPARED_BY = {"kind": "service", "id": "commerce-os", "role": "system"}
# Blockers an approval may be given over: delivery happens after approval, and the delivered files are the
# ones whose hashes the approval binds (asset_manifest_hash).
AFTER_APPROVAL = ("assets.delivery",)
NOT_TOUCHED = ["sku", "stock", "year", "frame", "packaging", "rarity", "authenticity", "is_featured", "is_sold",
               "show_in_gallery", "pricing_tiers[].stock"]
LABELS = {"name": "Title", "slug": "Web address", "short_description": "Short description",
          "description": "Description", "medium": "Medium", "dimensions": "Size", "price": "Price",
          "pricing_tiers": "Sold as", "is_original": "Original", "category_id": "Category", "tags": "Tags",
          "images": "Images", "status": "Status", "id": "Product id"}


# ---------------------------------------------------------------- the mapping and the test catalog

def load_mapping(path) -> Optional[dict]:
    p = Path(path)
    p = p if p.is_absolute() else REPO / p
    return json.loads(p.read_text()) if p.exists() else None


def _name(entry: dict) -> str:
    names = entry.get("name") or {}
    return names.get("production") or next(iter(names.values()), entry["key"])


def test_id(kind: str, key: str) -> str:
    return f"test-{kind}-{key}"


def test_seed(mapping: dict) -> dict:
    """The owner's in-scope categories and tags, with test ids: the fake store's catalog."""
    pick = lambda xs: [x for x in xs if x.get("status") == "in_scope"]  # noqa: E731
    return {"categories": [{"id": test_id("category", c["key"]), "name": _name(c), "slug": c.get("slug") or c["key"]}
                           for c in pick(mapping.get("categories", []))],
            "tags": [{"id": test_id("tag", t["key"]), "name": _name(t), "slug": t.get("slug") or t["key"]}
                     for t in pick(mapping.get("tags", []))],
            "products": []}


def test_store(storefront: str, mapping: dict) -> FakeStorefront:
    """The fake test storefront, seeded with the owner's catalog (no products). Writes stay disabled."""
    store = FakeStorefront.from_repo(storefront, ENVIRONMENT, seed=False)
    fresh = FakeStorefront(storefront, ENVIRONMENT, store.profile, store.structure, currency=store.currency,
                           features=store.features, seed=test_seed(mapping), writes_enabled=False)
    return fresh


# ---------------------------------------------------------------- pieces of the mapping

def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:80].rstrip("-") or "untitled"


def money(price: str, currency: str) -> dict:
    """"1250.00" -> {"amount_minor": 125000, "currency": "USD"}: exact, never through floating point."""
    return {"amount_minor": int(decimal.Decimal(price).scaleb(2)), "currency": currency}


def _number(price: str):
    d = decimal.Decimal(price)
    return int(d) if d == d.to_integral_value() else float(d)


def file_hash(path: Path) -> Optional[str]:
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_manifest_hash(assets: List[dict]) -> str:
    """What an approval binds for the images: which files, their bytes, and their order."""
    return sha256_hex(canonical_json([{"derivative_id": a["derivative_id"], "sha256": a["sha256"], "order": i}
                                      for i, a in enumerate(assets)]))


class _Issues:
    def __init__(self, destination: str):
        self.destination, self.items = destination, []

    def add(self, target: str, question: str, severity: str = "blocking", resolver: str = "reviewer"):
        self.items.append({"id": f"RI-{len(self.items) + 1}", "severity": severity, "gate": 3,
                           "destination": self.destination, "target": target, "question": question,
                           "resolver": resolver})


def has_unit(size: str) -> bool:
    return bool(re.search(r"\b(in|cm)\b\s*$", size or ""))


# ---------------------------------------------------------------- the change set

def build(*, item: dict, entry: dict, record: Optional[dict], copy: Optional[dict], assets: List[dict],
          mapping: dict, store: FakeStorefront, status: str = STATUS) -> dict:
    """The sealed change set for one listing. `assets` are the listing images in order, each
    {"derivative_id", "kind", "sha256"}. Blockers are in `change_set["blockers"]`."""
    sf, facts = store.storefront_id, entry.get("facts") or {}
    issues = _Issues(sf)
    approved = entry.get("approved")
    key = f"cos-{item['id']}"[:120]

    if not record or not copy:
        issues.add("copy.draft", "There's no draft yet: draft the copy first.")
    elif not approved:
        issues.add("copy.approval", "Approve the copy first: the storefront only gets approved copy.")
    copy = copy or {}
    copy_status = "human_confirmed" if approved else "inferred"

    fields = {"id": {"value": key, "status": "observed"},
              "name": {"value": copy.get("title") or "", "status": copy_status},
              "slug": {"value": _slug(copy.get("title"), key, store), "status": "inferred"},
              "short_description": {"value": copy.get("short_description") or "", "status": copy_status},
              "description": {"value": copy.get("collector_description") or "", "status": copy_status},
              "status": {"value": status, "status": "human_confirmed"}}

    medium, size = facts.get("medium"), facts.get("dimensions")
    price, sold_as, edition = facts.get("price"), facts.get("sold_as"), facts.get("edition")
    if medium:
        fields["medium"] = {"value": medium, "status": "supplied"}
    else:
        issues.add("product.material", "What is it made with? Supply the medium under About this piece.")
    if size and has_unit(size):
        fields["dimensions"] = {"value": size, "status": "supplied"}
    else:
        issues.add("product.dimensions", "How big is it? Supply the size, with inches or cm, under About this piece.")
    tiers = mapping.get("tier_types") or []
    if not sold_as:
        issues.add("product.sold_as", "Is it sold as an original or a print? Choose under About this piece.")
    elif sold_as not in tiers:
        issues.add("product.sold_as", f"\"{sold_as}\" isn't one of the store's tier types ({', '.join(tiers)}).")
        sold_as = None
    if sold_as and edition:
        if (sold_as == ORIGINAL and edition == "print") or (sold_as != ORIGINAL and edition == "original"):
            issues.add("product.edition", f"Edition says {edition}, but it's sold as {sold_as}. Make them agree.")
    if price:
        fields["price"] = {"value": money(price, store.currency), "status": "supplied"}
    else:
        issues.add("product.price", "What does it sell for? Supply the price under About this piece.")
    if price and sold_as:
        tier = {"id": _tier_id(key), "type": sold_as, "price": _number(price), "description": ""}
        if size:
            tier["size"] = size
        fields["pricing_tiers"] = {"value": [tier], "status": "supplied"}
    if sold_as:
        fields["is_original"] = {"value": sold_as == ORIGINAL, "status": "supplied"}

    category = _category(item.get("kind"), sold_as, mapping, store)
    if category:
        fields["category_id"] = {"value": category, "status": "human_confirmed"}      # owner-confirmed mapping
    else:
        issues.add("product.category", f"No store category is mapped for a {item.get('kind') or 'piece'}"
                   f"{' sold as ' + sold_as if sold_as else ''}. Add it with /edit-mappings.", resolver="administrator")

    tag_ids, unknown = _tags(copy.get("store_tags") or [], store)
    fields["tags"] = {"value": tag_ids, "status": copy_status}
    for name in unknown:
        issues.add("product.tags", f"\"{name}\" isn't a tag in the store, so it's left off.", severity="warning")

    planned = [{"derivative_id": a["derivative_id"], "sha256": a["sha256"],
                "destination_key": f"/objects/uploads/{key}-{a['kind']}-{a['sha256'][:12]}"} for a in assets]
    fields["images"] = {"value": [a["destination_key"] for a in planned], "status": "observed"}
    if not planned:
        issues.add("product.images", "There's no listing image yet: accept the crop on the Photos page.")
    else:
        issues.add("assets.delivery", "The images aren't uploaded to the store yet (upload isn't authorized). "
                   "This happens after approval, with exactly these files.", resolver="operator")

    body = {
        "contract": "change-set", "contract_version": 1,
        "change_set_id": "pending",
        "submission_id": f"sub-{item['id']}"[:128],
        "destination": sf, "environment": store.environment,
        "canonical_revision": (approved or {}).get("revision") or (record or {}).get("draft", {}).get("revision") or 1,
        "mapping_version": int(mapping.get("version") or 1),
        "schema_fingerprint": store.fingerprint,
        "asset_manifest_hash": asset_manifest_hash(assets),
        "requested_status": status,
        "operations": [{"seq": 1, "op": "create", "entity": "product", "key": key,
                        "precondition": {"must_not_exist": True}, "fields": fields}],
        "assets": [{"derivative_id": a["derivative_id"], "destination_key": a["destination_key"], "delivered": False}
                   for a in planned],
        "not_touched": list(NOT_TOUCHED),
        "blockers": issues.items,
        "change_set_hash": None,
        "simulated": True,
    }
    # the id follows from the contents, so the same listing gives the same change set every time
    body["change_set_id"] = f"cs-{item['id'][:90]}-{change_set_hash(dict(body, change_set_id=''))[:12]}"
    return seal(body)


def _slug(title, key: str, store: FakeStorefront) -> str:
    slug = slugify(title)
    taken = {r.get("slug") for r in store.tables["products"].values() if r.get("id") != key}
    return slug if slug not in taken else f"{slug}-{hashlib.sha256(key.encode()).hexdigest()[:6]}"


def _tier_id(key: str) -> str:
    return f"tier-{int(hashlib.sha256(key.encode()).hexdigest()[:11], 16)}"


def _category(kind, sold_as, mapping: dict, store: FakeStorefront) -> Optional[str]:
    pt = (mapping.get("product_types") or {}).get(kind or "")
    if not isinstance(pt, dict) or not pt.get("category"):
        return None
    key = pt["category"]
    if sold_as and sold_as != ORIGINAL and pt.get("alternative_categories"):
        key = pt["alternative_categories"][0]           # artwork with no Original tier is a print (mapping note)
    cid = test_id("category", key)
    return cid if cid in store.tables["categories"] else None


def _tags(names: List[str], store: FakeStorefront):
    by_name = {r["name"].lower(): r["id"] for r in store.tables["tags"].values() if r.get("name")}
    ids, unknown = [], []
    for n in names:
        tid = by_name.get(n.strip().lower())
        if tid and tid not in ids:
            ids.append(tid)
        elif not tid:
            unknown.append(n)
    return ids, unknown


# ---------------------------------------------------------------- reading it

def approvable(change_set: dict) -> bool:
    return not [b for b in change_set["blockers"] if b["severity"] == "blocking" and b["target"] not in AFTER_APPROVAL]


def preview_rows(change_set: dict, plan: list, store: Optional[FakeStorefront] = None) -> List[dict]:
    """What the product would receive, field by field, in the store's own terms. `display` gives category and
    tag names in place of their ids."""
    op = change_set["operations"][0]
    names = {r["id"]: r.get("name") for t in ("categories", "tags") for r in (store.tables[t].values() if store else [])}
    after = (plan[0].get("after") if plan else None) or {}
    before = (plan[0].get("before") if plan else None) or {}
    rows = []
    for col, f in op["fields"].items():
        value = after.get(col, f["value"])
        display = ([names.get(v, v) for v in value] if col == "tags" else names.get(value, value) if col == "category_id"
                   else value)
        rows.append({"column": col, "label": LABELS.get(col, col), "value": value, "display": display,
                     "before": before.get(col), "evidence": f["status"]})
    order = list(LABELS)
    return sorted(rows, key=lambda r: order.index(r["column"]) if r["column"] in order else len(order))


def differences(old: dict, new: dict) -> List[str]:
    """In words, what changed between an approved change set and the one the listing gives now."""
    out = []
    of, nf = old["operations"][0]["fields"], new["operations"][0]["fields"]
    for col in sorted(set(of) | set(nf), key=lambda c: list(LABELS).index(c) if c in LABELS else 99):
        if col == "images":
            continue
        if (of.get(col) or {}).get("value") != (nf.get(col) or {}).get("value"):
            out.append(LABELS.get(col, col))
        elif (of.get(col) or {}).get("status") != (nf.get(col) or {}).get("status") and col in ("name", "description"):
            out.append("Copy approval")
    if old["asset_manifest_hash"] != new["asset_manifest_hash"]:
        out.append("Images")
    if old["mapping_version"] != new["mapping_version"]:
        out.append("Store mapping")
    if old["schema_fingerprint"] != new["schema_fingerprint"]:
        out.append("Store schema")
    if old["requested_status"] != new["requested_status"]:
        out.append("Status")
    if old["canonical_revision"] != new["canonical_revision"] and "Copy approval" not in out:
        out.append("Copy revision")
    return list(dict.fromkeys(out)) or (["Change set"] if old["change_set_hash"] != new["change_set_hash"] else [])
