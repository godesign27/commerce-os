#!/usr/bin/env python3
"""Local API for the review dashboard (B-057): a stand-in for the workflow service, on this computer only.

    .venv/bin/python services/local_api/server.py [--port 8770] [--storefront storefront-a]

Serves the built dashboard (apps/review-dashboard/dist) and a JSON API over the local files: review items,
listing drafts and revisions, the reviewer's edits and supplied facts, copy approval, the brand context,
the learning loop, first-run setup and the start page. Binds 127.0.0.1 only, never 0.0.0.0: it shows unpublished artwork. Every request
that changes something must carry the header `X-Commerce-OS: 1`, which a page on another site can't send
without a CORS preflight this server never grants.

Nothing here writes to a storefront, and it holds no write login. Approving copy locks it locally. The preview and
its approval (Gate 3, B-064) run against a fake store. Publishing only asks: services/workers/publisher.py is the
one program that writes, after Gate 4 (B-070).
"""
import argparse
import json
import mimetypes
import os
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from packages import onboarding  # noqa: E402
from packages.adapters import artstore_map, catalog, updates  # noqa: E402
from packages.drafting import audit, brand, editing, learning, listing, publication, service  # noqa: E402
from packages.drafting.store import LockedError, Store  # noqa: E402
from packages.image_pipeline import intake, room_suggest, rooms, stages  # noqa: E402
from packages.publisher import records as publishing  # noqa: E402
from packages import journey  # noqa: E402


