#!/usr/bin/env python3
"""A local page for reviewing image conversions: crop outlines, crops and framed listing images.

Usage (from the repository root, with the project environment):
    .venv/bin/python scripts/review_images.py build [SOURCE_DIR]   process every image, write the page
    .venv/bin/python scripts/review_images.py serve [--port 8765]  open http://127.0.0.1:8765
    .venv/bin/python scripts/review_images.py apply                re-crop/rotate what you changed
                                                                   (the page's "Apply my changes" does the same)

SOURCE_DIR defaults to discovery/raw/. Photos (phone shots: IMG_*) are cropped and straightened first;
files that are already cropped are framed directly. Everything is written under .commerce-os/review/
(gitignored). Originals are never modified.

The page is served only on 127.0.0.1. Your decisions (accept, reject, corrected corners, rotation, notes)
save to .commerce-os/review/decisions.json as you go; "Apply my changes" re-crops and re-frames them. Accepting here is a local review aid: it isn't
an approval in the operational database (Gate 1), which comes with the review dashboard.
"""
import argparse
import hashlib
import html
import json
import re
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT = REPO / ".commerce-os" / "review"
DEFAULT_SOURCE = REPO / "discovery" / "raw"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}
PHOTO_PATTERN = re.compile(r"^IMG_\d+", re.I)
DECISIONS = "decisions.json"
THUMB_PX = 700
ROTATIONS = (0, 90, 180, 270)   # clockwise, applied after cropping and before framing


def slug(name: str) -> str:
    """A stable, URL-safe id for a source file."""
    base = re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-")[:48]
    return f"{base}-{hashlib.sha1(name.encode()).hexdigest()[:6]}"


def is_photo(name: str) -> bool:
    """Phone photos need cropping first; other files are treated as already cropped artwork."""
    return bool(PHOTO_PATTERN.match(Path(name).name))


def list_sources(source_dir: Path) -> list:
    return sorted(p for p in Path(source_dir).iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXT and not p.name.startswith("."))


def load_decisions(out: Path = OUT) -> dict:
    p = out / DECISIONS
    return json.loads(p.read_text()) if p.exists() else {}


def validate_decisions(data) -> dict:
    """Accept only the shape the page sends: {id: {decision, corners?, rotate?, note?}}."""
    if not isinstance(data, dict):
        raise ValueError("decisions must be an object")
    clean = {}
    for key, d in data.items():
        if not re.fullmatch(r"[a-z0-9-]{1,64}", str(key)) or not isinstance(d, dict):
            raise ValueError(f"bad decision entry {key!r}")
        decision = d.get("decision")
        if decision not in ("accept", "reject", "fix", None):
            raise ValueError(f"bad decision {decision!r}")
        entry = {"decision": decision}
        if d.get("corners") is not None:
            c = d["corners"]
            if not (isinstance(c, list) and len(c) == 4 and all(
                    isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p) for p in c)):
                raise ValueError(f"bad corners for {key}")
            entry["corners"] = [[float(x), float(y)] for x, y in c]
        if d.get("rotate"):
            if d["rotate"] not in ROTATIONS:
                raise ValueError(f"bad rotation for {key}")
            entry["rotate"] = int(d["rotate"])
        if d.get("note"):
            entry["note"] = str(d["note"])[:1000]
        clean[key] = entry
    return clean


# ---------------------------------------------------------------- build

def _thumb(src: Path, dst: Path, px: int = THUMB_PX):
    from PIL import Image
    im = Image.open(src).convert("RGB")
    im.thumbnail((px, px))
    im.save(dst, "JPEG", quality=85)


def _rotate(src: Path, dst: Path, degrees: int) -> Path:
    """Turn the artwork upright (clockwise degrees). Writes a new file; `src` is untouched."""
    from PIL import Image
    with Image.open(src) as im:
        im.convert("RGB").rotate(-degrees, expand=True).save(dst, "PNG")
    return dst


