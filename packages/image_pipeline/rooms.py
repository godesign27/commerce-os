"""Room views: a framed piece hung on the wall of a room photo (B-063).

The room library lives in .commerce-os/rooms/, which is gitignored because the photos are licensed to the
owner, not ours to commit:

    rooms.json          one entry per room: where the photo came from and its licence, the hanging area
                        on the wall (four corners) and how wide that area is in real life
    files/<id>.jpg      the room photo, sRGB, at most 3000 px on its long side
    inbox/              drop new room photos here; "Look for new rooms" imports them into the library
    previews/<id>.jpg   the room with a sample piece, for setting it up

A room is used only once its licence is recorded and its wall is set. A piece hangs at its real size when
the listing's dimensions are known (with a unit); otherwise at a guessed size, and the view says so. The
piece is the same render as the listing's framed image (art unchanged, mat, oak frame), warped onto the
wall in perspective, dimmed to the room's light and given a soft shadow. The artwork file is never
changed. Geometry is stdlib only; rendering needs Pillow.
"""
import datetime
import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from packages.image_pipeline import framing, stages

REPO = Path(__file__).resolve().parents[2]
ROOMS = REPO / ".commerce-os" / "rooms"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}
MAX_SIDE = 3000                    # room photos are stored at most this size
MAX_UPLOAD = 40_000_000            # "Add a room" takes photos up to this many bytes
VIEW_WIDTH = 2000                  # room views are rendered at this width
GUESS_FILL = 0.45                  # with no dimensions, the frame spans this share of the hanging area
MAX_FILL = 0.95                    # never wider or taller than this share of the hanging area
LICENCES = {
    "own": "My own photo",
    "pexels": "Pexels licence (free to use, no attribution required)",
    "unsplash": "Unsplash licence (free to use, no attribution required)",
    "cc0": "Public domain (CC0)",
    "purchased": "Bought or subscribed (a stock or mockup service's licence)",
    "other": "Other: say which in the note",
}
EDITABLE = {"name", "wall", "wall_width_cm", "light", "shadow", "enabled", "licence", "credit", "url", "note"}
STATUSES = [("ready", "Ready"), ("needs-licence", "Needs a licence"), ("needs-wall", "Wall not marked"),
            ("off", "Turned off")]


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- the library

def load(root: Path = ROOMS) -> dict:
    p = Path(root) / "rooms.json"
    return json.loads(p.read_text()) if p.exists() else {"rooms": []}


def save(lib: dict, root: Path = ROOMS) -> None:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / "rooms.json.tmp"
    tmp.write_text(json.dumps(lib, indent=1))
    tmp.replace(root / "rooms.json")


def get(lib: dict, room_id: str) -> Optional[dict]:
    return next((r for r in lib["rooms"] if r["id"] == room_id), None)


def status(room: dict) -> str:
    if not room.get("licence") or (room["licence"] == "other" and not (room.get("note") or "").strip()):
        return "needs-licence"
    if not room.get("wall") or not room.get("wall_width_cm"):
        return "needs-wall"
    return "ready" if room.get("enabled", True) else "off"


def ready(lib: dict) -> List[dict]:
    return [r for r in lib["rooms"] if status(r) == "ready"]


