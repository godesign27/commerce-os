"""Suggested set-up for a new room photo (B-063): a short name, where pieces can hang, and how wide that is.

One model call per room, made when a room is added (or when the owner asks again). The name is applied when
the room's name still came from its file name ("Screenshot 2026 10 30 at 3.37.26 pm"); a name the owner typed
is never replaced. The hanging area and width are only ever a *suggestion*: they're stored apart from the
room's wall, shown pre-filled on the room page, and the room stays unused until the owner saves them. That is
the same rule as everywhere else here: drafts are proposed, the owner decides.

What's checked before anything is kept: the area is inside the photo and big enough to hang something on,
and the width is between 20 and 2000 cm. A suggestion that fails a check keeps only the parts that passed.
"""
import base64
import io
import re
from pathlib import Path
from typing import Optional

from packages.drafting import listing
from packages.image_pipeline import rooms

MODEL = listing.MODEL
SEND_SIDE = 1568                   # the photo is sent at most this size on its long side
MIN_SHARE = 0.08                   # the area spans at least this share of the photo's width and height

SYSTEM = """You set up room photos for showing framed artwork on a wall.

Look at the photo and return:
- name: 2 to 6 words naming the room by its wall and its main furniture, in sentence case, like
  "Green wall and red door", "Terracotta loveseat" or "Beige wall and walnut sideboard". No brand names,
  no "room" or "photo", no file names or dates.
- area: the rectangle of wall where a framed piece can hang, as fractions of the photo's width and height
  (0 = left or top edge, 1 = right or bottom edge). It must be on the main wall facing the camera, clear of
  furniture, lamps, plants, shelves, windows, doors, pendant cords and anything else in front of the wall,
  with a small margin from each. Usually it's the empty wall above the sofa, sideboard, bench or chair.
- width_cm: how wide that rectangle is in real life, in centimetres. Judge it from furniture of known size
  in the photo: a three-seat sofa is about 210-230 cm, a loveseat about 150-165 cm, an armchair about 80-95 cm,
  a sideboard about 120-180 cm, a door about 80-90 cm wide and 200-210 cm tall.
- reference: the object you sized it by, in a few words ("the three-seat sofa").
- confidence: low, medium or high, for the width.
If there's no sensible place to hang a piece, return the best rectangle you can and confidence "low"."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "area", "width_cm", "reference", "confidence"],
    "properties": {
        "name": {"type": "string"},
        "area": {"type": "object", "additionalProperties": False, "required": ["left", "top", "right", "bottom"],
                 "properties": {k: {"type": "number"} for k in ("left", "top", "right", "bottom")}},
        "width_cm": {"type": "number"},
        "reference": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
}


def request(room: dict, root: Path = rooms.ROOMS, model: str = MODEL) -> dict:
    """Keyword arguments for `client.beta.messages.create`: the room photo, made small, and the instructions."""
    from PIL import Image
    im = Image.open(Path(root) / room["file"]).convert("RGB")
    im.thumbnail((SEND_SIDE, SEND_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return {
        "model": model,
        "max_tokens": 4000,
        "system": [{"type": "text", "text": SYSTEM}],
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(buf.getvalue()).decode("ascii")}},
            {"type": "text", "text": f"The photo is {im.width} x {im.height} pixels. Suggest its set-up."},
        ]}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }


def default_name(source_file: str) -> str:
    """The name a room gets from its file name when it's imported (see rooms.import_file)."""
    return Path(source_file).stem.replace("-", " ").replace("_", " ").strip().capitalize()


def named_from_file(room: dict) -> bool:
    """True while the room's name is still the one made from its file name: only then is it replaced."""
    if room.get("named_by"):
        return room["named_by"] == "file"
    return room.get("name", "") == default_name(room.get("source_file", ""))


def clean_name(text: str) -> Optional[str]:
    name = re.sub(r"\s+", " ", (text or "").strip().strip(".\"'"))[:60]
    if not name or re.search(r"\d{4}|screenshot|img_|\.(jpe?g|png|webp)", name, re.I):
        return None
    return name[0].upper() + name[1:]


def clean_area(area: dict, size) -> Optional[list]:
    """The rectangle as four corners in the photo's pixels, or None when it isn't a usable area."""
    try:
        l, t, r, b = (float(area[k]) for k in ("left", "top", "right", "bottom"))
    except (KeyError, TypeError, ValueError):
        return None
    l, t, r, b = (max(0.0, min(1.0, v)) for v in (l, t, r, b))
    if r - l < MIN_SHARE or b - t < MIN_SHARE:
        return None
    W, H = size
    return [[round(l * W, 1), round(t * H, 1)], [round(r * W, 1), round(t * H, 1)],
            [round(r * W, 1), round(b * H, 1)], [round(l * W, 1), round(b * H, 1)]]


def apply(room: dict, output: dict, model: str, cost_usd: float) -> dict:
    """The room with the suggestion recorded (and its name, if it was still the file name). Never sets the
    wall or width the room is used with: the owner confirms those on the room page."""
    r = dict(room)
    name = clean_name(output.get("name", ""))
    wall = clean_area(output.get("area") or {}, room["size"])
    width = output.get("width_cm")
    width = round(float(width), 1) if isinstance(width, (int, float)) and not isinstance(width, bool) \
        and 20 <= width <= 2000 else None
    r["suggested"] = {"name": name, "wall": wall, "wall_width_cm": width if wall else None,
                      "reference": str(output.get("reference", ""))[:120],
                      "confidence": output.get("confidence") if output.get("confidence") in ("low", "medium", "high") else "low",
                      "model": model, "cost_usd": cost_usd, "at": rooms.now()}
    if name and named_from_file(room):
        r["name"], r["named_by"] = name, "suggestion"
    r["updated_at"] = rooms.now()
    return r


def suggest(client, room: dict, root: Path = rooms.ROOMS, call=None) -> dict:
    """One room: ask, check, and return the updated room (not saved; the caller saves it under its lock)."""
    req = request(room, root)
    result = (call or listing.call_model)(client, req)
    model = result.get("model") or MODEL
    return apply(room, result["output"], model, listing.estimate_cost(result.get("usage") or {}, MODEL))