def process(source: Path, out: Path, corners=None, rotate: int = 0) -> dict:
    """Crop (photos), rotate if asked, and frame one source. Returns the page's record for it."""
    from PIL import Image
    from packages.image_pipeline import crop, framing
    img = out / "img"
    img.mkdir(parents=True, exist_ok=True)
    sid = slug(source.name)
    item = {"id": sid, "source": source.name, "kind": "photo" if is_photo(source.name) else "artwork"}
    art_path = source
    if item["kind"] == "photo":
        photo = crop.open_photo(source)
        item["photo_size"] = list(photo.size)
        record = crop.crop_artwork(source, img / sid, corners=corners)
        item["crop"] = {k: record.get(k) for k in ("recipe", "recipe_version", "needs_review", "reason")}
        preview = img / f"{sid}.photo.jpg"
        p = photo.copy()
        p.thumbnail((1400, 1400))
        p.save(preview, "JPEG", quality=85)
        item["photo"] = preview.relative_to(out).as_posix()
        item["photo_preview_size"] = list(p.size)
        if record.get("output"):
            prop = record["proposal"]
            item["crop"].update({"method": prop["method"], "ok": prop["check"]["ok"],
                                 "reasons": prop["check"]["reasons"], "corners": prop["corners"]})
            art_path = Path(record["output"])
            _thumb(art_path, img / f"{sid}.crop.jpg")
            item["cropped"] = f"img/{sid}.crop.jpg"
        else:
            item["crop"].update({"method": None, "ok": False, "reasons": [record.get("reason", "")],
                                 "corners": None})
            art_path = None
    if art_path is not None and rotate:
        art_path = _rotate(art_path, img / f"{sid}.rotated.png", rotate)
        if item["kind"] == "photo":
            _thumb(art_path, img / f"{sid}.crop.jpg")
    item["applied"] = {"corners": corners, "rotate": rotate}
    if art_path is not None:
        framed = img / f"{sid}.framed.png"
        rec = framing.frame_artwork(art_path, framed)
        _thumb(framed, img / f"{sid}.framed.jpg", 900)
        item["framed"] = f"img/{sid}.framed.jpg"
        item["framed_full"] = f"img/{sid}.framed.png"
        item["frame"] = {"recipe": rec["recipe"], "recipe_version": rec["recipe_version"],
                         "orientation": rec["layout"]["orientation"]}
        with Image.open(art_path) as a:
            item["art_size"] = list(a.size)
    if item["kind"] == "artwork":
        _thumb(source, img / f"{sid}.source.jpg")
        item["original"] = f"img/{sid}.source.jpg"
    return item


def pending(decisions: dict, items: list) -> set:
    """Items whose saved corners or rotation differ from what was last applied."""
    out = set()
    for item in items:
        d = decisions.get(item["id"], {})
        applied = item.get("applied") or {"corners": None, "rotate": 0}
        if d.get("corners") != applied.get("corners") or d.get("rotate", 0) != applied.get("rotate", 0):
            out.add(item["id"])
    return out


def status(item: dict) -> str:
    if item["kind"] == "artwork":
        return "ready" if item.get("framed") else "error"
    c = item.get("crop") or {}
    if c.get("method") == "manual":
        return "fixed"
    return "auto" if c.get("ok") else "flagged"


def build(source_dir: Path = DEFAULT_SOURCE, out: Path = OUT, only=None, log=print) -> list:
    out.mkdir(parents=True, exist_ok=True)
    decisions = load_decisions(out)
    items_path = out / "items.json"
    previous = {i["id"]: i for i in json.loads(items_path.read_text())} if items_path.exists() else {}
    items = []
    for i, src in enumerate(list_sources(source_dir), 1):
        sid = slug(src.name)
        if only is not None and sid not in only and sid in previous:
            items.append(previous[sid])
            continue
        fix = decisions.get(sid, {})
        try:
            item = process(src, out, corners=fix.get("corners"), rotate=fix.get("rotate", 0))
        except Exception as e:                        # one bad file never stops the batch
            item = {"id": sid, "source": src.name, "kind": "photo" if is_photo(src.name) else "artwork",
                    "error": f"{type(e).__name__}: {e}"}
        item["status"] = status(item) if "error" not in item else "error"
        items.append(item)
        log(f"[{i:>3}] {item['status']:8} {src.name}")
    items_path.write_text(json.dumps(items, indent=1))
    (out / "index.html").write_text(render_page(items))
    return items