def update(room: dict, changes: dict) -> dict:
    """The room with `changes` applied and checked. Raises ValueError; never edits `room` in place."""
    if not isinstance(changes, dict) or not changes or set(changes) - EDITABLE:
        raise ValueError(f"send any of: {', '.join(sorted(EDITABLE))}")
    r = dict(room)
    for k, v in changes.items():
        if k == "wall":
            r[k] = None if v is None else stages.order_corners(v, room["size"])
        elif k == "wall_width_cm":
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not 20 <= v <= 2000):
                raise ValueError("the wall width is between 20 and 2000 cm")
            r[k] = None if v is None else round(float(v), 1)
        elif k in ("light", "shadow"):
            lo, hi = (0.5, 1.1) if k == "light" else (0.0, 0.8)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                raise ValueError(f"{k} is between {lo} and {hi}")
            r[k] = round(float(v), 2)
        elif k == "enabled":
            if not isinstance(v, bool):
                raise ValueError("enabled is true or false")
            r[k] = v
        elif k == "licence":
            if v is not None and v not in LICENCES:
                raise ValueError(f"licence is one of: {', '.join(LICENCES)}")
            r[k] = v
        else:                                          # name, credit, url, note: plain text
            if v is not None and not isinstance(v, str):
                raise ValueError(f"{k} is text")
            v = (v or "").strip()[:500]
            if k == "name" and not v:
                raise ValueError("a room needs a name")
            if k == "url" and v and not re.match(r"^https?://", v):
                raise ValueError("the source link starts with http:// or https://")
            r[k] = v
            if k == "name" and v != room.get("name"):
                r["named_by"] = "owner"                # a name the owner typed is never replaced by a suggestion
    r["updated_at"] = now()
    return r


def _sha(path: Path) -> str:
    return framing.sha256_file(path)


def import_file(src: Path, root: Path = ROOMS, name: str = "", licence: Optional[str] = None, credit: str = "",
                url: str = "", note: str = "") -> Tuple[dict, bool]:
    """Copy one room photo into the library (sRGB, upright, at most MAX_SIDE). Returns (room, added); a photo
    already in the library is not added twice."""
    from PIL import Image
    src, root = Path(src), Path(root)
    digest = _sha(src)
    lib = load(root)
    for r in lib["rooms"]:
        if r.get("source_sha256") == digest:
            return r, False
    stem = re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-")[:32] or "room"
    rid = f"room-{stem}-{digest[:6]}"
    im = framing._open_artwork(src)                  # upright, sRGB, transparency on white
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    (root / "files").mkdir(parents=True, exist_ok=True)
    im.save(root / "files" / f"{rid}.jpg", "JPEG", quality=90)
    room = {"id": rid, "name": name.strip() or src.stem.replace("-", " ").replace("_", " ").strip().capitalize(),
            "file": f"files/{rid}.jpg", "size": list(im.size), "source_file": src.name, "source_sha256": digest,
            "licence": licence if licence in LICENCES else None, "credit": credit.strip(), "url": url.strip(),
            "note": note.strip(), "wall": None, "wall_width_cm": None, "light": 0.95, "shadow": 0.3,
            "enabled": True, "named_by": "owner" if name.strip() else "file", "added_at": now(), "updated_at": now()}
    lib["rooms"].append(room)
    save(lib, root)
    return room, True


def import_upload(data: bytes, filename: str, root: Path = ROOMS, **meta) -> Tuple[dict, bool]:
    """A photo sent from "Add a room": kept in inbox/imported/ like a scanned one, then imported. Anything
    that isn't a photo Pillow can open is refused, and nothing is left behind."""
    root = Path(root)
    base = Path(filename or "").name
    stem = re.sub(r"[^\w.-]+", "-", Path(base).stem).strip("-.")[:64] or "room"
    ext = Path(base).suffix.lower()
    if ext not in IMAGE_EXT:
        raise ValueError(f"not a photo: use {', '.join(sorted(IMAGE_EXT))}")
    if not data:
        raise ValueError("the file is empty")
    if len(data) > MAX_UPLOAD:
        raise ValueError(f"too large: at most {MAX_UPLOAD // 1_000_000} MB")
    done = root / "inbox" / "imported"
    done.mkdir(parents=True, exist_ok=True)
    target = done / f"{stem}{ext}"
    n = 1
    while target.exists() and _sha(target) != hashlib.sha256(data).hexdigest():
        n += 1
        target = done / f"{stem}-{n}{ext}"
    existed = target.exists()
    target.write_bytes(data)
    try:
        return import_file(target, root, **meta)
    except Exception as e:
        if not existed:
            target.unlink(missing_ok=True)
        raise ValueError(f"couldn't open that photo ({type(e).__name__})") from e


