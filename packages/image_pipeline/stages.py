"""Where each photo is in the pipeline, and when it got there (B-062).

A photo moves from the source folder, through cropping and framing, to the owner's review (accept,
correct the corners, rotate, or reject), then to a listing draft and approved copy. This module reads
the local files those steps leave behind and returns, per photo, its current stage and a timeline of
dated events. Pure: no network, no image processing, and it writes nothing.
"""
import datetime
from pathlib import Path
from typing import Dict, List, Optional

# In pipeline order; `stage()` picks the first that applies, most urgent first.
STAGES = [
    ("to-review", "To review"),          # a phone photo nobody has accepted or corrected yet, or a failed one
    ("not-applied", "Not applied"),      # corners or rotation saved but not re-cropped yet
    ("ready", "Ready to draft"),
    ("drafted", "Drafted"),
    ("approved", "Copy approved"),
    ("rejected", "Rejected"),
]


def _mtime(path: Optional[Path]) -> Optional[str]:
    if path is None or not path.exists():
        return None
    t = datetime.datetime.utcfromtimestamp(path.stat().st_mtime)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def stage(item: dict, decision: dict, pending: bool, drafted: bool, approved: bool) -> str:
    d = decision.get("decision")
    if d == "reject":
        return "rejected"
    if pending:
        return "not-applied"
    reviewed = d in ("accept", "fix") or (item.get("kind") == "artwork" and item.get("status") != "error")
    if not reviewed or not item.get("art_file"):
        return "to-review"
    if approved:
        return "approved"
    return "drafted" if drafted else "ready"


def timeline(item: dict, decision: dict, draft: Optional[dict], listing: dict, source_dir: Path,
             out: Path) -> List[dict]:
    """Dated events, oldest first. A time is None when the step happened before it was recorded."""
    events = [{"event": "added", "label": "Added", "at": _mtime(Path(source_dir) / item["source"])}]
    processed = item.get("processed_at")
    if not processed and item.get("framed"):          # built before processing times were recorded
        processed = _mtime(Path(out) / item["framed"])
    if item.get("error"):
        events.append({"event": "failed", "label": "Couldn't process", "at": processed})
    else:
        events.append({"event": "processed", "label": "Cropped and framed" if item.get("kind") == "photo"
                       else "Framed", "at": processed})
    labels = {"accept": "Accepted", "fix": "Corners corrected", "reject": "Rejected"}
    if decision.get("decision") in labels:
        events.append({"event": decision["decision"], "label": labels[decision["decision"]],
                       "at": decision.get("decided_at")})
    elif decision.get("rotate") and decision.get("decided_at"):
        events.append({"event": "rotate", "label": f"Rotated {decision['rotate']}°", "at": decision["decided_at"]})
    if draft:
        events.append({"event": "drafted", "label": f"Drafted (r{draft['draft']['revision']})",
                       "at": draft.get("drafted_at")})
    if listing.get("approved"):
        events.append({"event": "approved", "label": "Copy approved", "at": listing["approved"].get("at")})
    return events


def photo_rows(items: List[dict], decisions: Dict[str, dict], drafts: Dict[str, dict], listings: Dict[str, dict],
               pending_ids: set, source_dir: Path, out: Path) -> List[dict]:
    rows = []
    for it in items:
        d, rec, entry = decisions.get(it["id"], {}), drafts.get(it["id"]), listings.get(it["id"], {})
        events = timeline(it, d, rec, entry, source_dir, out)
        crop = it.get("crop") or {}
        rows.append({
            "id": it["id"], "source": it["source"], "kind": it["kind"],
            "image": it.get("cropped") or it.get("original") or it.get("framed"),
            "photo": it.get("photo"), "framed": it.get("framed"),
            "stage": stage(it, d, it["id"] in pending_ids, bool(rec), bool(entry.get("approved"))),
            "decision": d.get("decision"), "rotate": d.get("rotate", 0), "note": d.get("note", ""),
            "crop_flagged": it.get("kind") == "photo" and not crop.get("ok") and crop.get("method") != "manual",
            "crop_reasons": crop.get("reasons") or [], "error": it.get("error"),
            "events": events, "updated_at": max((e["at"] for e in events if e["at"]), default=None),
        })
    return rows


def order_corners(points: List[List[float]], size: List[int]) -> List[List[float]]:
    """Four corners in the order the crop expects (top-left, top-right, bottom-right, bottom-left), whatever
    order the handles were dragged into, clamped to the photo and rounded to 0.1 px. Raises ValueError for
    anything that isn't four points enclosing a real area (at least 1% of the photo)."""
    import math
    if not (isinstance(points, list) and len(points) == 4 and all(
            isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                                 for v in p) for p in points)):
        raise ValueError("corners are four [x, y] points")
    w, h = size
    pts = [[min(max(float(x), 0.0), float(w)), min(max(float(y), 0.0), float(h))] for x, y in points]
    cx, cy = sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4
    ring = sorted(pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    start = ring.index(min(ring, key=lambda p: p[0] + p[1]))
    ordered = [ring[(start + k) % 4] for k in range(4)]
    area = abs(sum(ordered[i][0] * ordered[(i + 1) % 4][1] - ordered[(i + 1) % 4][0] * ordered[i][1]
                   for i in range(4))) / 2
    if area < 0.01 * w * h:
        raise ValueError("the corners don't enclose the artwork")
    return [[round(x, 1), round(y, 1)] for x, y in ordered]


def photo_detail(item: dict, row: dict, decision: dict, neighbours: List[Optional[str]]) -> dict:
    """Everything the photo page needs: the original, the outline found, the corners you saved, and the results."""
    crop = item.get("crop") or {}
    v = item.get("processed_at") or ""
    bust = lambda p: f"{p}?v={v}" if p and v else p  # noqa: E731  re-cropped files keep their names
    return dict(row, **{
        "photo": bust(item.get("photo")), "photo_size": item.get("photo_size"),
        "photo_preview_size": item.get("photo_preview_size"),
        "cropped": bust(item.get("cropped")), "framed": bust(item.get("framed")), "original": bust(item.get("original")),
        "image": bust(row.get("image")), "art_size": item.get("art_size"),
        "detected": {"corners": crop.get("corners"), "method": crop.get("method"), "ok": crop.get("ok"),
                     "reasons": crop.get("reasons") or []},
        "corners": decision.get("corners"),
        "applied": dict({"corners": None, "rotate": 0, "mat": True}, **(item.get("applied") or {})),
        "mat": decision.get("mat", True),
        "prev": neighbours[0], "next": neighbours[1],
    })