# ---------------------------------------------------------------- page

def render_page(items: list) -> str:
    data = json.dumps(items).replace("</", "<\\/")      # safe inside <script>
    counts = {s: sum(1 for i in items if i.get("status") == s) for s in ("auto", "flagged", "fixed", "ready", "error")}
    summary = " · ".join(f"{n} {html.escape(s)}" for s, n in counts.items() if n)
    return PAGE.replace("{{DATA}}", data).replace("{{SUMMARY}}", summary)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Image Review</title>
<style>
:root {
  --bg: #f6f5f2; --card: #ffffff; --ink: #1d1d1b; --muted: #6b6a66; --line: #e3e1dc;
  --ok: #1f8a4c; --ok-bg: #e5f4ea; --warn: #b4441f; --warn-bg: #fbe9e2; --info: #2d5fa8; --info-bg: #e6eefa;
  --accent: #1d1d1b; --chip: #efeee9;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #161615; --card: #1f1f1d; --ink: #ecebe7; --muted: #a09f9a; --line: #33322f;
    --ok: #5cc58a; --ok-bg: #1d3326; --warn: #f08a63; --warn-bg: #3a231a; --info: #86a9e0; --info-bg: #1d2738;
    --accent: #ecebe7; --chip: #2a2a27;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
header { position: sticky; top: 0; z-index: 5; background: var(--bg); border-bottom: 1px solid var(--line);
  padding: 14px 20px; display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
h1 { font-size: 18px; margin: 0 12px 0 0; }
.summary { color: var(--muted); font-size: 13px; margin-right: auto; }
.filters button, .actions button, .modal button { font: inherit; font-size: 13px; border: 1px solid var(--line);
  background: var(--card); color: var(--ink); border-radius: 999px; padding: 6px 12px; cursor: pointer; }
.filters button[aria-pressed="true"] { background: var(--accent); color: var(--bg); border-color: var(--accent); }
.save-state { font-size: 12px; color: var(--muted); min-width: 90px; text-align: right; }
button.apply { font: inherit; font-size: 13px; font-weight: 600; border: 1px solid var(--accent); border-radius: 999px;
  padding: 7px 14px; background: var(--accent); color: var(--bg); cursor: pointer; }
button.apply:disabled { opacity: .45; cursor: default; }
.badge.pending { background: var(--info-bg); color: var(--info); }
.frame-box img.turned { transition: transform .2s; }
.tip { font-size: 12px; color: var(--muted); }
main { padding: 20px; display: grid; gap: 18px; max-width: 1400px; margin: 0 auto; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }
.card-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
.name { font-weight: 600; margin-right: auto; overflow-wrap: anywhere; }
.badge { font-size: 12px; padding: 2px 9px; border-radius: 999px; background: var(--chip); color: var(--muted); }
.badge.auto, .badge.ready, .badge.fixed { background: var(--ok-bg); color: var(--ok); }
.badge.flagged, .badge.error { background: var(--warn-bg); color: var(--warn); }
.badge.decision-accept { background: var(--ok-bg); color: var(--ok); }
.badge.decision-reject { background: var(--warn-bg); color: var(--warn); }
.badge.decision-fix { background: var(--info-bg); color: var(--info); }
.steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.step { margin: 0; }
.step figcaption { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.frame-box { background: var(--chip); border-radius: 8px; aspect-ratio: 4 / 5; display: flex;
  align-items: center; justify-content: center; overflow: hidden; position: relative; }
.frame-box > img { width: 100%; height: 100%; object-fit: contain; display: block; cursor: zoom-in; }
.frame-box svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.empty { color: var(--muted); font-size: 13px; padding: 12px; text-align: center; }
.reasons { margin: 10px 0 0; padding-left: 18px; color: var(--warn); font-size: 13px; }
.meta { color: var(--muted); font-size: 12px; margin-top: 8px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; align-items: center; }
.actions button.accept { border-color: var(--ok); color: var(--ok); }
.actions button.reject { border-color: var(--warn); color: var(--warn); }
.actions button.fix { border-color: var(--info); color: var(--info); }
.actions button.accept[aria-pressed="true"] { background: var(--ok); color: var(--card); }
.actions button.reject[aria-pressed="true"] { background: var(--warn); color: var(--card); }
.actions button.fix[aria-pressed="true"] { background: var(--info); color: var(--card); }
.card.decided-accept { border-left: 6px solid var(--ok); }
.card.decided-reject { border-left: 6px solid var(--warn); opacity: .8; }
.card.decided-fix { border-left: 6px solid var(--info); }
.actions input { flex: 1 1 220px; font: inherit; font-size: 13px; padding: 6px 10px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--bg); color: var(--ink); }
.modal-back { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: none; z-index: 20;
  align-items: center; justify-content: center; padding: 16px; }
.modal-back.open { display: flex; }
.modal { background: var(--card); border-radius: 12px; padding: 16px; max-width: 1100px; width: 100%;
  max-height: 100%; overflow: auto; }
.modal h2 { font-size: 16px; margin: 0 0 4px; }
.modal p { margin: 0 0 12px; color: var(--muted); font-size: 13px; }
.stage { position: relative; display: inline-block; touch-action: none; user-select: none; }
.stage img { display: block; max-width: 100%; max-height: 72vh; min-height: 240px; }
.stage svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.handle { fill: #fff; stroke: #2d5fa8; stroke-width: 3; cursor: grab; }
.modal .row { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }
.zoom img { max-width: 100%; max-height: 85vh; display: block; margin: 0 auto; }
@media (max-width: 720px) {
  .steps { grid-template-columns: 1fr; }
  header { padding: 12px 16px; } main { padding: 16px; }
}
</style>
</head>
<body>
<header>
  <h1>Image review</h1>
  <span class="summary">{{SUMMARY}}</span>
  <div class="filters" role="group" aria-label="Filter">
    <button data-filter="all" aria-pressed="true">All</button>
    <button data-filter="todo" aria-pressed="false">To review</button>
    <button data-filter="flagged" aria-pressed="false">Flagged</button>
    <button data-filter="photo" aria-pressed="false">Photos</button>
    <button data-filter="artwork" aria-pressed="false">Ready-cut files</button>
  </div>
  <span class="save-state" id="save-state"></span>
  <button class="apply" id="apply-btn" disabled>Apply my changes</button>
</header>
<main id="list"></main>

<div class="modal-back" id="fix-modal" role="dialog" aria-modal="true" aria-labelledby="fix-title">
  <div class="modal">
    <h2 id="fix-title">Fix corners</h2>
    <p>Drag the four handles onto the corners of the artwork (for paper pieces, the painted area). Save, then run <code>review_images.py apply</code> to re-crop.</p>
    <div class="stage" id="stage"><img id="stage-img" alt=""><svg id="stage-svg"></svg></div>
    <div class="row"><button id="fix-reset">Reset to full photo</button><button id="fix-cancel">Cancel</button><button id="fix-save">Save corners</button></div>
  </div>
</div>
<div class="modal-back" id="zoom-modal" role="dialog" aria-modal="true" aria-label="Zoomed image">
  <div class="modal zoom"><img id="zoom-img" alt=""><div class="row"><button id="zoom-close">Close</button></div></div>
</div>

<script>
const ITEMS = {{DATA}};
let decisions = {};
let filter = "all";
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function loadDecisions() {
  try { const r = await fetch("decisions.json", {cache: "no-store"}); if (r.ok) decisions = await r.json(); } catch (e) {}
}
let saveTimer;
function save() {
  clearTimeout(saveTimer);
  $("#save-state").textContent = "Saving…";
  saveTimer = setTimeout(async () => {
    try {
      const r = await fetch("/decisions", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(decisions)});
      $("#save-state").textContent = r.ok ? "Saved" : "Not saved";
    } catch (e) { $("#save-state").textContent = "Not saved (is the server running?)"; }
  }, 300);
}

function rot(item) { return (decisions[item.id] && decisions[item.id].rotate) || 0; }
function appliedRot(item) { return (item.applied && item.applied.rotate) || 0; }
function isPending(item) {
  const d = decisions[item.id] || {}, a = item.applied || {corners: null, rotate: 0};
  return JSON.stringify(d.corners || null) !== JSON.stringify(a.corners || null) || (d.rotate || 0) !== (a.rotate || 0);
}
function updateApply() {
  const n = ITEMS.filter(isPending).length, b = $("#apply-btn");
  if (b.dataset.busy) return;
  b.disabled = !n;
  b.textContent = n ? `Apply my changes (${n})` : "Apply my changes";
}
function turn(item) {
  // preview a rotation that hasn't been applied yet
  const deg = (rot(item) - appliedRot(item) + 360) % 360;
  return deg ? ` class="turned" style="transform: rotate(${deg}deg) scale(${deg % 180 ? 0.78 : 1})"` : "";
}

function outline(item) {
  const c = item.crop && item.crop.corners;
  const fixed = decisions[item.id] && decisions[item.id].corners;
  const pts = fixed || c;
  if (!pts || !item.photo_size) return "";
  const [W, H] = item.photo_size;
  const colour = fixed ? "#2d5fa8" : (item.crop.ok ? "#1f8a4c" : "#d0442a");
  const p = pts.map(([x, y]) => `${(x / W * 100).toFixed(2)},${(y / H * 100).toFixed(2)}`).join(" ");
  return `<svg viewBox="0 0 100 100" preserveAspectRatio="none"><polygon points="${p}" fill="none" stroke="${colour}" stroke-width="0.8" vector-effect="non-scaling-stroke" style="stroke-width:3px"/></svg>`;
}

function stepBox(label, src, extra = "", attrs = "") {
  const inner = src ? `<img src="${esc(src)}" alt="${esc(label)}" loading="lazy" data-zoom="${esc(src)}"${attrs}>` : `<div class="empty">${esc(extra || "Not available")}</div>`;
  return `<figure class="step"><figcaption>${esc(label)}</figcaption><div class="frame-box">${inner}</div></figure>`;
}

function photoBox(item) {
  // The outline overlay needs the image's own box, so wrap image + svg tightly.
  const [W, H] = item.photo_preview_size || [4, 5];
  return `<figure class="step"><figcaption>Photo and outline found</figcaption><div class="frame-box">
    <div style="position:relative;aspect-ratio:${W}/${H};max-width:100%;max-height:100%;height:100%">
      <img src="${esc(item.photo)}" alt="Original photo" loading="lazy" data-zoom="${esc(item.photo)}" style="width:100%;height:100%;object-fit:contain">
      ${outline(item)}</div></div></figure>`;
}

function card(item) {
  const d = decisions[item.id] || {};
  const st = item.status;
  const label = {auto: "Cropped automatically", flagged: "Needs corners", fixed: "Corners fixed", ready: "Ready-cut file", error: "Error"}[st] || st;
  const decision = d.decision ? `<span class="badge decision-${d.decision}">${{accept: "Accepted", reject: "Rejected", fix: "Corners saved"}[d.decision]}</span>` : "";
  const pend = isPending(item) ? `<span class="badge pending">Not applied yet${rot(item) !== appliedRot(item) ? ` · rotate ${rot(item)}°` : ""}</span>` : "";
  let steps;
  if (item.kind === "photo") {
    steps = photoBox(item) + stepBox("Cropped", item.cropped, "No crop yet: fix the corners", turn(item)) + stepBox(isPending(item) ? "Framed (updates when you apply)" : "Framed listing image", item.framed, "Appears after cropping", turn(item));
  } else {
    steps = stepBox("Original file", item.original, "", turn(item)) + stepBox(isPending(item) ? "Framed (updates when you apply)" : "Framed listing image", item.framed, "", turn(item)) + `<figure class="step"><figcaption>Details</figcaption><div class="frame-box"><div class="empty">${esc((item.art_size || []).join(" × "))} px<br>${esc(item.frame ? item.frame.orientation : "")}</div></div></figure>`;
  }
  const reasons = (item.crop && !item.crop.ok && item.crop.reasons && item.crop.reasons.length)
    ? `<ul class="reasons">${item.crop.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : "";
  const err = item.error ? `<ul class="reasons"><li>${esc(item.error)}</li></ul>` : "";
  const meta = [item.crop && item.crop.method ? `crop: ${item.crop.method} (v${item.crop.recipe_version})` : "",
                item.frame ? `frame: ${item.frame.orientation} (v${item.frame.recipe_version})` : ""].filter(Boolean).join(" · ");
  const on = act => d.decision === act ? ' aria-pressed="true"' : ' aria-pressed="false"';
  const fixBtn = item.kind === "photo" ? `<button class="fix" data-act="fix"${on("fix")}>${d.corners ? "✓ Corners saved: edit" : "Fix corners"}</button>` : "";
  return `<article class="card${d.decision ? " decided-" + esc(d.decision) : ""}" data-id="${esc(item.id)}">
    <div class="card-head"><span class="name">${esc(item.source)}</span><span class="badge ${esc(st)}">${esc(label)}</span>${decision}${pend}</div>
    <div class="steps">${steps}</div>${reasons}${err}
    ${meta ? `<div class="meta">${esc(meta)}</div>` : ""}
    <div class="actions">
      <button class="accept" data-act="accept"${on("accept")}>${d.decision === "accept" ? "✓ Accepted" : "Accept"}</button>${fixBtn}<button data-act="rotate" title="Turn 90° clockwise. The signature belongs in the bottom-right corner.">Rotate ↻ ${rot(item) ? rot(item) + "°" : ""}</button><button class="reject" data-act="reject"${on("reject")}>${d.decision === "reject" ? "✗ Rejected" : "Reject"}</button>
      <input type="text" data-act="note" placeholder="Note (optional)" value="${esc(d.note || "")}" aria-label="Note for ${esc(item.source)}">
    </div></article>`;
}

function visible(item) {
  const d = decisions[item.id];
  if (filter === "todo") return !d || !d.decision;
  if (filter === "flagged") return item.status === "flagged" || item.status === "error";
  if (filter === "photo" || filter === "artwork") return item.kind === filter;
  return true;
}
function render() {
  const list = $("#list");
  const shown = ITEMS.filter(visible);
  list.innerHTML = shown.length ? shown.map(card).join("") : `<div class="card empty">Nothing here.</div>`;
  updateApply();
}

document.addEventListener("click", e => {
  const f = e.target.closest("[data-filter]");
  if (f) { filter = f.dataset.filter; document.querySelectorAll("[data-filter]").forEach(b => b.setAttribute("aria-pressed", b === f)); render(); return; }
  const z = e.target.closest("[data-zoom]");
  if (z) { $("#zoom-img").src = z.dataset.zoom; $("#zoom-modal").classList.add("open"); return; }
  const a = e.target.closest("[data-act]");
  if (!a || a.tagName === "INPUT") return;
  const id = a.closest(".card").dataset.id;
  const item = ITEMS.find(i => i.id === id);
  if (a.dataset.act === "fix") return openFix(item);
  if (a.dataset.act === "rotate") {
    decisions[id] = {...(decisions[id] || {decision: null}), rotate: (rot(item) + 90) % 360};
    save(); render(); return;
  }
  // accepting or rejecting keeps any corners and rotation you set; clicking it again undoes it
  const current = (decisions[id] || {}).decision;
  decisions[id] = {...(decisions[id] || {}), decision: current === a.dataset.act ? null : a.dataset.act};
  save(); render();
});
document.addEventListener("input", e => {
  if (e.target.dataset.act !== "note") return;
  const id = e.target.closest(".card").dataset.id;
  decisions[id] = {...(decisions[id] || {decision: null}), note: e.target.value};
  save();
});
$("#zoom-close").onclick = () => $("#zoom-modal").classList.remove("open");
$("#zoom-modal").onclick = e => { if (e.target.id === "zoom-modal") $("#zoom-modal").classList.remove("open"); };
document.addEventListener("keydown", e => { if (e.key === "Escape") document.querySelectorAll(".modal-back").forEach(m => m.classList.remove("open")); });

// ---- corner fixing
let fixItem = null, pts = null, drag = -1;
function openFix(item) {
  fixItem = item;
  const [W, H] = item.photo_size;
  const saved = decisions[item.id] && decisions[item.id].corners;
  pts = (saved || (item.crop && item.crop.corners) || [[W*.1,H*.1],[W*.9,H*.1],[W*.9,H*.9],[W*.1,H*.9]]).map(p => [...p]);
  $("#stage-svg").setAttribute("viewBox", `0 0 ${W} ${H}`);
  $("#fix-modal").classList.add("open");
  $("#stage-img").onload = drawFix;
  $("#stage-img").src = item.photo;
  drawFix();
}
function drawFix() {
  // size handles in screen pixels, whatever the photo's resolution
  const [W] = fixItem.photo_size;
  const shown = $("#stage-img").getBoundingClientRect().width || 600;
  const px = W / shown;
  $("#stage-svg").innerHTML = `<polygon points="${pts.map(p => p.join(",")).join(" ")}" fill="rgba(45,95,168,.15)" stroke="#2d5fa8" stroke-width="${2.5 * px}"/>` +
    pts.map((p, i) => `<circle class="handle" data-i="${i}" cx="${p[0]}" cy="${p[1]}" r="${11 * px}" stroke-width="${3 * px}"/>`).join("");
}
window.addEventListener("resize", () => { if (fixItem && $("#fix-modal").classList.contains("open")) drawFix(); });
function toPhoto(ev) {
  const box = $("#stage-svg").getBoundingClientRect(); const [W, H] = fixItem.photo_size;
  return [Math.max(0, Math.min(W, (ev.clientX - box.left) / box.width * W)), Math.max(0, Math.min(H, (ev.clientY - box.top) / box.height * H))];
}
$("#stage-svg").addEventListener("pointerdown", e => {
  const h = e.target.closest(".handle");
  if (h) drag = +h.dataset.i;
  else { // click anywhere: move the nearest handle there
    const p = toPhoto(e); let best = 0, bd = Infinity;
    pts.forEach((q, i) => { const d = (q[0]-p[0])**2 + (q[1]-p[1])**2; if (d < bd) { bd = d; best = i; } });
    drag = best; pts[best] = p; drawFix();
  }
  $("#stage-svg").setPointerCapture(e.pointerId);
});
$("#stage-svg").addEventListener("pointermove", e => { if (drag >= 0) { pts[drag] = toPhoto(e); drawFix(); } });
$("#stage-svg").addEventListener("pointerup", () => { drag = -1; });
$("#fix-reset").onclick = () => { const [W, H] = fixItem.photo_size; pts = [[0,0],[W,0],[W,H],[0,H]]; drawFix(); };
$("#fix-cancel").onclick = () => $("#fix-modal").classList.remove("open");
$("#fix-save").onclick = () => {
  // keep corner order tl, tr, br, bl whatever order the handles were dragged into
  const cx = pts.reduce((s, p) => s + p[0], 0) / 4, cy = pts.reduce((s, p) => s + p[1], 0) / 4;
  const ordered = [...pts].sort((a, b) => Math.atan2(a[1]-cy, a[0]-cx) - Math.atan2(b[1]-cy, b[0]-cx));
  const tl = ordered.reduce((m, p) => (p[0] + p[1] < m[0] + m[1] ? p : m));
  const start = ordered.indexOf(tl);
  const corners = [0, 1, 2, 3].map(k => ordered[(start + k) % 4].map(v => Math.round(v * 10) / 10));
  decisions[fixItem.id] = {...(decisions[fixItem.id] || {}), decision: "fix", corners};
  $("#fix-modal").classList.remove("open");
  save(); render();
};

$("#apply-btn").onclick = async () => {
  const b = $("#apply-btn");
  b.dataset.busy = "1"; b.disabled = true; b.textContent = "Starting…";
  clearTimeout(saveTimer);
  await fetch("/decisions", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(decisions)});
  const r = await fetch("/apply", {method: "POST"});
  if (!r.ok) { b.textContent = "Already applying…"; }
  const poll = async () => {
    const s = await (await fetch("/apply-status", {cache: "no-store"})).json();
    if (s.error) { b.textContent = "Failed: " + s.error; delete b.dataset.busy; return; }
    if (s.running) { b.textContent = `Applying ${Math.min(s.done + 1, s.total)} of ${s.total}…`; return setTimeout(poll, 1000); }
    b.textContent = "Done, reloading…"; location.reload();
  };
  poll();
};

loadDecisions().then(render);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- serve

SOURCE = DEFAULT_SOURCE
JOB = {"running": False, "done": 0, "total": 0, "error": None, "finished": False}
_JOB_LOCK = threading.Lock()


def _run_apply(ids: set):
    try:
        build(SOURCE, OUT, only=ids, log=lambda *_: JOB.__setitem__("done", JOB["done"] + 1))
    except Exception as e:                            # report, don't crash the server
        JOB["error"] = f"{type(e).__name__}: {e}"
    finally:
        JOB["running"], JOB["finished"] = False, True


def start_apply() -> int:
    """Re-process every item with unapplied corners or rotation, in the background. Returns the count."""
    with _JOB_LOCK:
        if JOB["running"]:
            raise RuntimeError("already applying")
        items = json.loads((OUT / "items.json").read_text()) if (OUT / "items.json").exists() else []
        ids = pending(load_decisions(OUT), items)
        JOB.update(running=bool(ids), done=0, total=len(ids), error=None, finished=not ids)
        if ids:
            threading.Thread(target=_run_apply, args=(ids,), daemon=True).start()
        return len(ids)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, directory=None, **kw):
        super().__init__(*a, directory=str(OUT), **kw)

    def _json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/apply-status":
            return self._json(200, dict(JOB))
        return super().do_GET()

    def do_POST(self):
        if self.path == "/apply":
            try:
                return self._json(202, {"count": start_apply()})
            except RuntimeError as e:
                return self._json(409, {"error": str(e)})
        if self.path != "/decisions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2_000_000:
            self.send_error(413)
            return
        try:
            data = validate_decisions(json.loads(self.rfile.read(length) or b"{}"))
        except (ValueError, json.JSONDecodeError) as e:
            self.send_error(400, str(e))
            return
        (OUT / DECISIONS).write_text(json.dumps(data, indent=1))
        self.send_response(204)
        self.end_headers()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        line = fmt % args
        if "POST /apply " in line:
            sys.stderr.write("applying changes\n")
        if "POST /decisions" in line:
            sys.stderr.write(("saved decisions" if " 204 " in line else line) + "\n")


HOST = "127.0.0.1"   # never 0.0.0.0: the page shows unpublished artwork


def make_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), Handler)


def serve(port: int, source: Path = DEFAULT_SOURCE):
    global SOURCE
    SOURCE = Path(source)
    if not (OUT / "index.html").exists():
        raise SystemExit("No review page yet. Run: .venv/bin/python scripts/review_images.py build")
    httpd = make_server(port)
    print(f"Review page: http://127.0.0.1:{port}/  (only this computer can open it; Ctrl+C to stop)")
    httpd.serve_forever()


def apply(source_dir: Path = DEFAULT_SOURCE) -> int:
    items = json.loads((OUT / "items.json").read_text()) if (OUT / "items.json").exists() else []
    ids = pending(load_decisions(), items)
    if not ids:
        print("Nothing to apply.")
        return 0
    build(source_dir, only=ids)
    print(f"Applied corners or rotation for {len(ids)} image(s). Reload the page.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE))
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE))
    a = sub.add_parser("apply")
    a.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE))
    args = ap.parse_args(argv)
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise SystemExit("Pillow isn't installed. Use the project environment: .venv/bin/python")
    if args.cmd == "build":
        build(Path(args.source))
        print(f"\nWrote {OUT / 'index.html'}. Open it with: .venv/bin/python scripts/review_images.py serve")
        return 0
    if args.cmd == "serve":
        serve(args.port, Path(args.source))
        return 0
    return apply(Path(args.source))


if __name__ == "__main__":
    sys.exit(main())
