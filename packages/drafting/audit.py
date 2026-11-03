"""Each listing's audit trail (PRD §17, AC-12): an append-only log, one file per listing, never rewritten.

    .commerce-os/audit/<item>.jsonl      one JSON event per line: {"at", "event", "label", "by", ...}

The timeline a reviewer sees joins these events with what is already recorded elsewhere and never
copied here (the photo decision, each draft revision, copy approvals and unlocks), so the trail reads
source photo → draft → human decision → exact change set → approval, in order.
"""
import json
import threading
from pathlib import Path
from typing import List, Optional

from packages.drafting import brand

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / ".commerce-os" / "audit"
_LOCK = threading.Lock()


class Audit:
    def __init__(self, root: Path = AUDIT):
        self.root = Path(root)

    def _path(self, item: str) -> Path:
        if not item or "/" in item or item.startswith("."):
            raise ValueError(f"bad item id {item!r}")
        return self.root / f"{item}.jsonl"

    def append(self, item: str, event: str, label: str, by: str = "owner", **data) -> dict:
        rec = {"at": brand.now(), "event": event, "label": label, "by": by, **data}
        with _LOCK:
            self.root.mkdir(parents=True, exist_ok=True)
            with self._path(item).open("a") as f:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec

    def events(self, item: str) -> List[dict]:
        p = self._path(item)
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def timeline(item: str, audit: Audit, *, decision: Optional[dict] = None, drafts: List[dict] = (),
             entry: Optional[dict] = None) -> List[dict]:
    """Everything that happened to a listing, oldest first. Undated older records sort first, marked."""
    out = []
    if decision and decision.get("decision"):
        word = {"accept": "Crop accepted", "reject": "Photo rejected", "fix": "Corners corrected"}.get(decision["decision"],
                                                                                                    decision["decision"])
        out.append({"at": decision.get("decided_at"), "event": "photo_decided", "label": word, "by": "owner"})
    for d in drafts:
        out.append({"at": d.get("drafted_at"), "event": "drafted", "by": "commerce-os",
                    "label": f"Drafted revision {d['draft']['revision']} ({d.get('model', 'model')})"})
    entry = entry or {}
    for u in entry.get("unlocked", []):
        out.append({"at": u.get("at"), "event": "copy_unlocked", "label": f"Copy unlocked (revision {u.get('revision')})",
                    "by": u.get("by", "owner")})
    if entry.get("approved"):
        a = entry["approved"]
        out.append({"at": a.get("at"), "event": "copy_approved", "label": f"Copy approved (revision {a.get('revision')})",
                    "by": a.get("by", "owner")})
    out += audit.events(item)
    return sorted(out, key=lambda e: (e.get("at") is not None, e.get("at") or ""))