def _load_script(name: str):
    """scripts/ aren't a package; load one as a module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ri = _load_script("review_images")       # the photo decisions' rules
_DECISIONS_LOCK = threading.Lock()
_ROOMS_LOCK = threading.Lock()

HOST = "127.0.0.1"
OUT = REPO / ".commerce-os" / "review"
DIST = REPO / "apps" / "review-dashboard" / "dist"
CONFIG = REPO / "config" / "storefronts.local.json"
MAX_BODY = 1_000_000
OWNER = {"kind": "human", "id": "owner", "role": "administrator"}


class ApiError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class App:
    """All behaviour, independent of HTTP, so tests can call it directly."""

    def __init__(self, out: Path = OUT, storefront: str = "storefront-a", brand_root: Path = brand.BRAND_DIR,
                 learning_root: Path = learning.LEARNING, config: Path = CONFIG, client_factory=None, call=None,
                 source: Path = None, rooms_root: Path = rooms.ROOMS, approvals_root: Path = None,
                 audit_root: Path = None, mapping: Path = None, catalog_root: Path = None, inbox: Path = None,
                 intake_root: Path = None, read_catalog=None, env_file: Path = None, connect=None, check_key=None,
                 publications_root: Path = None, read_product=None):
        self.rooms_root = Path(rooms_root)
        # also next to the review folder; the inbox is the one folder the owner uses directly, so it's easy to find
        self.catalog = catalog.Catalog(catalog_root or Path(out).parent / "catalog", storefront)
        self.inbox = Path(inbox) if inbox else (intake.INBOX if Path(out) == OUT else Path(out).parent / "inbox")
        self.intake_root = Path(intake_root) if intake_root else Path(out).parent / "intake"
        self._read_catalog = read_catalog         # tests inject a stand-in for reading the store
        self._read_product = read_product         # tests inject: product id -> the store's row, or None
        self._rows = {}                           # product id -> (read at, row): a short cache of store reads
        self.env_file = Path(env_file) if env_file else (REPO / ".env" if Path(out) == OUT else Path(out).parent / ".env")
        self._connect = connect                   # tests inject: url -> an object with .rows(sql)
        self._check_key = check_key               # tests inject: key -> raises if it's refused
        self._intake_lock = threading.Lock()
        # next to the review folder (.commerce-os/approvals, .commerce-os/audit), so a test's folder holds its own
        self.audit = audit.Audit(audit_root or Path(out).parent / "audit")
        self.approvals = publication.Approvals(approvals_root or Path(out).parent / "approvals", self.audit)
        self._mapping_path, self._mapping, self._fake = mapping, None, None
        self.out, self.storefront, self.brand_root, self.config = Path(out), storefront, Path(brand_root), Path(config)
        # Each target keeps its own records, so a listing published to the test store is still unpublished on the live one.
        self.pubs = publishing.Publications(publications_root or Path(out).parent / ("publications-live" if self._live() else "publications"), self.audit)
        self.source = Path(source) if source else ri.DEFAULT_SOURCE
        self.store = Store(self.out)
        self.learn = learning.Learning(learning_root)
        self.client_factory = client_factory
        self.call = call                          # tests inject a stand-in for listing.call_model
        self.jobs = {}
        self._job_lock = threading.Lock()

    # ------------------------------------------------------------ reading
    def items(self) -> list:
        p = self.out / "items.json"
        return json.loads(p.read_text()) if p.exists() else []

    def item(self, item_id: str) -> dict:
        for it in self.items():
            if it["id"] == item_id:
                return it
        raise ApiError(404, f"no item {item_id!r}")

    def decisions(self) -> dict:
        p = self.out / "decisions.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def brand_ctx(self):
        return brand.load(self.storefront, self.brand_root)

    def _live(self) -> bool:
        """Has the owner turned the live store on (scripts/go_live.py)? This page can only read that."""
        return self.storefront_entry().get("publish_target") == "live"

    def _target(self) -> str:
        return "Live store" if self._live() else "Local test store"

    def storefront_entry(self) -> dict:
        if not self.config.exists():
            return {"id": self.storefront}
        cfg = json.loads(self.config.read_text())
        return next((s for s in cfg.get("storefronts", []) if s["id"] == self.storefront), {"id": self.storefront})

    def state(self) -> dict:
        decisions, listings, drafts = self.decisions(), self.store.listings(), self.store.all_drafts()
        pending = ri.pending(decisions, self.items())
        rows = []
        for it in self.items():
            rec, entry = drafts.get(it["id"]), listings.get(it["id"], {})
            store_state, status = self._journey(it, decisions.get(it["id"], {}), it["id"] in pending, entry, rec)
            issues = rec["draft"]["review_issues"] if rec else []
            rows.append({
                "id": it["id"], "source": it["source"], "kind": it["kind"],
                "image": self._image(it), "framed": it.get("framed"),
                "crop_decision": decisions.get(it["id"], {}).get("decision"),
                "has_art": bool(it.get("art_file")),
                "drafted": bool(rec), "revision": rec["draft"]["revision"] if rec else None,
                "title": (self.store.effective(it["id"], rec) or {}).get("title") if rec else None,
                "approved": bool(entry.get("approved")), "edited": bool(entry.get("edits") or entry.get("chosen_title")),
                "blocking": sum(i["severity"] == "blocking" and not listing.supplied(i, entry.get("facts")) for i in issues),
                "supplied": sum(listing.supplied(i, entry.get("facts")) for i in issues),   # answered: redraft to use
                "warnings": sum(i["severity"] == "warning" for i in issues),
                "category": rec["draft"]["product"]["attributes"].get("category", {}).get("value") if rec else None,
                "storefront": store_state,
                "published": self.pubs.state(it["id"]),
                "status": status, "thumb": self._thumb(it),
            })
        ctx = self.brand_ctx()
        entry = self.storefront_entry()
        return {"storefront": self.storefront, "display_name": entry.get("display_name", self.storefront),
                "site_kind": entry.get("site_kind") or (ctx or {}).get("site_kind"),
                "brand": {"version": ctx["version"], "name": ctx["identity"]["name"],
                          "proposed_lessons": sum(x["status"] == "proposed" for x in ctx["lessons"])} if ctx else None,
                "items": rows, "statuses": journey.STATUSES, "key_configured": bool(self._key()), "jobs": self.job_list(),
                "onboarding": self._steps(), "publish_target": "live" if self._live() else "local"}

    @staticmethod
    def _image(it: dict):
        return it.get("cropped") or it.get("original") or it.get("framed")

    def detail(self, item_id: str) -> dict:
        it = self.item(item_id)
        rec = self.store.draft(item_id)
        entry = self.store.listing(item_id)
        ctx = self.brand_ctx()
        out = {"item": {k: it.get(k) for k in ("id", "source", "kind", "framed", "art_size")},
               "image": self._image(it), "listing": entry,
               "revisions": self.store.revisions(item_id) + ([rec["draft"]["revision"]] if rec else []),
               "meanings": brand.meanings_in_scope(ctx, item_id, entry.get("series")) if ctx else [],
               "categories": [{"id": c["id"], "name": c["name"]} for c in (ctx or {}).get("categories", [])],
               "draft": None, "size_from_name": listing.size_from_name(it.get("source")),
               "tier_types": self.tier_types(), "status": self._status_of(item_id),
               "pipeline": [journey.LABELS[x] for x in journey.PIPELINE]}
        if rec:
            d, a = rec["draft"], rec["draft"]["product"]["attributes"]
            val = lambda k, default=None: a.get(k, {}).get("value", default)  # noqa: E731
            out["draft"] = {
                "revision": d["revision"], "drafted_at": rec["drafted_at"], "model": rec["model"],
                "cost_usd": rec.get("cost_usd"), "prompt": d["policy_versions"].get("prompt"),
                "brand_context": d["policy_versions"].get("brand_context"),
                "proposed": self.store.proposed(rec), "effective": self.store.effective(item_id, rec),
                "title_options": val("title_options") or [], "title_reason": val("title_reason"),
                "category": val("category"), "moment": val("moment"), "observations": val("observations") or [],
                "interpretations": val("interpretations") or [], "ask_artist": val("ask_artist") or [],
                "self_review": val("self_review") or {}, "proposed_new_tags": val("proposed_new_tags") or [],
                "subject": val("subject"), "colors": val("dominant_colors") or [],
                "rotate": val("upright_rotation"), "signature": val("signature_corner"),
                "issues": d["review_issues"], "policy_violations": rec.get("policy_violations", []),
                "inputs": rec.get("inputs", {}),
            }
        return out

    # ------------------------------------------------------------ the reviewer's changes
    def update_listing(self, item_id: str, body: dict) -> dict:
        self.item(item_id)
        allowed = {"facts", "series", "note", "edits", "chosen_title"}
        extra = set(body) - allowed
        if extra:
            raise ApiError(400, f"unknown fields: {sorted(extra)}")
        sold_as = ((body.get("facts") or {}).get("sold_as") or "").strip()
        if sold_as and sold_as not in self.tier_types():
            raise ApiError(400, f"sold as must be one of the store's tier types: {', '.join(self.tier_types()) or 'none set up'}")
        before = self.store.listing(item_id).get("facts") or {}
        try:
            entry = self.store.update(item_id, **body)
            self._audit_facts(item_id, before, entry.get("facts") or {})
            return entry
        except LockedError as e:
            raise ApiError(409, str(e))
        except ValueError as e:
            raise ApiError(400, str(e))

    def name_sizes(self) -> dict:
        """Pieces with no saved size whose file name carries one ("Animal Art 16x20_0005_Lion.jpg"): the list the
        owner checks before saving them all at once."""
        listings = self.store.listings()
        rows = []
        for it in self.items():
            size = listing.size_from_name(it.get("source"))
            if size and not ((listings.get(it["id"]) or {}).get("facts") or {}).get("dimensions"):
                rows.append({"id": it["id"], "source": it["source"], "size": size, "image": self._image(it)})
        return {"pieces": rows}

    def save_name_sizes(self, body: dict) -> dict:
        """Save the file-name size for each piece the owner ticked. A piece that has a size by now keeps it."""
        ids = body.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ApiError(400, 'send {"ids": ["<item id>", ...]}')
        items = {it["id"]: it for it in self.items()}
        unknown = [i for i in ids if i not in items]
        if unknown:
            raise ApiError(404, f"no item {unknown[0]!r}")                 # checked before anything is saved
        saved, skipped = [], []
        for item_id in dict.fromkeys(ids):
            it = items[item_id]
            size = listing.size_from_name(it.get("source"))
            facts = self.store.listing(item_id).get("facts") or {}
            if not size:
                skipped.append({"id": item_id, "reason": "no size in its file name"})
            elif facts.get("dimensions"):
                skipped.append({"id": item_id, "reason": f"already has a size ({facts['dimensions']})"})
            else:
                self.store.update(item_id, facts=dict(facts, dimensions=size))      # the other facts are kept
                self.audit.append(item_id, "facts_saved", f"Size saved from the file name: {size}")
                saved.append({"id": item_id, "size": size})
        return {"saved": saved, "skipped": skipped}

    def save_copy(self, item_id: str, body: dict) -> dict:
        """One section's Save (or Discard, with a null value). Other fields are left as they are."""
        self.item(item_id)
        if set(body) != {"fields"} or not isinstance(body["fields"], dict):
            raise ApiError(400, 'send {"fields": {"<field>": value or null}}')
        try:
            return editing.save(self.store, item_id, body["fields"], self.brand_ctx())
        except LockedError as e:
            raise ApiError(409, str(e))
        except ValueError as e:
            raise ApiError(400, str(e))

    def approve(self, item_id: str) -> dict:
        try:
            return service.approve(item_id, OWNER["id"], store=self.store, learn=self.learn)
        except LockedError as e:
            raise ApiError(409, str(e))
        except ValueError as e:
            raise ApiError(400, str(e))

    def unlock(self, item_id: str) -> dict:
        return self.store.unlock(item_id, OWNER["id"])

    def _audit_facts(self, item_id: str, before: dict, after: dict):
        names = {"medium": "medium", "dimensions": "size", "price": "price", "sold_as": "sold as", "edition": "edition"}
        changed = [names[k] for k in names if before.get(k) != after.get(k)]
        if changed:
            self.audit.append(item_id, "facts_saved", "Saved " + ", ".join(changed),
                              facts={k: after.get(k) for k in names if before.get(k) != after.get(k)})

    # ------------------------------------------------------------ Storefront A preview and approval (B-064)
    def mapping(self):
        if self._mapping is None:
            path = self._mapping_path or self.storefront_entry().get("mapping")
            self._mapping = (artstore_map.load_mapping(path) if path else None) or {}
        return self._mapping

    def tier_types(self) -> list:
        return list(self.mapping().get("tier_types") or [])

    def fake_store(self):
        if self._fake is None:
            structure = self.catalog.structure()
            snapshot = self.catalog.load()
            if self._live() and structure and snapshot:
                self._fake = artstore_map.live_preview(self.storefront, self.mapping(), self.storefront_entry(), structure, snapshot)
                return self._fake
            self._fake = artstore_map.test_store(self.storefront, self.mapping(), self.storefront_entry(), structure) \
                if structure and self.storefront_entry().get("catalog_profile") \
                else artstore_map.test_store(self.storefront, self.mapping())
        return self._fake

    def can_preview(self) -> bool:
        """A preview needs a mapping, and a structure to check it against: read from the store, or in the repo."""
        known = (REPO / "database" / "storefronts" / self.storefront / "catalog-structure.json").exists()
        return bool(self.mapping()) and (known or bool(self.catalog.structure()))

    def _assets(self, it: dict):
        """The listing images in order (the room view, then the framed piece on its own), each with its file's hash;
        and notes on what's missing. A rejected photo has none. The store shows the first image in its listings, so
        the piece on a wall goes first (owner, 2026-11-11)."""
        assets, notes = [], []
        if self.decisions().get(it["id"], {}).get("decision") == "reject" or not it.get("framed"):
            return assets, notes
        # The full-size file is what's delivered; the page shows a smaller copy of it.
        framed = self.out / (it.get("framed_full") or it["framed"]).split("?")[0]
        h = artstore_map.file_hash(framed)
        if h:
            assets.append({"derivative_id": f"drv-{it['id']}-framed", "kind": "framed", "sha256": h,
                           "image": it["framed"], "file": str(framed)})
        if it.get("art_file"):
            view = rooms.room_view(it, rooms.load(self.rooms_root), self.out, self._dimensions(it["id"]))
            vh = artstore_map.file_hash(self.out / view["image"].split("?")[0]) if view and view.get("image") else None
            if vh and not view["stale"]:
                assets.insert(0, {"derivative_id": f"drv-{it['id']}-room", "kind": "room", "sha256": vh,
                               "image": view["image"], "file": str(self.out / view["image"].split("?")[0])})
            else:
                notes.append("No up-to-date room view: hang it in its room on the photo page to add one.")
        return assets, notes

    def change_set(self, item_id: str, it: dict = None, entry: dict = None, rec: dict = None):
        it = it or self.item(item_id)
        entry = self.store.listing(item_id) if entry is None else entry
        rec = self.store.draft(item_id) if rec is None else rec
        assets, notes = self._assets(it)
        copy = self.store.effective(item_id, rec) if rec else None
        cs = artstore_map.build(item=it, entry=entry, record=rec, copy=copy, assets=assets, mapping=self.mapping(),
                                store=self.fake_store(), catalog_issues=catalog.issues(self._candidates(item_id, entry, rec)),
                                taken_slugs=catalog.taken_slugs(self.catalog.load()), simulated=False)
        sets, product_id = self._published(item_id)
        if sets and product_id:                   # in the store already: what changed goes as an update (B-085)
            cs = self._as_update(cs, sets, product_id)
        return cs, assets, notes

    # ------------------------------------------------------------ updates (B-085)
    PRODUCT_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
    STORE_ROW_SECONDS = 10                     # one look at the store serves a page's worth of reads

    def _published(self, item_id: str):
        """The change sets that reached the store for this piece, oldest first, and its product id there."""
        hashes = self.pubs.published_hashes(item_id)
        if not hashes:
            return [], None
        approved = {r["change_set"]["change_set_hash"]: r["change_set"]
                    for r in self.approvals.records(item_id) if r["event"] == "approved"}
        sets = [approved[h] for h in hashes if h in approved]
        last = self.pubs.latest(item_id, "published") or {}
        return sets, last.get("product_id") or (sets[-1]["operations"][0]["key"] if sets else None)

    def store_product(self, product_id: str, fresh: bool = False) -> Optional[dict]:
        """The product as the store has it right now, read with the read-only login. None if it isn't there."""
        if not self.PRODUCT_ID.fullmatch(product_id or ""):
            raise catalog.CatalogError("that isn't a product id")
        hit = self._rows.get(product_id)
        if hit and not fresh and time.time() - hit[0] < self.STORE_ROW_SECONDS:
            return hit[1]
        try:
            if self._read_product:
                row = self._read_product(product_id)
            elif self._live():
                url = self._login_url()
                if not url:
                    raise catalog.CatalogError("there's no read-only login saved for this store")
                rows = self._pg(url).rows(f"SELECT * FROM public.products WHERE id = '{product_id}'")
                row = rows[0] if rows else None
            else:                                  # the local test store has no admin, so nobody edits it there:
                row = self._as_published(product_id)   # it holds what was published (the worker checks that too)
        except SystemExit as e:                    # the read session reports a failed query this way, without secrets
            raise catalog.CatalogError(str(e))
        self._rows[product_id] = (time.time(), row)
        return row

    def _pending_update(self, item_id: str, cs: dict) -> bool:
        """An update that hasn't reached the store yet. Once it has, it's what's published, and nothing waits."""
        return updates.is_update(cs) and cs["change_set_hash"] not in self.pubs.published_hashes(item_id)

    def _as_published(self, product_id: str) -> Optional[dict]:
        """The row Commerce OS last put in the local test store for this product, in the store's own terms."""
        for it in self.items():
            sets, pid = self._published(it["id"])
            if pid == product_id and sets:
                store = self.fake_store()
                return {c: store._to_destination("products", c, f["value"])
                        for c, f in updates.published_fields(sets).items()}
        return None

    def _as_update(self, cs: dict, sets: list, product_id: str) -> dict:
        """For a piece already in the store: the last published change set while nothing changed, otherwise the
        update that sends what changed here and keeps what was edited in the store."""
        published = updates.published_fields(sets)
        if not updates.changed_here(published, cs["operations"][0]["fields"]):
            return sets[-1]
        problem, row = None, None
        try:
            row = self.store_product(product_id)
            if row is None:
                problem = "The product isn't in the store any more, so there's nothing to update."
        except Exception as e:                     # noqa: BLE001  shown to the owner as what's in the way
            problem = f"Couldn't read the product from the store to compare it: {e}"
        store = self.fake_store()
        plan = (updates.plan(published, cs["operations"][0]["fields"], row,
                             lambda col, value: store._to_destination("products", col, value))
                if row is not None else {"send": {}, "expected": {}, "kept": []})
        if not problem and not plan["send"]:       # every change was also made in the store, whose edits win
            return sets[-1]
        return updates.build(cs, product_id, plan, problem)

    def _candidates(self, item_id: str, entry: dict, rec: dict) -> list:
        snap = self.catalog.load()
        if not snap or not rec:
            return []
        copy = self.store.effective(item_id, rec) or {}
        subject = (rec["draft"]["product"]["attributes"].get("subject_name") or {}).get("value") or ""
        return catalog.find_matches(title=copy.get("title"), subject=subject, facts=entry.get("facts"),
                                    products=snap["products"], answers=self.catalog.answers(item_id))

    def _store_check(self, it: dict, entry: dict, rec: dict):
        """Where a drafted listing stands against the store, what's in its way, and what changed since approval."""
        if not self.can_preview():
            return None, [], []
        cs, _, _ = self.change_set(it["id"], it, entry, rec)
        approval = self.approvals.status(it["id"], cs)
        if self._pending_update(it["id"], cs):   # a published piece's update needs its own approval
            if approval["state"] == "current":
                state = "approved"
            else:
                state = "ready" if artstore_map.approvable(cs) else "blocked"
            return state, cs["blockers"], self._update_changes(cs)
        if approval["state"] != "none":
            state = {"current": "approved", "out_of_date": "out_of_date"}[approval["state"]]
        else:
            state = "ready" if artstore_map.approvable(cs) else "blocked"
        return state, cs["blockers"], approval.get("changes") or []

    @staticmethod
    def _update_changes(cs: dict) -> list:
        """What an update would change, in words, then what it keeps as the store has it."""
        op = cs["operations"][0]
        sent = [artstore_map.LABELS.get(c, c) for c in updates.UPDATABLE if c in op["fields"]]
        kept = [artstore_map.LABELS.get(k["column"], k["column"]) for k in cs.get("kept", [])]
        return sent + [f"{k} (kept as the store has it)" for k in kept]

    def _storefront_state(self, it: dict, entry: dict, rec: dict):
        return self._store_check(it, entry, rec)[0]

    def _journey(self, it: dict, decision: dict, pending: bool, entry: dict, rec: dict):
        """The listing's state against the store, and the piece's one status (packages/journey.py)."""
        store_state, blockers, changes = self._store_check(it, entry, rec) if rec else (None, [], [])
        stage = stages.stage(it, decision, pending, bool(rec), bool(entry.get("approved")))
        published = bool(self.pubs.published_hashes(it["id"]))
        update = published and store_state is not None and bool(changes)
        return store_state, journey.status(stage=stage, drafted=bool(rec), copy_approved=bool(entry.get("approved")),
                                           publish_state=self.pubs.state(it["id"]), store_state=store_state,
                                           blockers=blockers, changes=changes, published=published, update=update)

    def _status_of(self, item_id: str) -> dict:
        it, decisions = self.item(item_id), self.decisions()
        pending = ri.pending(decisions, self.items())
        return self._journey(it, decisions.get(item_id, {}), item_id in pending, self.store.listing(item_id),
                             self.store.draft(item_id))[1]

    def _thumb(self, it: dict):
        """A small copy of the piece for the start page, made once and again if the piece changes. Falls back to the
        full image: a missing thumbnail must never stop a page."""
        image = self._image(it)
        if not image:
            return None
        source = self.out / image.split("?")[0]
        target = self.out / "img" / "thumbs" / f"{it['id']}.jpg"
        try:
            if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
                from PIL import Image
                target.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(source) as im:
                    im = im.convert("RGB")
                    im.thumbnail((240, 240))
                    part = target.with_name(f".{target.name}.part")
                    im.save(part, "JPEG", quality=82)
                os.replace(part, target)
            return f"img/thumbs/{target.name}?v={int(target.stat().st_mtime)}"
        except (OSError, ValueError):
            return image

    def _history(self, item_id: str) -> list:
        drafts = []
        for n in self.store.revisions(item_id):
            p = self.store.drafts / "history" / f"{item_id}.r{n}.json"
            if p.exists():
                drafts.append(json.loads(p.read_text()))
        rec = self.store.draft(item_id)
        if rec:
            drafts.append(rec)
        return audit.timeline(item_id, self.audit, decision=self.decisions().get(item_id),
                              drafts=drafts, entry=self.store.listing(item_id))

    def storefront_preview(self, item_id: str) -> dict:
        it = self.item(item_id)
        entry = self.storefront_entry()
        if not self.can_preview():
            return {"available": False, "reason": "The store isn't connected yet: finish Getting started.",
                    "history": self._history(item_id)}
        cs, assets, notes = self.change_set(item_id, it)
        fs = self.fake_store()
        update = None
        if self._pending_update(item_id, cs):      # the store's copy has the row; the preview shows the change
            expected = cs["operations"][0]["precondition"]["expected_fields"]
            rows = artstore_map.preview_rows(cs, [], fs)
            for r in rows:
                r["before"] = expected.get(r["column"])
            names = {r["id"]: r.get("name") for t in ("categories", "tags") for r in fs.tables[t].values()}
            show = lambda col, v: ([names.get(x, x) for x in v] if col == "tags" and isinstance(v, list)  # noqa: E731
                                   else names.get(v, v) if col == "category_id" else v)
            update = {"product_id": cs["operations"][0]["key"], "kept": [
                {"column": k["column"], "label": artstore_map.LABELS.get(k["column"], k["column"]),
                 "store": show(k["column"], k["store"]), "ours": show(k["column"], k["ours"])} for k in cs.get("kept", [])]}
            dry = {"would_publish": artstore_map.approvable(cs), "issues": [], "plan": []}
        else:
            dry = fs.dry_run(cs)
            rows = artstore_map.preview_rows(cs, dry["plan"], fs)
        return {
            "available": True, "storefront": self.storefront,
            "display_name": entry.get("display_name", self.storefront), "environment": fs.environment,
            "change_set": {k: cs[k] for k in ("change_set_id", "change_set_hash", "requested_status", "mapping_version",
                                              "canonical_revision", "asset_manifest_hash", "not_touched")},
            "rows": rows, "update": update,
            "images": [{"kind": a["kind"], "image": a["image"]} for a in assets],
            "blockers": cs["blockers"], "notes": notes,
            "dry_run": {"would_publish": dry["would_publish"], "issues": dry["issues"]},
            "approvable": artstore_map.approvable(cs),
            "approval": self.approvals.status(item_id, cs),
            "catalog": self._catalog_doc(item_id),
            "publish": self._publish_doc(item_id),
            "history": self._history(item_id),
        }

    # ------------------------------------------------------------ publishing (B-070): asks; the worker does the rest
    def _publish_doc(self, item_id: str) -> dict:
        state = self.pubs.state(item_id)
        published = self.pubs.latest(item_id, "published")     # still in the store after a failed update
        rechecked = self.pubs.latest(item_id, "rechecked") if state == publishing.UNKNOWN else None
        ended = next((e for e in reversed(self.pubs.events(item_id)) if e.get("state") == publishing.FAILED), None)
        return {"target": self._target(), "live": self._live(), "state": state, "kill_switch": self.pubs.kill_switch(),
                "worker": self.pubs.worker(), "product_id": (published or {}).get("product_id"),
                "receipt_id": (published or {}).get("receipt_id"), "published_at": (published or {}).get("at"),
                "reasons": (ended or {}).get("reasons", []) if state == publishing.FAILED else [],
                "finding": (rechecked or {}).get("finding"), "fields": (rechecked or {}).get("fields", []),
                "checking": self.pubs.recheck_wanted(item_id), "last_op": (published or {}).get("op", "create") if published else None}

    def publish(self, item_id: str, body: dict) -> dict:
        """Ask the worker to publish what the owner approved. This writes nothing to a store."""
        self.item(item_id)
        if not isinstance(body, dict) or set(body) != {"change_set_hash"}:
            raise ApiError(400, 'send {"change_set_hash": "<the hash you approved>"}')
        if not self.can_preview():
            raise ApiError(400, "the store isn't connected yet: finish Getting started")
        cs, _, _ = self.change_set(item_id)
        status = self.approvals.status(item_id, cs)
        if status["state"] != "current" or status["approval"]["change_set_hash"] != body["change_set_hash"]:
            raise ApiError(409, "This version isn't approved: approve it first.")
        try:
            self.pubs.request(item_id, cs, status["approval"], OWNER["id"])
        except publishing.PublishError as e:
            raise ApiError(409, str(e))
        return self.storefront_preview(item_id)

    @staticmethod
    def _queue_section(publish_state, approval_state: str, published: bool = False, update: bool = False) -> str:
        """Where a drafted listing belongs on the publish page. What's happening now comes first. A piece already in
        the store stays published until its listing changes; then it waits in "changed" for an approved update (B-085)."""
        if publish_state in (publishing.QUEUED, publishing.WRITING):
            return "working"
        if publish_state == publishing.UNKNOWN:
            return "problems"
        if update:
            if approval_state != "current":
                return "changed"
            return "problems" if publish_state == publishing.FAILED else "ready"
        if published or publish_state == publishing.SUCCEEDED:
            return "published"
        if approval_state != "current":
            return "waiting"
        return "problems" if publish_state == publishing.FAILED else "ready"

    def _queue_row(self, it: dict, rec: dict):
        cs, assets, _ = self.change_set(it["id"], it, None, rec)
        fields = cs["operations"][0]["fields"]
        tiers = (fields.get("pricing_tiers") or {}).get("value") or [{}]
        status = self.approvals.status(it["id"], cs)
        doc = self._publish_doc(it["id"])
        update = self._pending_update(it["id"], cs)
        section = self._queue_section(doc["state"], status["state"], bool(doc["product_id"]), update)
        if section == "changed":
            op, kept = cs["operations"][0], cs.get("kept", [])
            sent = [artstore_map.LABELS.get(c, c) for c in updates.UPDATABLE if c in op["fields"]]
            nxt = ([f"Would change: {', '.join(sent)}."]
                   + ([f"Kept as the store has it: {', '.join(artstore_map.LABELS.get(k['column'], k['column']) for k in kept)}."] if kept else [])
                   if artstore_map.approvable(cs) else
                   [b["question"] for b in cs["blockers"] if b["severity"] == "blocking" and b["target"] != "assets.delivery"])
        elif status["state"] == "out_of_date":
            nxt = [f"Changed since you approved it: {', '.join(status['changes'])}. Approve this version."]
        elif artstore_map.approvable(cs):
            nxt = ["Check what the store would receive, then approve it."]
        else:
            nxt = [b["question"] for b in cs["blockers"] if b["severity"] == "blocking" and b["target"] != "assets.delivery"]
        row = {"id": it["id"], "source": it["source"], "title": (self.store.effective(it["id"], rec) or {}).get("title"),
               "image": assets[0]["image"] if assets else self._image(it), "price": (fields.get("price") or {}).get("value"),
               "sold_as": tiers[0].get("type"), "size": tiers[0].get("size"),
               "change_set_hash": cs["change_set_hash"] if section in ("ready", "problems") else None,
               "approved_at": (status["approval"] or {}).get("approved_at"),
               "next": nxt if section in ("waiting", "changed") else [], "update": update}
        row["status"] = self._status_of(it["id"])
        row.update({k: doc[k] for k in ("state", "product_id", "receipt_id", "published_at", "reasons", "finding", "fields", "checking")})
        return section, row

    def publish_queue(self) -> dict:
        """The publish page: every drafted listing, sorted by what it needs next. This reads; it changes nothing."""
        entry = self.storefront_entry()
        doc = {"available": self.can_preview(), "target": self._target(), "live": self._live(), "display_name": entry.get("display_name", self.storefront),
               "kill_switch": self.pubs.kill_switch(), "worker": self.pubs.worker(), "not_drafted": 0,
               "ready": [], "working": [], "problems": [], "waiting": [], "changed": [], "published": []}
        if not doc["available"]:
            return dict(doc, reason="The store isn't connected yet.")
        decisions, drafts = self.decisions(), self.store.all_drafts()
        for it in self.items():
            if decisions.get(it["id"], {}).get("decision") == "reject":
                continue
            rec = drafts.get(it["id"])
            if not rec:
                doc["not_drafted"] += 1 if it.get("art_file") else 0
                continue
            section, row = self._queue_row(it, rec)
            doc[section].append(row)
        return doc

    # What the task bar says about each step the worker records (B-077). A publish moves down this list.
    STAGES = {"queued": "Waiting for the publisher", "gate4_passed": "Final check passed", "writing": "Sending images",
              "images_delivered": "Adding it to the store", "published": "In the store as a Draft",
              "gate4_refused": "Didn't go in", "failed": "Didn't go in", "outcome_unknown": "Not sure it went in"}
    RECENT_SECONDS = 600            # a finished job or publish stays on the bar this long

    def activity(self) -> dict:
        """What's being processed right now, for the task bar on every page. It reads; it changes nothing."""
        now = time.time()
        jobs = [{k: j.get(k) for k in ("label", "running", "done", "total", "error")} | {"id": jid}
                for jid, j in list(self.jobs.items())
                if j["running"] or now - (j.get("finished_at") or 0) <= self.RECENT_SECONDS]
        worker, switch = self.pubs.worker(), self.pubs.kill_switch()
        publishing_rows = []
        for item in self.pubs.items():
            events = self.pubs.events(item)
            last = next((e for e in reversed(events) if e.get("state")), None)
            if not last:
                continue
            active = last["state"] in (publishing.QUEUED, publishing.WRITING)
            if not active and publishing._seconds_since(last["at"]) > self.RECENT_SECONDS:
                continue
            step = events[-1]
            stage = self.STAGES.get(step["event"], step["event"].replace("_", " ").capitalize())
            if step["event"] == "queued" and switch["on"]:
                stage = "Held: writing is switched off"
            elif step["event"] == "queued" and not worker["running"]:
                stage = "Held: the publisher isn't running"
            elif step["event"] == "queued" and not worker["ok"]:
                stage = "Held: " + (worker["reason"] or "the publisher hit a problem")
            title = (self.store.effective(item) or {}).get("title") or item
            publishing_rows.append({"id": item, "title": title, "state": last["state"], "stage": stage, "at": step["at"],
                                    "active": active, "detail": "; ".join(last.get("reasons") or []) or last.get("why")})
        publishing_rows.sort(key=lambda r: (not r["active"], r["at"]))
        return {"jobs": jobs, "publishing": publishing_rows, "target": self._target(), "live": self._live(),
                "worker": worker, "kill_switch": switch,
                "active": any(j["running"] for j in jobs) or any(r["active"] for r in publishing_rows)}

    def publish_many(self, body: dict) -> dict:
        """Ask for several at once. Each names the version the owner saw and passes the same checks as one alone, and
        one refused doesn't stop the rest."""
        items = body.get("items") if isinstance(body, dict) and set(body) == {"items"} else None
        if not isinstance(items, list) or not items or not all(isinstance(i, dict) and set(i) == {"id", "change_set_hash"} for i in items):
            raise ApiError(400, 'send {"items": [{"id": "...", "change_set_hash": "<the hash you approved>"}]}')
        results = []
        for i in items:
            try:
                self.publish(i["id"], {"change_set_hash": i["change_set_hash"]})
                results.append({"id": i["id"], "ok": True})
            except ApiError as e:
                results.append({"id": i["id"], "ok": False, "error": str(e)})
        return {"results": results, "queue": self.publish_queue()}

    def publish_recheck(self, item_id: str) -> dict:
        self.item(item_id)
        try:
            self.pubs.ask_recheck(item_id, OWNER["id"])
        except publishing.PublishError as e:
            raise ApiError(409, str(e))
        return self.storefront_preview(item_id)

    def kill_switch(self, body: dict) -> dict:
        if not isinstance(body, dict) or not isinstance(body.get("on"), bool):
            raise ApiError(400, 'send {"on": true} or {"on": false}')
        state = self.pubs.set_kill_switch(body["on"], OWNER["id"])
        self.audit.append("_setup", "kill_switch", f"Writing switched {'off' if body['on'] else 'on'}", by=OWNER["id"])
        return state

    # ------------------------------------------------------------ the store's catalog, read only (B-065)
    def _catalog_doc(self, item_id: str = None) -> dict:
        snap = self.catalog.load()
        if not snap:
            return {"read_at": None, "products": 0, "candidates": []}
        doc = {"read_at": snap["read_at"], "products": len(snap["products"]), "candidates": []}
        if item_id:
            doc["candidates"] = self._candidates(item_id, self.store.listing(item_id), self.store.draft(item_id))
        return doc

    def _env_key(self) -> str:
        prefix = self.storefront_entry().get("env_prefix")
        return f"{prefix}_DB_URL" if prefix else ""

    def _login_url(self) -> str:
        key = self._env_key()
        return (onboarding.read_env(self.env_file).get(key) or os.environ.get(key) or "") if key else ""

    def _pg(self, url: str):
        """A read-only session. Every message from it is safe to show: credentials are taken out."""
        if self._connect:
            return self._connect(url)
        crr = _load_script("check_read_role")
        return crr.Psql(crr.pg_env_from_url(url))

    def _read_store(self) -> dict:
        if self._read_catalog:
            return self._read_catalog()
        if not self._env_key():
            raise catalog.CatalogError("This storefront isn't connected yet: finish Getting started.")
        url = self._login_url()
        if not url:
            raise catalog.CatalogError("There's no read-only login saved for this store yet: finish Getting started.")
        try:
            return catalog.read_snapshot(self._pg(url), self.storefront, brand.now())
        except (SystemExit, ValueError) as e:
            raise catalog.CatalogError("The store couldn't be read: " + onboarding.scrub(e, url, onboarding.url_password(url)))

    def refresh_catalog(self) -> dict:
        def work(job):
            job["total"] = 1
            try:
                snap = self._read_store()
                self.catalog.save(snap)
            except catalog.CatalogError as e:
                job["error"] = str(e)
                return
            job["done"] = 1
            job["results"] = [{"products": len(snap["products"])}]
        return self._start("Read the store's catalog", work)

    def answer_match(self, item_id: str, body: dict) -> dict:
        """The owner's answer to "is this the same piece?". Only a person answers it; Commerce OS never does."""
        self.item(item_id)
        if not isinstance(body, dict) or set(body) != {"product_id", "answer"}:
            raise ApiError(400, 'send {"product_id": "...", "answer": "same" | "different" | null}')
        snap = self.catalog.load()
        product = next((p for p in (snap or {}).get("products", []) if p["id"] == body["product_id"]), None)
        if not product:
            raise ApiError(404, "that product isn't in the catalog copy; read the catalog again")
        try:
            self.catalog.answer(item_id, product["id"], body["answer"], OWNER["id"], brand.now())
        except ValueError as e:
            raise ApiError(400, str(e))
        words = {"same": "the same piece as", "different": "a different piece from", None: "unanswered against"}
        self.audit.append(item_id, "catalog_match_answered", f"Marked {words[body['answer']]} \"{product['name']}\" in the store",
                          by=OWNER["id"], product_id=product["id"], answer=body["answer"])
        return self.storefront_preview(item_id)

    def approve_storefront(self, item_id: str, body: dict) -> dict:
        """Gate 3: the owner approves the change set they were shown, by its hash. Writes nothing to a store."""
        self.item(item_id)
        if not isinstance(body, dict) or set(body) != {"change_set_hash", "status"}:
            raise ApiError(400, 'send {"change_set_hash": "<the hash you saw>", "status": "draft"}')
        if not self.can_preview():
            raise ApiError(400, "the store isn't connected yet: finish Getting started")
        cs, _, _ = self.change_set(item_id)
        try:
            self.approvals.approve(item_id, cs, seen_hash=body["change_set_hash"], status=body["status"],
                                   actor_id=OWNER["id"])
        except publication.ApprovalError as e:
            raise ApiError(409, str(e))
        return self.storefront_preview(item_id)

    # ------------------------------------------------------------ first run (B-068)
    def _steps(self) -> dict:
        entry = self.storefront_entry()
        return onboarding.steps(entry=entry if entry.get("provider") else None, login=bool(self._login_url()),
                                snapshot=bool(self.catalog.load()), mapping=self.mapping() or None, key=bool(self._key()),
                                brand=bool(self.brand_ctx()), photos=len(self.items()))

    def _reset_store(self):
        self._mapping, self._fake = None, None

    def onboarding_doc(self) -> dict:
        """Everything the Getting started page needs. It never holds a credential."""
        entry, snap = self.storefront_entry(), self.catalog.load()
        provider = entry.get("provider")
        mapping = self.mapping()
        doc = dict(self._steps(), storefront=self.storefront,
                   store={k: entry.get(k) for k in ("display_name", "site_kind", "provider", "currency")},
                   providers=[{"id": p["id"], "label": p["display_name"]} for p in onboarding.providers()],
                   login={"env_key": self._env_key() or None, "saved": bool(self._login_url()),
                          "sql": onboarding.login_sql(), "example": onboarding.login_example(provider),
                          "where": onboarding.login_where(provider)},
                   check=None, choices=None)
        if snap:
            doc["check"] = {"read_at": snap["read_at"], "products": len(snap["products"]), "categories": len(snap["categories"]),
                            "tags": len(snap["tags"])}
            ref = lambda r: r["slug"] or r["id"]  # noqa: E731
            in_scope = lambda rows, entries: [ref(r) for r in rows if any(  # noqa: E731
                e.get("status") == "in_scope" and (e.get("slug") == r["slug"] or (e.get("id") or {}).get("production") == r["id"])
                for e in entries)]
            doc["choices"] = {
                "categories": [{"ref": ref(r), "name": r["name"]} for r in snap["categories"]],
                "tags": [{"ref": ref(r), "name": r["name"]} for r in snap["tags"]],
                "tier_types": snap.get("tier_types") or [],
                "tier_ladders": snap.get("tier_ladders") or [],
                "product_types": onboarding.product_types(entry.get("site_kind")),
                "chosen": {"categories": in_scope(snap["categories"], mapping.get("categories", [])),
                           "tags": in_scope(snap["tags"], mapping.get("tags", [])),
                           "tier_types": mapping.get("tier_types", []), "product_types": self._chosen_types(mapping),
                           "tier_ladders": sorted(mapping.get("tier_ladders") or {})}}
        return doc

    @staticmethod
    def _chosen_types(mapping: dict) -> dict:
        slug = {c["key"]: c.get("slug") or c["key"] for c in mapping.get("categories", [])}
        out = {}
        for k, v in (mapping.get("product_types") or {}).items():
            if isinstance(v, dict) and v.get("category"):
                alt = (v.get("alternative_categories") or [None])[0]
                out[k] = {"category": slug.get(v["category"]), "alternative": slug.get(alt)}
        return out

    def onboarding_store(self, body: dict) -> dict:
        try:
            onboarding.save_store(self.config, self.storefront, body)
        except onboarding.SetupError as e:
            raise ApiError(400, str(e))
        self._reset_store()
        return self.onboarding_doc()

    def onboarding_login(self, body: dict) -> dict:
        """Check a read-only login, then save it. A login that fails any check is never saved, and no response or
        message holds it."""
        url = (body.get("url") or "").strip() if isinstance(body, dict) else ""
        key = self._env_key()
        if not key:
            raise ApiError(400, "Say which store this is first.")
        if not url:
            raise ApiError(400, "Enter the login.")
        hidden = (url, onboarding.url_password(url))
        env = onboarding.read_env(self.env_file)
        other_keys = [f"{s['env_prefix']}_DB_URL" for s in onboarding.load_config(self.config)["storefronts"]
                      if s["id"] != self.storefront and s.get("env_prefix")] + ["OPS_DB_URL", "COMMERCE_OS_TEST_DB_URL"]
        if any(env.get(k) == url for k in other_keys):
            raise ApiError(409, "That login belongs to something else here. Every store needs its own.")
        crr = _load_script("check_read_role")
        try:
            pg = self._pg(url)
            role, memberships, privileges, rls = crr.collect(pg)
            results = crr.evaluate(role, memberships, privileges) + crr.evaluate_rls(role["user"], rls)
        except (SystemExit, Exception) as e:      # noqa: B014 - Psql stops with SystemExit
            raise ApiError(400, "Couldn't connect with that login: " + onboarding.scrub(e, *hidden))
        failed = [onboarding.scrub(msg, *hidden) for ok, msg in results if not ok]
        if failed:
            raise ApiError(409, "That login isn't safe to use, so it wasn't saved: " + "; ".join(failed)
                           + ". Use a login made with the script on this page.")
        onboarding.set_env(self.env_file, key, url)
        self.audit.append("_setup", "login_saved", "Read-only login checked and saved", by=OWNER["id"], env_key=key)
        return self.onboarding_doc()

    def onboarding_check(self) -> dict:
        """Read the store: its structure first, then the catalog. Stops if the structure doesn't fit."""
        url, entry = self._login_url(), self.storefront_entry()
        if not url:
            raise ApiError(400, "Save the read-only login first.")
        hidden = (url, onboarding.url_password(url))
        profile = next((p for p in onboarding.profiles() if p["id"] == entry.get("catalog_profile")), None)
        if not profile:
            raise ApiError(400, "This store has no catalog profile.")
        ldb = _load_script("local_storefront_db")
        try:
            pg = self._pg(url)
            tables = ldb.read_structure(pg)
            problems = onboarding.fit(tables, profile)
            if problems:
                raise ApiError(409, "This store's structure doesn't fit what Commerce OS knows how to work with: "
                               + " ".join(problems) + " A new catalog profile would be needed.")
            snap = catalog.read_snapshot(pg, self.storefront, brand.now())
            self.catalog.save(snap)
        except ApiError:
            raise
        except (catalog.CatalogError, SystemExit, Exception) as e:     # noqa: B014
            raise ApiError(400, onboarding.scrub(e, *hidden))
        self.catalog.save_structure(tables, ldb.fingerprint(tables), profile["id"])
        onboarding.record_features(self.config, self.storefront, onboarding.detect_features(tables, profile))
        self._reset_store()
        return self.onboarding_doc()

    def onboarding_mapping(self, body: dict) -> dict:
        snap = self.catalog.load()
        if not snap:
            raise ApiError(400, "Check the store first.")
        entry = self.storefront_entry()
        path = Path(entry.get("mapping") or f"config/mappings/{self.storefront}.local.json")
        path = self._mapping_path and Path(self._mapping_path) or (path if path.is_absolute() else REPO / path)
        try:
            built = onboarding.build_mapping(self.storefront, snap, body, self.mapping() or None, brand.now()[:10])
        except onboarding.SetupError as e:
            raise ApiError(400, str(e))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(built, indent=2) + "\n")
        self._reset_store()
        return self.onboarding_doc()

    def onboarding_key(self, body: dict) -> dict:
        key = (body.get("key") or "").strip() if isinstance(body, dict) else ""
        if not key:
            raise ApiError(400, "Enter the key.")
        try:
            if self._check_key:
                self._check_key(key)
            else:
                import anthropic
                anthropic.Anthropic(api_key=key, max_retries=0, timeout=15).models.list(limit=1)
        except Exception as e:
            kind = "It was refused." if "Authentication" in type(e).__name__ or "Permission" in type(e).__name__ \
                else "Claude couldn't be reached to check it."
            raise ApiError(400, f"That key wasn't saved. {kind}")
        onboarding.set_env(self.env_file, "ANTHROPIC_API_KEY", key)
        return self.onboarding_doc()

    # ------------------------------------------------------------ the start page
    def inbox_status(self) -> dict:
        st = intake.status(self.inbox, self.intake_root)
        return {"new": st["new"], "waiting": st["waiting"], "folder": st["folder"]}

    def home(self) -> dict:
        """The start page: is a store connected, and one summary for each area."""
        state = self.state()
        photos = self.photos({r["id"]: r["status"] for r in state["items"]})
        entry, snap = self.storefront_entry(), self.catalog.load()
        rows, drafted = state["items"], [i for i in state["items"] if i["drafted"]]
        by_stage = {s["id"]: sum(p["stage"] == s["id"] for p in photos["photos"]) for s in photos["stages"]}
        lib = rooms.load(self.rooms_root)["rooms"]
        room_states = [rooms.status(r) for r in lib]
        count = lambda v: sum(i["storefront"] == v for i in drafted)  # noqa: E731
        return {
            "onboarding": state["onboarding"],
            "statuses": journey.STATUSES, "pipeline": [journey.LABELS[x] for x in journey.PIPELINE],
            "pieces": [{"id": i["id"], "title": i["title"], "source": i["source"], "thumb": i["thumb"], "status": i["status"]}
                       for i in rows if i["has_art"] or i["drafted"]],
            "next": journey.next_step([i for i in rows if i["has_art"] or i["drafted"]], setup_done=state["onboarding"]["complete"],
                                      can_draft=state["key_configured"]),
            "store": {"connected": bool(self._login_url() and snap), "display_name": entry.get("display_name"),
                      "site_kind": entry.get("site_kind"),
                      "provider": next((p["display_name"] for p in onboarding.providers() if p["id"] == entry.get("provider")), None),
                      "products": len(snap["products"]) if snap else None, "read_at": snap["read_at"] if snap else None,
                      "writes_enabled": bool(entry.get("writes_enabled"))},
            "inbox": self.inbox_status(),
            "photos": {"total": len(photos["photos"]), "to_review": by_stage.get("to-review", 0) + by_stage.get("not-applied", 0),
                       "ready": by_stage.get("ready", 0), "rejected": by_stage.get("rejected", 0)},
            "listings": {"drafted": len(drafted), "copy_approved": sum(i["approved"] for i in drafted),
                         "blocked": count("blocked"), "ready": count("ready"), "approved": count("approved"),
                         "out_of_date": count("out_of_date"),
                         "published": sum(i["published"] == publishing.SUCCEEDED for i in rows),
                         "publish_problems": sum(i["published"] in (publishing.FAILED, publishing.UNKNOWN) for i in rows),
                         "to_publish": sum(i["storefront"] == "approved" and i["published"] is None for i in drafted)},
            "publishing": {"target": self._target(), "kill_switch": self.pubs.kill_switch(), "worker": self.pubs.worker()},
            "rooms": {"total": len(lib), "ready": room_states.count("ready"), "need_attention": sum(s not in ("ready", "off") for s in room_states)},
            "learning": {"approvals": self.learn.stats()["approvals"],
                         "proposed_lessons": (state["brand"] or {}).get("proposed_lessons", 0)},
        }

    # ------------------------------------------------------------ photos (B-062)
    def photos(self, statuses: dict = None) -> dict:
        items, decisions = self.items(), self.decisions()
        pend = ri.pending(decisions, items)
        rows = stages.photo_rows(items, decisions, self.store.all_drafts(), self.store.listings(), pend,
                                 self.source, self.out)
        if statuses is None:
            statuses = {r["id"]: r["status"] for r in self.state()["items"]}
        drafts = self.store.all_drafts()
        for row in rows:
            row["status"] = statuses.get(row["id"])
            rec = drafts.get(row["id"])
            row["title"] = (self.store.effective(row["id"], rec) or {}).get("title") if rec else None
        return {"stages": [{"id": k, "label": v} for k, v in stages.STAGES], "statuses": journey.STATUSES, "photos": rows,
                "pending": len(pend), "review_page": "http://127.0.0.1:8765/",
                "intake": intake.status(self.inbox, self.intake_root)}

    def scan_inbox(self) -> dict:
        """Bring in what's in the inbox, then crop and frame only the new photos, as a background job."""
        def work(job):
            if not self._intake_lock.acquire(blocking=False):
                job["error"] = "already looking for new photos"
                return
            try:
                job["total"] = len(intake.waiting(self.inbox))
                res = intake.scan(self.inbox, self.source, self.intake_root,
                                  on_file=lambda _: job.__setitem__("done", job["done"] + 1))
                job["results"] = [{k: len(res[k]) for k in ("added", "duplicates", "problems")}]
                if res["added"]:
                    ids = {ri.slug(a["source_name"]) for a in res["added"]}
                    ri.build(self.source, self.out, only=ids, log=lambda *_: None)
            finally:
                self._intake_lock.release()
        return self._start("Look for new photos", work)

    def photo(self, item_id: str) -> dict:
        items = self.items()
        ids = [it["id"] for it in items]
        it = self.item(item_id)
        row = next(r for r in self.photos()["photos"] if r["id"] == item_id)
        i = ids.index(item_id)
        neighbours = [ids[i - 1] if i > 0 else None, ids[i + 1] if i + 1 < len(ids) else None]
        rec = self.store.draft(item_id)
        out = stages.photo_detail(it, row, self.decisions().get(item_id, {}), neighbours)
        out["listing_title"] = (self.store.effective(item_id, rec) or {}).get("title") if rec else None
        entry = self.store.listing(item_id)
        out["facts"], out["series"] = entry.get("facts") or {}, entry.get("series") or ""   # About this piece
        out["dimensions"] = out["facts"].get("dimensions")
        out["size_from_name"] = listing.size_from_name(it.get("source"))
        out["tier_types"] = self.tier_types()
        lib = rooms.load(self.rooms_root)
        out["room"] = rooms.room_view(it, lib, self.out, out["dimensions"]) if it.get("art_file") else None
        out["room_options"] = rooms.options(lib, self.rooms_root)
        return out

    def _dimensions(self, item_id: str):
        return (self.store.listing(item_id).get("facts") or {}).get("dimensions")

    # ------------------------------------------------------------ rooms (B-063)
    def rooms_doc(self) -> dict:
        lib = rooms.load(self.rooms_root)
        inbox = self.rooms_root / "inbox"
        return {"rooms": [rooms.public(r, self.rooms_root) for r in lib["rooms"]],
                "licences": [{"id": k, "label": v} for k, v in rooms.LICENCES.items()],
                "statuses": [{"id": k, "label": v} for k, v in rooms.STATUSES],
                "inbox": str(inbox.relative_to(REPO)) if REPO in inbox.parents else str(inbox),
                "pieces": [{"id": it["id"], "source": it["source"]} for it in self.items() if it.get("art_file")]}

    def room(self, room_id: str) -> dict:
        r = rooms.get(rooms.load(self.rooms_root), room_id)
        if not r:
            raise ApiError(404, f"no room {room_id!r}")
        return rooms.public(r, self.rooms_root)

    def edit_room(self, room_id: str, body: dict) -> dict:
        with _ROOMS_LOCK:
            lib = rooms.load(self.rooms_root)
            r = rooms.get(lib, room_id)
            if not r:
                raise ApiError(404, f"no room {room_id!r}")
            try:
                new = rooms.update(r, body)
            except ValueError as e:
                raise ApiError(400, str(e))
            lib["rooms"] = [new if x["id"] == room_id else x for x in lib["rooms"]]
            rooms.save(lib, self.rooms_root)
        return rooms.public(new, self.rooms_root)

    def upload_room(self, data: bytes, query: dict) -> dict:
        """"Add a room": one photo as the request body; its name, licence and credit in the query."""
        q = {k: (v[0] if v else "") for k, v in query.items()}
        lic = q.get("licence") or None
        if lic is not None and lic not in rooms.LICENCES:
            raise ApiError(400, f"unknown licence {lic!r}")
        with _ROOMS_LOCK:
            try:
                room, added = rooms.import_upload(data, q.get("filename", ""), self.rooms_root, name=q.get("name", "")[:500],
                                                  licence=lic, credit=q.get("credit", "")[:500], note=q.get("note", "")[:500])
            except ValueError as e:
                raise ApiError(400, str(e))
        return dict(rooms.public(room, self.rooms_root), added=added)

    def _suggest_one(self, client, room_id: str) -> dict:
        r = rooms.get(rooms.load(self.rooms_root), room_id)
        if not r:
            raise ApiError(404, f"no room {room_id!r}")
        new = room_suggest.suggest(client, r, self.rooms_root, call=self.call)   # the slow part, outside the lock
        with _ROOMS_LOCK:                                  # save over the latest copy, keeping the owner's edits
            lib = rooms.load(self.rooms_root)
            cur = rooms.get(lib, room_id) or r
            keep = dict(cur, suggested=new["suggested"], updated_at=new["updated_at"])
            if new.get("named_by") == "suggestion" and room_suggest.named_from_file(cur):
                keep.update(name=new["name"], named_by="suggestion")
            lib["rooms"] = [keep if x["id"] == room_id else x for x in lib["rooms"]]
            rooms.save(lib, self.rooms_root)
        return keep

    def suggest_room(self, room_id: str) -> dict:
        """Ask again for one room's name, hanging area and width (the room page's Suggest button)."""
        try:
            return rooms.public(self._suggest_one(self._client(), room_id), self.rooms_root)
        except listing.ModelError as e:
            raise ApiError(502, f"couldn't get a suggestion: {e}")

    def suggest_rooms(self, body: dict) -> dict:
        """A name, hanging area and width for each room given, as a background job (after rooms are added)."""
        ids = body.get("rooms") if isinstance(body, dict) else None
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            raise ApiError(400, 'send {"rooms": ["room-…", …]}')
        lib = rooms.load(self.rooms_root)
        missing = [i for i in ids if not rooms.get(lib, i)]
        if missing:
            raise ApiError(404, f"no room {missing[0]!r}")
        client = self._client()

        def work(job):
            job["total"] = len(ids)
            for rid in ids:
                try:
                    r = self._suggest_one(client, rid)
                    job["cost_usd"] = round(job["cost_usd"] + (r["suggested"].get("cost_usd") or 0), 4)
                    job["results"].append({"id": rid, "name": r["name"]})
                except (listing.ModelError, ApiError, OSError) as e:
                    job["results"].append({"id": rid, "error": str(e)})
                job["done"] += 1
        return self._start(f"Suggest names and walls for {len(ids)} room(s)", work)

    def scan_rooms(self) -> dict:
        with _ROOMS_LOCK:
            added = rooms.scan_inbox(self.rooms_root)
        return {"added": [r["id"] for r in added], "rooms": self.rooms_doc()["rooms"]}

    def preview_room(self, room_id: str, body: dict) -> dict:
        """The room with one piece on its wall, for setting it up. Local only: not a listing image."""
        r = rooms.get(rooms.load(self.rooms_root), room_id)
        if not r:
            raise ApiError(404, f"no room {room_id!r}")
        if not r.get("wall") or not r.get("wall_width_cm"):
            raise ApiError(400, "mark the wall and say how wide it is first")
        pieces = [it for it in self.items() if it.get("art_file")]
        it = next((p for p in pieces if p["id"] == body.get("piece")), pieces[0] if pieces else None)
        if not it:
            raise ApiError(400, "no framed piece to preview with yet")
        art = Path(it["art_file"])
        rooms.render_view(r, self.rooms_root, art if art.is_absolute() else REPO / art, self._dimensions(it["id"]),
                          self.rooms_root / "previews" / f"{room_id}.jpg", recipe_id=rooms.recipe_of(it))
        return dict(self.room(room_id), preview_piece=it["id"])

    def photo_room(self, item_id: str, body: dict) -> dict:
        """Hang a piece in its room. {"room": id} chooses that room first; {"room": null} goes back to the
        automatic pick. Only a ready room can be chosen. {"scale": n | null} sizes this piece by hand in its
        room (null: its real size); {"centre": [x, y] | null} moves where art hangs in that room, for every
        piece (x and y are shares of the view; null: the middle of the wall)."""
        it = self.item(item_id)
        if not isinstance(body, dict) or set(body) - {"room", "scale", "centre"} or ("room" in body and len(body) > 1):
            raise ApiError(400, 'send {} to hang it, {"room": "room-…" | null} to change its room, or '
                                '{"scale": …, "centre": …} to size and place it')
        if not it.get("art_file"):
            raise ApiError(400, "this piece isn't cropped and framed yet")
        with _ROOMS_LOCK:
            lib = rooms.load(self.rooms_root)
            if "room" in body:
                rid = body["room"]
                if rid is not None:
                    r = rooms.get(lib, rid) if isinstance(rid, str) else None
                    if not r:
                        raise ApiError(404, f"no room {rid!r}")
                    if rooms.status(r) != "ready":
                        raise ApiError(400, f"{r['name']} isn't ready: record its licence and mark its wall first")
                rooms.save_choice(self.out, item_id, rid)
            dims = self._dimensions(item_id)
            room, _, _ = rooms.chosen(it, lib, self.out, dims)
            if not room:
                raise ApiError(400, "no room is ready yet: set one up on the Rooms page")
            try:
                if "scale" in body:
                    rooms.save_size(self.out, item_id, room["id"], body["scale"])
                if "centre" in body:
                    at = body["centre"]
                    if at is not None and not (isinstance(at, list) and len(at) == 2 and all(
                            isinstance(n, (int, float)) and not isinstance(n, bool) and 0 <= n <= 1 for n in at)):
                        raise ValueError("centre is [x, y], each between 0 and 1, or null")
                    hang = None if at is None else rooms.centre_on_wall(room, at)
                    if hang != room.get("hang"):
                        room = rooms.update(room, {"hang": hang})
                        lib["rooms"] = [room if r["id"] == room["id"] else r for r in lib["rooms"]]
                        rooms.save(lib, self.rooms_root)
                rooms.render_item(it, lib, self.rooms_root, self.out, dims, [room])
            except ValueError as e:
                raise ApiError(400, str(e))
        return self.photo(item_id)

    def render_all_rooms(self) -> dict:
        """Every piece that isn't rejected, in its own room, as a background job."""
        lib = rooms.load(self.rooms_root)
        if not rooms.ready(lib):
            raise ApiError(400, "no room is ready yet")
        decisions = self.decisions()
        todo = [it for it in self.items() if it.get("art_file") and decisions.get(it["id"], {}).get("decision") != "reject"]
        if not todo:
            raise ApiError(400, "no framed piece yet")

        def work(job):
            job["total"] = len(todo)
            for it in todo:
                try:
                    dims = self._dimensions(it["id"])
                    room, _, _ = rooms.chosen(it, lib, self.out, dims)
                    rooms.render_item(it, lib, self.rooms_root, self.out, dims, [room])
                except Exception as e:            # one bad file doesn't stop the batch
                    job["results"].append({"id": it["id"], "error": str(e)})
                job["done"] += 1
        return self._start(f"Hang {len(todo)} piece(s), each in its room", work)

    def decide_photo(self, item_id: str, body: dict) -> dict:
        """Accept, reject or rotate one photo, correct its corners, or change its note. Same file and rules
        as the image review page. Saving corners marks the photo corrected ("fix"); null corners go back to
        the outline the crop found."""
        it = self.item(item_id)
        if not isinstance(body, dict) or not body or set(body) - {"decision", "rotate", "note", "corners", "mat"}:
            raise ApiError(400, 'send any of {"decision": "accept"|"reject"|null, "rotate": 0|90|180|270, '
                                '"corners": [[x, y] ×4] | null, "mat": true|false, "note": "…"}')
        if "mat" in body and not isinstance(body["mat"], bool):
            raise ApiError(400, "mat is true (a white mat) or false (the frame against the artwork)")
        if "decision" in body and body["decision"] not in ("accept", "reject", None):
            raise ApiError(400, "decision is accept, reject or null (save corners to mark a photo corrected)")
        if "corners" in body:
            if it.get("kind") != "photo" or not it.get("photo_size"):
                raise ApiError(400, "only phone photos have corners to correct")
            if body["corners"] is not None:
                try:
                    body = dict(body, corners=stages.order_corners(body["corners"], it["photo_size"]))
                except ValueError as e:
                    raise ApiError(400, str(e))
        with _DECISIONS_LOCK:
            old = self.decisions()
            entry = dict(old.get(item_id, {"decision": None}))
            for k in ("decision", "rotate", "note"):
                if k in body:
                    entry[k] = body[k]
            if body.get("mat") is True:
                entry.pop("mat", None)
            elif body.get("mat") is False:
                entry["mat"] = False
            if "corners" in body:
                if body["corners"] is None:
                    entry.pop("corners", None)
                    if entry.get("decision") == "fix":
                        entry["decision"] = None
                else:
                    entry["corners"] = body["corners"]
                    if "decision" not in body:
                        entry["decision"] = "fix"
            new = dict(old, **{item_id: entry})
            try:
                clean = ri.validate_decisions(new)
            except ValueError as e:
                raise ApiError(400, str(e))
            clean = ri.stamp_changes(old, clean, brand.now())
            (self.out / "decisions.json").write_text(json.dumps(clean, indent=1))
        return next(r for r in self.photos()["photos"] if r["id"] == item_id)

    def apply_photos(self) -> dict:
        """Re-crop and re-frame every photo whose corners, rotation or mat changed, as a background job."""
        ids = ri.pending(self.decisions(), self.items())
        if not ids:
            raise ApiError(400, "nothing to apply")

        def work(job):
            job["total"] = len(ids)
            ri.build(self.source, self.out, only=ids, log=lambda *_: job.__setitem__("done", job["done"] + 1))
        return self._start(f"Apply {len(ids)} photo change(s)", work)

    # ------------------------------------------------------------ brand context
    def brand_doc(self) -> dict:
        return {"context": self.brand_ctx(), "history": brand.history(self.storefront, self.brand_root),
                "storefront": self.storefront_entry()}

    def save_brand(self, ctx: dict) -> dict:
        if ctx.get("storefront_id") != self.storefront:
            raise ApiError(400, "storefront_id does not match")
        current = self.brand_ctx()
        if current and ctx.get("version") != current["version"]:
            raise ApiError(409, f"the brand context changed (now v{current['version']}); reload and try again")
        try:
            return brand.save(ctx, OWNER, self.brand_root)
        except brand.BrandContextError as e:
            raise ApiError(400, str(e))

    def add_meaning(self, item_id: str, body: dict) -> dict:
        ctx = self.brand_ctx()
        if ctx is None:
            raise ApiError(400, "set up the brand context first")
        kind = body.get("scope")
        if kind not in ("artwork", "series", "catalog"):
            raise ApiError(400, "scope must be artwork, series or catalog")
        entry = self.store.listing(item_id)
        ref = {"artwork": item_id, "series": (body.get("series") or entry.get("series") or "").strip(), "catalog": None}[kind]
        if kind == "series" and not ref:
            raise ApiError(400, "name the series first")
        subject, meaning = (body.get("subject") or "").strip(), (body.get("meaning") or "").strip()
        if not subject or not meaning:
            raise ApiError(400, "say what it's about and what it means")
        ids = {m["id"] for m in ctx["meanings"]}
        n = len(ctx["meanings"]) + 1
        while f"mean-{n}" in ids:
            n += 1
        ctx["meanings"].append({"id": f"mean-{n}", "scope": {"kind": kind, "ref": ref}, "subject": subject[:200],
                                "meaning": meaning[:2000], "recorded_by": {"kind": "human", "id": OWNER["id"]},
                                "recorded_at": brand.now()})
        return self.save_brand(ctx)

    def decide(self, kind: str, entry_id: str, status: str, text=None) -> dict:
        ctx = self.brand_ctx()
        if ctx is None:
            raise ApiError(404, "no brand context")
        if status not in ("approved", "rejected", "proposed"):
            raise ApiError(400, "status must be approved, rejected or proposed")
        coll = {"lesson": "lessons", "example": "examples"}[kind]
        entry = next((x for x in ctx[coll] if x["id"] == entry_id), None)
        if entry is None:
            raise ApiError(404, f"no {kind} {entry_id!r}")
        entry["status"] = status
        if text and kind == "lesson":
            entry["text"] = text.strip()[:500]
        if kind == "lesson":
            entry["decided_at"] = brand.now()
        return self.save_brand(ctx)

    def setup(self, body: dict) -> dict:
        """The first-run question and interview: site kind, then a starting brand context."""
        kind = body.get("site_kind")
        if kind not in ("artist", "product"):
            raise ApiError(400, "Is this an artist site or a product site?")
        name = (body.get("name") or "").strip()
        if not name:
            raise ApiError(400, "a name is needed")
        if self.brand_ctx() is not None and not body.get("replace"):
            raise ApiError(409, "a brand context already exists; edit it on the Brand page")
        cats = [c for c in body.get("categories", []) if (c.get("name") or "").strip()]
        if not cats:
            raise ApiError(400, "add at least one " + ("kind of work" if kind == "artist" else "product line"))
        lines = lambda s: [x.strip() for x in (s or "").splitlines() if x.strip()]  # noqa: E731
        ctx = {
            "contract": "brand-context", "contract_version": 1, "storefront_id": self.storefront,
            "site_kind": kind, "version": 1, "updated_at": brand.now(), "updated_by": OWNER,
            "identity": {"name": name, "name_usage": (body.get("name_usage") or "").strip()
                         or "Third person; at most once in a long description; never in a short description."},
            "philosophy": (body.get("philosophy") or "").strip() or "(not written yet)",
            "categories": [{"id": re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-") or f"cat-{i}",
                            "name": c["name"].strip(), "description": (c.get("description") or "").strip(),
                            "writing_approach": (c.get("writing_approach") or "").strip()}
                           for i, c in enumerate(cats, 1)],
            "voice": {"tone": (body.get("tone") or "").strip() or "Warm, plain and specific.",
                      "do": lines(body.get("do")), "avoid": lines(body.get("avoid"))},
            "style_words": {"accept": lines(body.get("accept")), "reject": lines(body.get("reject"))},
            "meanings": [], "examples": [], "lessons": [],
            "watch_phrases": [{"phrase": p, "max_share": 0.05, "source": "owner"} for p in lines(body.get("phrases"))],
            "length": {"short_words": {"min": 18, "max": 35}, "collector_words": {"min": 85, "max": 135},
                       "short_chars_max": 200},
        }
        if (body.get("audience") or "").strip():
            ctx["identity"]["audience"] = body["audience"].strip()
        current = self.brand_ctx()
        if current:
            ctx["version"] = current["version"]
        try:
            saved = brand.save(ctx, OWNER, self.brand_root)
        except brand.BrandContextError as e:
            raise ApiError(400, str(e))
        self._record_site_kind(kind)
        return saved

    def _record_site_kind(self, kind: str):
        if not self.config.exists():
            return
        cfg = json.loads(self.config.read_text())
        for s in cfg.get("storefronts", []):
            if s["id"] == self.storefront:
                s["site_kind"] = kind
                s["brand_context"] = f"config/brand/{self.storefront}.local.json"
        self.config.write_text(json.dumps(cfg, indent=2) + "\n")

    # ------------------------------------------------------------ learning
    def learning_doc(self) -> dict:
        ctx = self.brand_ctx()
        edits = self.learn.edits()
        return {"stats": self.learn.stats(), "edits": list(reversed(edits))[:60],
                "repeated_removals": self.learn.repeated_removals(),
                "lessons": (ctx or {}).get("lessons", []), "examples": (ctx or {}).get("examples", []),
                "changed": len(self.learn.changed())}

    # ------------------------------------------------------------ jobs (calls to Claude)
    def _key(self) -> str:
        return onboarding.read_env(self.env_file).get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or ""

    def _client(self):
        if self.client_factory:
            return self.client_factory()
        key = self._key()
        if not key:
            raise ApiError(400, "ANTHROPIC_API_KEY isn't set in .env")
        import anthropic
        return anthropic.Anthropic(api_key=key)

    def job_list(self) -> list:
        return [dict(j, id=k) for k, j in list(self.jobs.items())[-10:]]

    def _start(self, label: str, fn) -> dict:
        with self._job_lock:
            if any(j["running"] for j in self.jobs.values()):
                raise ApiError(409, "another job is running; wait for it to finish")
            jid = uuid.uuid4().hex[:10]
            self.jobs[jid] = {"label": label, "running": True, "done": 0, "total": 0, "error": None,
                              "cost_usd": 0.0, "results": []}
        job = self.jobs[jid]

        def run():
            try:
                fn(job)
            except Exception as e:                # report, don't crash the server
                job["error"] = f"{type(e).__name__}: {e}"
            finally:
                job["finished_at"] = time.time()
                job["running"] = False
        threading.Thread(target=run, daemon=True).start()
        return {"job": jid}

    def draft(self, ids: list, label: str) -> dict:
        client = self._client()
        from packages.policy import load_product_types
        product_types, tags, ctx = load_product_types(), service.store_tags(self.storefront), self.brand_ctx()
        items = {it["id"]: it for it in self.items()}
        todo = [items[i] for i in ids if i in items and items[i].get("art_file")]
        locked = [i for i in ids if self.store.listing(i).get("approved")]
        if locked:
            raise ApiError(409, f"approved copy is locked; unlock first: {', '.join(locked)}")
        if not todo:
            raise ApiError(400, "nothing to draft")

        def work(job):
            job["total"] = len(todo)
            for it in todo:
                try:
                    rec = service.draft_item(client, it, store=self.store, ctx=ctx, product_types=product_types,
                                             tags=tags, learn=self.learn, call=self.call,
                                             reference=brand.reference_text(self.storefront, self.brand_root))
                    job["cost_usd"] = round(job["cost_usd"] + rec["cost_usd"], 4)
                    job["results"].append({"id": it["id"], "title": rec["draft"]["product"]["title"]["value"]})
                except listing.ModelError as e:
                    job["results"].append({"id": it["id"], "error": str(e)})
                job["done"] += 1
        return self._start(label, work)

    def draft_pending(self, limit: int) -> dict:
        decisions, listings = self.decisions(), self.store.listings()
        ids = [it["id"] for it in self.items() if it.get("art_file")
               and decisions.get(it["id"], {}).get("decision") != "reject"
               and not listings.get(it["id"], {}).get("approved") and not self.store.draft(it["id"])]
        return self.draft(ids[:max(1, min(limit, 60))], f"Draft {min(len(ids), limit)} new piece(s)")

    def draft_selected(self, body: dict) -> dict:
        """Draft the pieces the owner ticked on the Listings page (B-081). Only pieces not drafted yet."""
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list) or not ids or len(ids) > 60 or not all(isinstance(i, str) for i in ids):
            raise ApiError(400, 'send {"ids": ["…"]}: between 1 and 60 pieces')
        ids = list(dict.fromkeys(ids))
        decisions, known = self.decisions(), {it["id"]: it for it in self.items()}
        bad = [i for i in ids if i not in known or not known[i].get("art_file")
               or decisions.get(i, {}).get("decision") == "reject" or self.store.draft(i)]
        if bad:
            raise ApiError(400, "these can't be drafted from here (already drafted, rejected or not framed): " + ", ".join(bad))
        return self.draft(ids, f"Draft {len(ids)} selected piece(s)")

    def distil(self) -> dict:
        client = self._client()

        def work(job):
            job["total"] = 1
            res = service.distil_lessons(client, self.storefront, {"kind": "agent", "id": "learning-loop"},
                                         learn=self.learn, call=self.call, brand_root=self.brand_root)
            job["cost_usd"] = res["cost_usd"]
            job["results"].append(res)
            job["done"] = 1
        return self._start("Learn from edits", work)


