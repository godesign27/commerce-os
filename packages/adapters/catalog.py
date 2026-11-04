"""One storefront's catalog, read only, and which of its products may already be a new piece (PRD §10, B-065).

`read_snapshot` takes one connection, to one storefront, and refuses a login that could write or could see
anything beyond the catalog tables. It reads only the columns matching needs: no price, stock or customer
data. The result is kept per storefront in .commerce-os/catalog/ (gitignored), so previews work from a
dated copy and the store is only contacted when the owner asks.

`find_matches` ranks possible matches with the evidence for and against. It never decides identity and its
values never become a listing's facts: a likely match is a question for the owner. Thresholds are starting
values that nobody has measured yet against a labeled sample, so no accuracy is claimed for them.

Stdlib only; Python 3.9+.
"""
import json
import os
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional

from packages.adapters.artstore_map import ORIGINAL, slugify

ALLOWED = ("products", "categories", "tags")
WRITE_PRIVILEGES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
PRODUCT_COLUMNS = ("id", "name", "slug", "sku", "status", "category_id", "is_original", "medium", "dimensions")
LIST_COLUMNS = ("id", "name", "slug")
LIKELY_OVERLAP = 0.75               # title word overlap from which a candidate needs the owner's answer
MAX_CANDIDATES = 5
DECISIONS = ("same", "different")
# Words that say nothing about which piece this is.
GENERIC = {"a", "an", "and", "art", "artwork", "at", "by", "canvas", "for", "from", "in", "of", "on", "original",
           "painting", "print", "the", "to", "with", "wall"}
_LOCK = threading.Lock()


class CatalogError(Exception):
    """The catalog couldn't be read or saved; what was there before is untouched. Safe to show the owner."""


# ---------------------------------------------------------------- reading the store

def guard(privileges: Dict[str, dict]) -> List[str]:
    """Why this login mustn't be used. `privileges` maps table -> {"SELECT": bool, "INSERT": bool, ...}."""
    problems = []
    writable = sorted(f"{t} ({p})" for t, row in privileges.items() for p in WRITE_PRIVILEGES if row.get(p))
    if writable:
        problems.append("it can change data: " + ", ".join(writable))
    other = sorted(t for t, row in privileges.items() if t not in ALLOWED and row.get("SELECT"))
    if other:
        problems.append("it can read tables beyond the catalog: " + ", ".join(other))
    missing = [t for t in ALLOWED if not privileges.get(t, {}).get("SELECT")]
    if missing:
        problems.append("it can't read: " + ", ".join(missing))
    return problems


def _privileges(pg) -> Dict[str, dict]:
    columns = ", ".join(f"has_table_privilege(c.oid, '{p}') AS \"{p}\"" for p in ("SELECT",) + WRITE_PRIVILEGES)
    rows = pg.rows(f"SELECT c.relname AS t, {columns} FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                   "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')")
    return {r.pop("t"): r for r in rows}


def read_snapshot(pg, storefront: str, now: str) -> dict:
    """One dated copy of one storefront's catalog. `pg.rows(sql)` runs one read-only query."""
    problems = guard(_privileges(pg))
    if problems:
        raise CatalogError("This login isn't safe to use for reading the store, so nothing was read: "
                           + "; ".join(problems) + ". See docs/runbooks/read-only-role.md.")
    return {"storefront": storefront, "read_at": now,
            "products": pg.rows(f"SELECT {', '.join(PRODUCT_COLUMNS)} FROM public.products ORDER BY id"),
            "categories": pg.rows(f"SELECT {', '.join(LIST_COLUMNS)} FROM public.categories ORDER BY name"),
            "tags": pg.rows(f"SELECT {', '.join(LIST_COLUMNS)} FROM public.tags ORDER BY name"),
            "tier_types": read_tier_types(pg)}


def read_tier_types(pg) -> List[str]:
    """How the store sells things, as names only: never a tier's price."""
    rows = pg.rows("SELECT DISTINCT t->>'type' AS type FROM public.products p, jsonb_array_elements(p.pricing_tiers) t "
                   "WHERE jsonb_typeof(p.pricing_tiers) = 'array' AND t->>'type' IS NOT NULL")
    return sorted(r["type"] for r in rows)


class Catalog:
    """The saved snapshot and the owner's answers, for one storefront only."""

    def __init__(self, root: Path, storefront: str):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", storefront or ""):
            raise ValueError(f"bad storefront id {storefront!r}")
        self.root, self.storefront = Path(root), storefront
        self.path = self.root / f"{storefront}.json"
        self.answers_path = self.root / f"{storefront}.answers.jsonl"
        self.structure_path = self.root / f"{storefront}.structure.json"

    def load(self) -> Optional[dict]:
        if not self.path.exists():
            return None
        snap = json.loads(self.path.read_text())
        if snap.get("storefront") != self.storefront:          # a catalog is never used for the other store
            raise CatalogError(f"{self.path.name} holds another storefront's catalog; read it again.")
        return snap

    def save(self, snap: dict):
        if snap.get("storefront") != self.storefront:
            raise CatalogError("That catalog belongs to another storefront, so it wasn't saved.")
        old = self.load()
        if old and old["products"] and not snap["products"]:
            # a role with no read policy sees zero rows, which looks just like an empty store
            raise CatalogError(f"The store returned no products, but {len(old['products'])} were there last time. "
                               "The login has probably lost its read policy, so the last copy was kept.")
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap, indent=1, default=str))
        os.replace(tmp, self.path)

    def structure(self) -> Optional[dict]:
        """The connected store's structure, as read: what previews are checked against."""
        return json.loads(self.structure_path.read_text()) if self.structure_path.exists() else None

    def save_structure(self, tables: dict, fingerprint: str, profile: str):
        self.root.mkdir(parents=True, exist_ok=True)
        self.structure_path.write_text(json.dumps({"storefront": self.storefront, "catalog_profile": profile,
                                                   "fingerprint": fingerprint, "tables": tables}, indent=1))

    def answers(self, item: str) -> Dict[str, str]:
        """product id -> "same" or "different": the owner's latest answer for this piece."""
        if not self.answers_path.exists():
            return {}
        out = {}
        for line in self.answers_path.read_text().splitlines():
            rec = json.loads(line) if line.strip() else None
            if rec and rec["item"] == item:
                out[rec["product_id"]] = rec["answer"]
        return {k: v for k, v in out.items() if v}

    def answer(self, item: str, product_id: str, answer: Optional[str], by: str, at: str):
        if answer is not None and answer not in DECISIONS:
            raise ValueError(f"answer must be one of {DECISIONS} or null")
        self.root.mkdir(parents=True, exist_ok=True)
        with _LOCK, self.answers_path.open("a") as f:
            f.write(json.dumps({"item": item, "product_id": product_id, "answer": answer, "by": by, "at": at},
                               sort_keys=True) + "\n")