def scan_inbox(root: Path = ROOMS) -> List[dict]:
    """Import every photo in inbox/, then move each original to inbox/imported/. Returns the rooms added."""
    root = Path(root)
    inbox = root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    added = []
    for p in sorted(inbox.iterdir()):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXT or p.name.startswith("."):
            continue
        room, new = import_file(p, root)
        if new:
            added.append(room)
        done = inbox / "imported"
        done.mkdir(exist_ok=True)
        shutil.move(str(p), str(done / p.name))
    return added


# ---------------------------------------------------------------- sizes

_UNIT = r'(cm|mm|in(?:ch(?:es)?)?|"|”|″|\'\')'
_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*" + _UNIT + r"?\s*(?:x|×|by)\s*(\d+(?:\.\d+)?)\s*" + _UNIT + "?", re.I)
_CM = {"cm": 1.0, "mm": 0.1}


def parse_size(text: Optional[str]) -> Optional[Tuple[float, float]]:
    """'16 x 20 in', '40×50 cm', '12" x 16"' -> (width, height) in cm, as written. None without a unit:
    a bare '16x20' could be inches or centimetres, and the size is never guessed from a number alone."""
    m = _SIZE.search(text or "")
    if not m:
        return None
    a, u1, b, u2 = m.groups()
    unit = (u2 or u1 or "").lower()
    if not unit:
        return None
    k = _CM.get(unit, 2.54)
    return round(float(a) * k, 2), round(float(b) * k, 2)


# ---------------------------------------------------------------- geometry

def homography(src: List[List[float]], dst: List[List[float]]) -> List[float]:
    """The 8 coefficients (a..h) of the projective map taking each src point to its dst point:
    x' = (a x + b y + c) / (g x + h y + 1), y' = (d x + e y + f) / (g x + h y + 1)."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); rhs.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y]); rhs.append(v)
    n = 8
    m = [row[:] + [r] for row, r in zip(rows, rhs)]
    for col in range(n):                                  # Gaussian elimination, partial pivoting
        piv = max(range(col, n), key=lambda i: abs(m[i][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ValueError("the corners are in a line")
        m[col], m[piv] = m[piv], m[col]
        for i in range(n):
            if i != col:
                f = m[i][col] / m[col][col]
                m[i] = [a - f * b for a, b in zip(m[i], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def apply_h(h: List[float], x: float, y: float) -> Tuple[float, float]:
    a, b, c, d, e, f, g, hh = h
    w = g * x + hh * y + 1
    return (a * x + b * y + c) / w, (d * x + e * y + f) / w


def _dist(p, q) -> float:
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def wall_height_cm(room: dict) -> float:
    """The hanging area's height, from its width and the average of its edges in the photo."""
    tl, tr, br, bl = room["wall"]
    across = (_dist(tl, tr) + _dist(bl, br)) / 2
    down = (_dist(tl, bl) + _dist(tr, br)) / 2
    return room["wall_width_cm"] * down / across