# ---------------------------------------------------------------- HTTP

ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return deco


@route("GET", "/api/state")
def _state(app, m, body): return app.state()
@route("GET", r"/api/items/([\w.-]+)")
def _detail(app, m, body): return app.detail(m.group(1))
@route("GET", "/api/sizes/from-names")
def _name_sizes(app, m, body): return app.name_sizes()
@route("POST", "/api/sizes/from-names")
def _save_name_sizes(app, m, body): return app.save_name_sizes(body)
@route("PUT", r"/api/items/([\w.-]+)/listing")
def _listing(app, m, body): return app.update_listing(m.group(1), body)
@route("PUT", r"/api/items/([\w.-]+)/copy")
def _copy(app, m, body): return app.save_copy(m.group(1), body)
@route("POST", r"/api/items/([\w.-]+)/draft")
def _draft(app, m, body): return app.draft([m.group(1)], f"Redraft {m.group(1)}")
@route("POST", r"/api/items/([\w.-]+)/approve")
def _approve(app, m, body): return app.approve(m.group(1))
@route("GET", r"/api/items/([\w.-]+)/storefront")
def _storefront(app, m, body): return app.storefront_preview(m.group(1))
@route("POST", r"/api/items/([\w.-]+)/storefront/approve")
def _storefront_approve(app, m, body): return app.approve_storefront(m.group(1), body)
@route("POST", r"/api/items/([\w.-]+)/unlock")
def _unlock(app, m, body): return app.unlock(m.group(1))
@route("POST", r"/api/items/([\w.-]+)/meaning")
def _meaning(app, m, body): return app.add_meaning(m.group(1), body)
@route("POST", "/api/draft-selected")
def _draft_selected(app, m, body): return app.draft_selected(body)
@route("POST", "/api/draft-pending")
def _pending(app, m, body): return app.draft_pending(int(body.get("limit", 5)))
@route("POST", r"/api/items/([\w.-]+)/publish")
def _publish(app, m, body): return app.publish(m.group(1), body)
@route("POST", r"/api/items/([\w.-]+)/publish/recheck")
def _publish_recheck(app, m, body): return app.publish_recheck(m.group(1))
@route("GET", "/api/activity")
def _activity(app, m, body): return app.activity()
@route("GET", "/api/publishing/queue")
def _publish_queue(app, m, body): return app.publish_queue()
@route("POST", "/api/publishing/publish")
def _publish_many(app, m, body): return app.publish_many(body)
@route("PUT", "/api/publishing/kill-switch")
def _kill_switch(app, m, body): return app.kill_switch(body)
@route("GET", "/api/home")
def _home(app, m, body): return app.home()
@route("GET", "/api/inbox")
def _inbox(app, m, body): return app.inbox_status()
@route("GET", "/api/onboarding")
def _onboarding(app, m, body): return app.onboarding_doc()
@route("PUT", "/api/onboarding/store")
def _onboarding_store(app, m, body): return app.onboarding_store(body)
@route("POST", "/api/onboarding/login")
def _onboarding_login(app, m, body): return app.onboarding_login(body)
@route("POST", "/api/onboarding/check")
def _onboarding_check(app, m, body): return app.onboarding_check()
@route("PUT", "/api/onboarding/mapping")
def _onboarding_mapping(app, m, body): return app.onboarding_mapping(body)
@route("POST", "/api/onboarding/key")
def _onboarding_key(app, m, body): return app.onboarding_key(body)
@route("POST", "/api/intake/scan")
def _intake_scan(app, m, body): return app.scan_inbox()
@route("POST", "/api/catalog/refresh")
def _catalog_refresh(app, m, body): return app.refresh_catalog()
@route("PUT", r"/api/items/([\w.-]+)/catalog-match")
def _catalog_match(app, m, body): return app.answer_match(m.group(1), body)
@route("GET", "/api/photos")
def _photos(app, m, body): return app.photos()
@route("GET", r"/api/photos/([\w.-]+)")
def _photo_detail(app, m, body): return app.photo(m.group(1))
@route("PUT", r"/api/photos/([\w.-]+)")
def _photo(app, m, body): return app.decide_photo(m.group(1), body)
@route("POST", "/api/photos/apply")
def _apply(app, m, body): return app.apply_photos()
@route("POST", r"/api/photos/([\w.-]+)/room")
def _photo_room(app, m, body): return app.photo_room(m.group(1), body)
@route("GET", "/api/rooms")
def _rooms(app, m, body): return app.rooms_doc()
@route("POST", "/api/rooms/scan")
def _rooms_scan(app, m, body): return app.scan_rooms()
@route("POST", "/api/rooms/suggest")
def _rooms_suggest(app, m, body): return app.suggest_rooms(body)
@route("POST", r"/api/rooms/(room-[\w.-]+)/suggest")
def _room_suggest(app, m, body): return app.suggest_room(m.group(1))
@route("POST", "/api/rooms/render")
def _rooms_render(app, m, body): return app.render_all_rooms()
@route("GET", r"/api/rooms/(room-[\w.-]+)")
def _room(app, m, body): return app.room(m.group(1))
@route("PUT", r"/api/rooms/(room-[\w.-]+)")
def _room_put(app, m, body): return app.edit_room(m.group(1), body)
@route("POST", r"/api/rooms/(room-[\w.-]+)/preview")
def _room_preview(app, m, body): return app.preview_room(m.group(1), body)
@route("GET", "/api/brand")
def _brand(app, m, body): return app.brand_doc()
@route("PUT", "/api/brand")
def _brand_put(app, m, body): return app.save_brand(body)
@route("POST", "/api/setup")
def _setup(app, m, body): return app.setup(body)
@route("POST", r"/api/brand/(lesson|example)s/([\w.-]+)")
def _decide(app, m, body): return app.decide(m.group(1), m.group(2), body.get("status"), body.get("text"))
@route("GET", "/api/learning")
def _learning(app, m, body): return app.learning_doc()
@route("POST", "/api/learning/distil")
def _distil(app, m, body): return app.distil()
@route("GET", r"/api/jobs/(\w+)")
def _job(app, m, body):
    j = app.jobs.get(m.group(1))
    if not j:
        raise ApiError(404, "no such job")
    return dict(j, id=m.group(1))


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, data: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode())

        def _api(self, method):
            path = urlparse(self.path).path
            if method != "GET" and self.headers.get("X-Commerce-OS") != "1":
                return self._json(403, {"error": "missing X-Commerce-OS header"})
            length = int(self.headers.get("Content-Length") or 0)
            if method == "POST" and path == "/api/rooms/upload":     # a photo, not JSON
                if length > rooms.MAX_UPLOAD:
                    return self._json(413, {"error": f"too large: at most {rooms.MAX_UPLOAD // 1_000_000} MB"})
                try:
                    return self._json(200, app.upload_room(self.rfile.read(length), parse_qs(urlparse(self.path).query)))
                except ApiError as e:
                    return self._json(e.code, {"error": str(e)})
                except Exception as e:
                    return self._json(500, {"error": f"{type(e).__name__}: {e}"})
            if length > MAX_BODY:
                return self._json(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except json.JSONDecodeError:
                return self._json(400, {"error": "invalid JSON"})
            for meth, pat, fn in ROUTES:
                m = pat.match(path)
                if m and meth == method:
                    try:
                        return self._json(200, fn(app, m, body))
                    except ApiError as e:
                        return self._json(e.code, {"error": str(e)})
                    except Exception as e:        # never crash the server
                        return self._json(500, {"error": f"{type(e).__name__}: {e}"})
            return self._json(404, {"error": "not found"})

        def _file(self, root: Path, rel: str):
            target = (root / rel).resolve()
            if root.resolve() not in target.parents or not target.is_file():
                return self._json(404, {"error": "not found"})
            self._send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path.startswith("/api/"):
                return self._api("GET")
            if path.startswith("/img/"):
                return self._file(app.out / "img", path[len("/img/"):])
            if path.startswith("/rooms/files/") or path.startswith("/rooms/previews/"):
                return self._file(app.rooms_root, path[len("/rooms/"):])   # never rooms.json or the inbox
            if not DIST.exists():
                return self._send(200, b"Dashboard not built. Run: cd apps/review-dashboard && npm install && npm run build",
                                  "text/plain")
            rel = path.lstrip("/") or "index.html"
            if not (DIST / rel).is_file():
                rel = "index.html"                # client-side routes
            return self._file(DIST, rel)

        def do_POST(self):
            return self._api("POST")

        def do_PUT(self):
            return self._api("PUT")

        def log_message(self, fmt, *args):
            line = fmt % args
            if "/api/" in line and '" 200 ' not in line:
                sys.stderr.write(line + "\n")
    return Handler


def make_server(app: App, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), make_handler(app))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--storefront", default="storefront-a")
    args = ap.parse_args(argv)
    httpd = make_server(App(storefront=args.storefront), args.port)
    print(f"Review dashboard: http://{HOST}:{args.port}/  (only this computer can open it; Ctrl+C to stop)")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