# ---------------------------------------------------------------- matching

def words(text: Optional[str]) -> set:
    out = set()
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        w = w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
        if w not in GENERIC:
            out.add(w)
    return out


def _numbers(size: Optional[str]) -> List[str]:
    return sorted(str(float(n)) for n in re.findall(r"\d+(?:\.\d+)?", size or ""))


def _conflicts(product: dict, facts: dict) -> List[str]:
    out = []
    medium, size, sold_as = facts.get("medium"), facts.get("dimensions"), facts.get("sold_as")
    theirs = (product.get("medium") or "").strip()
    if medium and theirs and medium.strip().lower() != theirs.lower():
        out.append(f"Medium differs: you supplied {medium}, the store has {theirs}")
    if size and product.get("dimensions") and _numbers(size) != _numbers(product["dimensions"]):
        out.append(f"Size differs: you supplied {size}, the store has {product['dimensions']}")
    if sold_as and product.get("is_original") is not None and (sold_as == ORIGINAL) != bool(product["is_original"]):
        out.append("One is an original and the other isn't")
    return out


def find_matches(*, title: Optional[str], subject: str = "", facts: Optional[dict] = None, products: List[dict],
                 answers: Optional[Dict[str, str]] = None) -> List[dict]:
    """Ranked candidates, most likely first. "likely" needs the owner's answer; "possible" is for information."""
    facts, answers = facts or {}, answers or {}
    ours, slug, subject_words = words(title), slugify(title), words(subject)
    found = []
    for p in products:
        theirs = words(p.get("name"))
        shared = ours & theirs
        matching, overlap = [], (len(shared) / len(ours | theirs)) if ours | theirs else 0.0
        same_slug = bool(title) and p.get("slug") == slug
        if same_slug:
            matching.append("Same web address")
        if ours and ours == theirs:
            matching.append("Same title")
        elif shared:
            matching.append("Title shares: " + ", ".join(sorted(shared)))
        named = subject_words & theirs
        if named and not named <= shared:
            matching.append("Names the same subject: " + ", ".join(sorted(named)))
        if not matching:
            continue
        likely = same_slug or (ours and ours == theirs) or (overlap >= LIKELY_OVERLAP and len(shared) >= 2)
        found.append({"product_id": p["id"], "name": p.get("name"), "slug": p.get("slug"), "status": p.get("status"),
                      "level": "likely" if likely else "possible", "score": round(overlap, 3), "matching": matching,
                      "conflicting": _conflicts(p, facts), "medium": p.get("medium"), "dimensions": p.get("dimensions"),
                      "answer": answers.get(p["id"])})
    found.sort(key=lambda c: (c["level"] != "likely", -c["score"], c["name"] or ""))
    answered = [c for c in found if c["answer"]]       # an answer stays visible, however far down it ranks
    shown = found[:MAX_CANDIDATES]
    return shown + [c for c in answered if c not in shown]


def issues(candidates: List[dict]) -> List[dict]:
    """What the candidates ask of the owner before a change set can be approved."""
    out = []
    for c in candidates:
        if c["answer"] == "same":
            out.append({"target": "catalog.match", "question": f"You said this is \"{c['name']}\", already in the "
                        "store. Only new products can go in for now, so it can't be approved as a new one."})
        elif c["level"] == "likely" and not c["answer"]:
            out.append({"target": "catalog.match", "question": f"\"{c['name']}\" in the store looks like this piece. "
                        "Is it the same one? Answer under Already in the store."})
    return out


def taken_slugs(snapshot: Optional[dict]) -> set:
    return {p["slug"] for p in (snapshot or {}).get("products", []) if p.get("slug")}