def placement(room: dict, frame_px: Tuple[int, int], art_px: Tuple[int, int],
              art_cm: Optional[Tuple[float, float]]) -> dict:
    """Where the frame goes on the wall: its four corners in the room photo, and the size it was hung at.

    frame_px and art_px come from the framing layout (the frame's outside and the artwork inside it), so the
    frame's real size is the artwork's real size scaled by the same mat and frame. A piece of known size is
    never shrunk: one bigger than the hanging area is hung at its real size and marked `overflows`. With no
    art_cm the frame spans GUESS_FILL of the hanging area, shrunk if needed to MAX_FILL of either side
    (`fitted`). Either way it is centred."""
    fw, fh = frame_px
    wall_w, wall_h = room["wall_width_cm"], wall_height_cm(room)
    guessed = art_cm is None
    if not guessed:
        aw_cm, ah_cm = art_cm
        if (aw_cm > ah_cm) != (art_px[0] > art_px[1]) and abs(aw_cm - ah_cm) > 0.5:
            aw_cm, ah_cm = ah_cm, aw_cm                   # written as height x width
        frame_w_cm = aw_cm * fw / art_px[0]
    else:
        frame_w_cm = GUESS_FILL * wall_w
    frame_h_cm = frame_w_cm * fh / fw
    fit = min(1.0, MAX_FILL * wall_w / frame_w_cm, MAX_FILL * wall_h / frame_h_cm)
    scale = fit if guessed else 1.0               # a real size is never changed to suit the room
    fitted = scale < 1.0
    overflows = not guessed and (frame_w_cm > wall_w or frame_h_cm > wall_h)
    frame_w_cm, frame_h_cm = frame_w_cm * scale, frame_h_cm * scale
    u, v = frame_w_cm / wall_w, frame_h_cm / wall_h      # share of the hanging area
    u0, v0 = (1 - u) / 2, (1 - v) / 2
    h = homography([[0, 0], [1, 0], [1, 1], [0, 1]], room["wall"])
    corners = [list(apply_h(h, x, y)) for x, y in ((u0, v0), (u0 + u, v0), (u0 + u, v0 + v), (u0, v0 + v))]
    return {"corners": [[round(x, 1), round(y, 1)] for x, y in corners],
            "frame_cm": [round(frame_w_cm, 1), round(frame_h_cm, 1)], "guessed": guessed, "fitted": fitted,
            "overflows": overflows}


# ---------------------------------------------------------------- rendering (Pillow)

def framed_piece(art_file: Path):
    """The frame, mat and artwork alone (no canvas, no shadow), and the layout it came from."""
    recipe = framing.load_recipe()
    image, lay = framing.render(Path(art_file), recipe, canvas_width=1800)
    return image.crop(lay.frame), lay


