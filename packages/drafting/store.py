"""Local listing state: drafts with revisions, the reviewer's edits, supplied facts, approval (B-056).

A stand-in for the operational database until the workflow service exists. Everything is under
`.commerce-os/review/` (gitignored):

    drafts/<item>.json              the current draft record (model output + canonical draft)
    drafts/history/<item>.r<N>.json every earlier revision, never rewritten
    listings.json                   per item: facts, series, note, edits, chosen title, approval

Approved copy is locked. A redraft of an approved item is refused unless the reviewer unlocks it, which
clears the approval (and is itself recorded). Publishing is not here: approval of copy is Gate 1 input,
not a storefront write.
"""
import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

from packages.drafting import brand

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / ".commerce-os" / "review"
COPY_FIELDS = ("title", "short_description", "collector_description")
LIST_FIELDS = ("store_tags", "search_keywords")
FACT_FIELDS = ("edition", "medium", "dimensions")
EDITIONS = ("original", "print", "both")
_LOCK = threading.RLock()


class LockedError(Exception):
    """The copy is approved; unlock it before redrafting or editing."""


class Store:
    def __init__(self, out: Path = OUT):
        self.out = Path(out)
        self.drafts = self.out / "drafts"

    # ------------------------------------------------------------ files
    def _listings_path(self) -> Path:
        return self.out / "listings.json"

    def listings(self) -> Dict[str, dict]:
        p = self._listings_path()
        return json.loads(p.read_text()) if p.exists() else {}

    def _write_listings(self, data: dict):
        self.out.mkdir(parents=True, exist_ok=True)
        tmp = self._listings_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self._listings_path())

    def listing(self, item: str) -> dict:
        return self.listings().get(item, {})

    def draft(self, item: str) -> Optional[dict]:
        p = self.drafts / f"{item}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def all_drafts(self) -> Dict[str, dict]:
        if not self.drafts.exists():
            return {}
        return {p.stem: json.loads(p.read_text()) for p in sorted(self.drafts.glob("*.json"))}

    def revisions(self, item: str) -> List[int]:
        hist = self.drafts / "history"
        return sorted(int(p.stem.rsplit(".r", 1)[1]) for p in hist.glob(f"{item}.r*.json")) if hist.exists() else []

    def next_revision(self, item: str) -> int:
        current = self.draft(item)
        return (current["draft"]["revision"] + 1) if current else 1

    def save_draft(self, item: str, record: dict):
        """Write a new revision; the previous one goes to history. Refused while the copy is approved."""
        with _LOCK:
            if self.listing(item).get("approved"):
                raise LockedError(f"{item}: the copy is approved; unlock it to redraft")
            self.drafts.mkdir(parents=True, exist_ok=True)
            current = self.draft(item)
            if current:
                hist = self.drafts / "history"
                hist.mkdir(exist_ok=True)
                archived = hist / f"{item}.r{current['draft']['revision']}.json"
                if not archived.exists():
                    archived.write_text(json.dumps(current, indent=1))
            (self.drafts / f"{item}.json").write_text(json.dumps(record, indent=1))
            # a fresh draft starts with no edits on top of it
            data = self.listings()
            entry = data.setdefault(item, {})
            entry.pop("edits", None)
            entry.pop("chosen_title", None)
            self._write_listings(data)

    # ------------------------------------------------------------ the reviewer's input
    def update(self, item: str, *, facts=None, series=None, note=None, edits=None, chosen_title=None) -> dict:
        with _LOCK:
            data = self.listings()
            entry = data.setdefault(item, {})
            if entry.get("approved") and (edits is not None or chosen_title is not None):
                raise LockedError(f"{item}: the copy is approved; unlock it to edit")
            if facts is not None:
                clean = {}
                for k, v in facts.items():
                    if k not in FACT_FIELDS:
                        raise ValueError(f"unknown fact {k!r}")
                    v = (v or "").strip()
                    if k == "edition" and v and v not in EDITIONS:
                        raise ValueError(f"edition must be one of {EDITIONS}")
                    if v:
                        clean[k] = v[:200]
                entry["facts"] = clean
            if series is not None:
                entry["series"] = series.strip()[:120]
            if note is not None:
                entry["note"] = note.strip()[:4000]
            if edits is not None:
                entry["edits"] = {k: self.clean_field(k, v) for k, v in edits.items()}
            if chosen_title is not None:
                entry["chosen_title"] = str(chosen_title)[:200]
            self._write_listings(data)
            return entry

    @staticmethod
    def clean_field(k: str, v):
        if k in COPY_FIELDS:
            return str(v)[:5000]
        if k in LIST_FIELDS:
            if not isinstance(v, list):
                raise ValueError(f"{k} must be a list")
            return [str(x).strip()[:60] for x in v if str(x).strip()][:30]
        raise ValueError(f"unknown field {k!r}")

    def set_fields(self, item: str, fields: dict) -> dict:
        """Save some fields and leave the others alone (one section's Save button, or /listing-edit).

        A value of None discards the edit and goes back to the draft. A value equal to the draft is
        stored as no edit, so the learning loop only sees real changes. Saving a title replaces any
        chosen title option. Refused while the copy is approved, or before there is a draft.
        """
        with _LOCK:
            record = self.draft(item)
            if not record:
                raise ValueError(f"{item}: no draft yet")
            data = self.listings()
            entry = data.setdefault(item, {})
            if entry.get("approved"):
                raise LockedError(f"{item}: the copy is approved; unlock it to edit")
            proposed = self.proposed(record)
            edits = dict(entry.get("edits", {}))
            for k, v in fields.items():
                if v is None:
                    self.clean_field(k, "" if k in COPY_FIELDS else [])  # validates the name
                    edits.pop(k, None)
                else:
                    v = self.clean_field(k, v)
                    if k == "title" and not v.strip():
                        raise ValueError("the title can't be empty")
                    if v == proposed[k]:
                        edits.pop(k, None)
                    else:
                        edits[k] = v
                if k == "title":
                    entry.pop("chosen_title", None)
            if edits:
                entry["edits"] = edits
            else:
                entry.pop("edits", None)
            self._write_listings(data)
            return entry

    # ------------------------------------------------------------ what the reviewer sees
    @staticmethod
    def proposed(record: dict) -> dict:
        d = record["draft"]
        a = d["product"]["attributes"]
        return {"title": d["product"]["title"]["value"],
                "short_description": a["short_description"]["value"],
                "collector_description": d["product"]["description"]["value"],
                "store_tags": a["suggested_tags"]["value"],
                "search_keywords": a.get("search_keywords", {}).get("value") or []}

    def effective(self, item: str, record: Optional[dict] = None) -> Optional[dict]:
        """The copy as it stands: approved copy, else the draft with the reviewer's edits on top."""
        entry = self.listing(item)
        if entry.get("approved"):
            return dict(entry["approved"]["copy"])
        record = record or self.draft(item)
        if not record:
            return None
        copy = self.proposed(record)
        if entry.get("chosen_title"):
            copy["title"] = entry["chosen_title"]
        copy.update(entry.get("edits", {}))
        return copy

    def corpus(self, exclude: Optional[str] = None) -> List[dict]:
        """Every other listing's current copy, for repetition checks and catalog memory."""
        listings = self.listings()
        out = []
        ids = set(self.all_drafts()) | {k for k, v in listings.items() if v.get("approved")}
        for item in sorted(ids):
            if item == exclude:
                continue
            copy = self.effective(item)
            if copy:
                out.append(dict(copy, item=item, approved=bool(listings.get(item, {}).get("approved"))))
        return out

    # ------------------------------------------------------------ approval
    def approve(self, item: str, actor: str) -> dict:
        """Lock the current copy. Returns the approval and the edit pairs (proposed vs final) for learning."""
        with _LOCK:
            record = self.draft(item)
            if not record:
                raise ValueError(f"{item}: no draft to approve")
            data = self.listings()
            entry = data.setdefault(item, {})
            if entry.get("approved"):
                raise LockedError(f"{item}: already approved")
            final = self.effective(item, record)
            proposed = self.proposed(record)
            approval = {"at": brand.now(), "by": actor, "revision": record["draft"]["revision"], "copy": final,
                        "brand_context": record["draft"]["policy_versions"].get("brand_context"),
                        "prompt": record["draft"]["policy_versions"].get("prompt")}
            entry["approved"] = approval
            self._write_listings(data)
            return {"approval": approval, "proposed": proposed, "final": final, "record": record}

    def unlock(self, item: str, actor: str) -> dict:
        with _LOCK:
            data = self.listings()
            entry = data.setdefault(item, {})
            if not entry.get("approved"):
                return entry
            entry.setdefault("unlocked", []).append({"at": brand.now(), "by": actor,
                                                     "revision": entry["approved"]["revision"]})
            # keep the approved copy as the starting point for further edits
            entry["edits"] = {k: v for k, v in entry["approved"]["copy"].items() if k in COPY_FIELDS + LIST_FIELDS}
            entry.pop("approved")
            self._write_listings(data)
            return entry