def render_view(room: dict, root: Path, art_file: Path, dimensions: Optional[str], out_path: Path) -> dict:
    """Hang one piece in one room and save the view. Returns what was rendered, for the manifest."""
    from PIL import Image, ImageEnhance, ImageFilter
    if not room.get("wall") or not room.get("wall_width_cm"):
        raise ValueError("set the room's wall first")
    base = Image.open(Path(root) / room["file"]).convert("RGB")
    k = VIEW_WIDTH / base.width if base.width > VIEW_WIDTH else 1.0
    if k != 1.0:
        base = base.resize((VIEW_WIDTH, round(base.height * k)), Image.LANCZOS)
    scaled = dict(room, wall=[[x * k, y * k] for x, y in room["wall"]])
    piece, lay = framed_piece(art_file)
    art_px = (lay.art[2] - lay.art[0], lay.art[3] - lay.art[1])
    art_cm = parse_size(dimensions)
    place = placement(scaled, piece.size, art_px, art_cm)
    pw, ph = piece.size
    coeffs = homography(place["corners"], [[0, 0], [pw, 0], [pw, ph], [0, ph]])   # view pixel -> piece pixel
    light = room.get("light", 0.95)
    lit = ImageEnhance.Brightness(piece).enhance(light) if light != 1.0 else piece
    layer = lit.convert("RGBA").transform(base.size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    alpha = layer.split()[3]
    # Soft shadow: the frame's outline, blurred and dropped a little below it.
    span = _dist(place["corners"][0], place["corners"][3])
    shadow_k = room.get("shadow", 0.3)
    if shadow_k > 0:
        blur = max(2.0, span * 0.025)
        sh = Image.new("L", base.size, 0)
        sh.paste(alpha, (0, round(span * 0.02)))
        sh = sh.filter(ImageFilter.GaussianBlur(blur)).point(lambda a: round(a * shadow_k))
        base.paste(Image.new("RGB", base.size, (0, 0, 0)), (0, 0), sh)
    base.paste(layer.convert("RGB"), (0, 0), alpha)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(out_path, "JPEG", quality=88)
    return {"room": room["id"], "room_updated_at": room.get("updated_at"), "file": out_path.name,
            "rendered_at": now(), "dimensions": dimensions or "", "frame_cm": place["frame_cm"],
            "guessed": place["guessed"], "fitted": place["fitted"], "overflows": place["overflows"]}


# ---------------------------------------------------------------- views per piece

def views_path(out: Path) -> Path:
    return Path(out) / "room_views.json"


def load_views(out: Path) -> dict:
    p = views_path(out)
    return json.loads(p.read_text()) if p.exists() else {}


def is_stale(view: dict, room: dict, item: dict, dimensions: Optional[str]) -> bool:
    return (view.get("room_updated_at") != room.get("updated_at") or view.get("processed_at") != item.get("processed_at")
            or view.get("dimensions", "") != (dimensions or ""))


def render_item(item: dict, lib: dict, root: Path, out: Path, dimensions: Optional[str],
                rooms: Optional[List[dict]] = None) -> List[dict]:
    """Hang one piece in every ready room (or the rooms given), and record each view. Returns the records."""
    if not item.get("art_file"):
        raise ValueError("this piece has no cropped artwork yet")
    art = Path(item["art_file"])
    art = art if art.is_absolute() else REPO / art
    rooms = ready(lib) if rooms is None else rooms
    if any(status(r) != "ready" for r in rooms):
        raise ValueError("only ready rooms (licence recorded, wall set, turned on) are used for listings")
    records = []
    for room in rooms:
        rec = render_view(room, root, art, dimensions, Path(out) / "img" / f"{item['id']}.room-{room['id']}.jpg")
        rec["processed_at"] = item.get("processed_at")
        records.append(rec)
    views = load_views(out)
    entry = views.get(item["id"], {})
    entry.update({r["room"]: r for r in records})
    views[item["id"]] = entry
    tmp = views_path(out).with_suffix(".tmp")
    tmp.write_text(json.dumps(views, indent=1))
    tmp.replace(views_path(out))
    return records


# ---------------------------------------------------------------- one room per piece

FRAME_ALLOWANCE = 1.3              # the mat and frame make a piece about this much bigger than its art


def choices_path(out: Path) -> Path:
    return Path(out) / "room_choice.json"


def load_choices(out: Path) -> dict:
    p = choices_path(out)
    return json.loads(p.read_text()) if p.exists() else {}


def save_choice(out: Path, item_id: str, room_id: Optional[str]) -> None:
    """The owner's room for a piece; None goes back to the automatic pick."""
    choices = load_choices(out)
    if room_id is None:
        choices.pop(item_id, None)
    else:
        choices[item_id] = {"room": room_id, "at": now()}
    tmp = choices_path(out).with_suffix(".tmp")
    tmp.write_text(json.dumps(choices, indent=1))
    tmp.replace(choices_path(out))


def _real_size(item: dict, dimensions: Optional[str]) -> Optional[Tuple[float, float]]:
    """The artwork's size in cm, turned to match the art's orientation; None when it isn't known."""
    aw, ah = (item.get("art_size") or [1, 1])[:2]
    size = parse_size(dimensions)
    if size and (size[0] > size[1]) != (aw > ah) and abs(size[0] - size[1]) > 0.5:
        size = (size[1], size[0])                         # written as height x width
    return size


def too_big(room: dict, size: Optional[Tuple[float, float]]) -> bool:
    """Whether a piece of this real size, framed, is bigger than the room's hanging area."""
    return bool(size) and (size[0] * FRAME_ALLOWANCE > room["wall_width_cm"] or size[1] * FRAME_ALLOWANCE > wall_height_cm(room))


def auto_room(item: dict, candidates: List[dict], dimensions: Optional[str]) -> Optional[dict]:
    """The best wall for a piece: one it fits on at its real size when that's known, then the hanging area
    closest to its shape (portrait on a tall wall, landscape on a wide one). Rooms that suit it about as well
    are shared out by a stable hash, so the pieces don't all land in the same room."""
    if not candidates:
        return None
    aw, ah = (item.get("art_size") or [1, 1])[:2]
    shape = aw / ah if aw and ah else 1.0
    size = _real_size(item, dimensions)

    def score(r):
        tie = hashlib.sha256(f"{item['id']}:{r['id']}".encode()).hexdigest()
        return (too_big(r, size), round(abs(math.log(shape / (r["wall_width_cm"] / wall_height_cm(r)))), 1), tie)
    return min(candidates, key=score)


def chosen(item: dict, lib: dict, out: Path, dimensions: Optional[str]) -> Tuple[Optional[dict], bool, Optional[str]]:
    """The room a piece is shown in: (room, picked automatically, name of a chosen room that can't be used
    any more). Only ready rooms are ever used; a choice whose room stopped being ready falls back."""
    rid = (load_choices(out).get(item["id"]) or {}).get("room")
    room = get(lib, rid) if rid else None
    if room and status(room) == "ready":
        return room, False, None
    lost = (room or {}).get("name") or rid
    return auto_room(item, ready(lib), dimensions), True, lost


def room_view(item: dict, lib: dict, out: Path, dimensions: Optional[str]) -> Optional[dict]:
    """The photo page's environment photo: the piece in its room, whether it's been made and is up to date."""
    room, auto, lost = chosen(item, lib, out, dimensions)
    if not room:
        return None
    v = load_views(out).get(item["id"], {}).get(room["id"])
    return {"room": room["id"], "name": room["name"], "auto": auto, "unavailable": lost,
            "image": f"img/{v['file']}?v={v['rendered_at']}" if v else None,
            "stale": not v or is_stale(v, room, item, dimensions),
            "guessed": v["guessed"] if v else parse_size(dimensions) is None,
            "fitted": bool(v and v.get("fitted")), "overflows": bool(v and v.get("overflows")),
            "frame_cm": v["frame_cm"] if v else None,
            "fits_elsewhere": [r["name"] for r in ready(lib)
                               if r["id"] != room["id"] and not too_big(r, _real_size(item, dimensions))][:3]}


def image_url(room: dict, root: Path = ROOMS) -> str:
    """The room photo's address, changed whenever the file is (a cleaned or replaced photo isn't served from cache)."""
    f = Path(root) / room["file"]
    return f"rooms/{room['file']}" + (f"?v={int(f.stat().st_mtime)}" if f.exists() else "")


def options(lib: dict, root: Path = ROOMS) -> List[dict]:
    """Every room, for the Change room drawer: ready ones can be picked, the rest say what they still need."""
    out = []
    for r in lib["rooms"]:
        prev = Path(root) / "previews" / f"{r['id']}.jpg"
        st = status(r) if r.get("enabled", True) else "off"   # a room switched off says so, whatever else it needs
        out.append({"id": r["id"], "name": r["name"], "status": st, "image": image_url(r, root),
                    "preview": f"rooms/previews/{r['id']}.jpg" if prev.exists() else None})
    return sorted(out, key=lambda o: (o["status"] != "ready", o["status"] == "off"))   # ready first, off last


def public(room: dict, root: Path = ROOMS) -> dict:
    """A room as the dashboard sees it: its status, and its preview if one was made."""
    prev = Path(root) / "previews" / f"{room['id']}.jpg"
    return dict(room, status=status(room), image=image_url(room, root),
                preview=f"rooms/previews/{room['id']}.jpg?v={int(prev.stat().st_mtime)}" if prev.exists() else None,
                wall_height_cm=round(wall_height_cm(room), 1) if room.get("wall") and room.get("wall_width_cm") else None)
