"""Find the artwork in a photo, then straighten and crop it (B-053 prototype).

Cropping is consequential (contracts: crop derivatives are always marked consequential): a reviewer must
accept every crop before it's used. So this module only *proposes*: corners, a confidence check, a
review image with the outline drawn on the photo, and the straightened crop. The original is never
written.

How detection works, for a painting photographed on a contrasting surface (floor, table):
1. Downscale, and take colour saturation. Wood and tabletops are far more saturated than most painted
   surfaces and canvases; the threshold between them is chosen per photo (Otsu's method).
2. Trim thin bridges to the background (erode), keep the region connected to the photo's centre, and
   grow it back (dilate).
3. Fit a straight line along the middle 60% of each edge, ignoring outliers, and intersect the lines.
   Corners come from the lines, not from the region's extreme pixels, so a leak at one corner can't
   drag the outline.
Photos where this doesn't hold (white paper on a white table, a busy background) fail the confidence
check and are flagged for the reviewer to place the corners by hand.
"""
import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from packages.image_pipeline.framing import REPO, sha256_file

RECIPES = REPO / "resources" / "image-recipes"
Point = Tuple[float, float]


def load_recipe(recipe_id: str = "crop-perspective") -> dict:
    return json.loads((RECIPES / f"{recipe_id}.json").read_text())


# ---------------------------------------------------------------- pure geometry (stdlib)

def otsu(hist: List[int]) -> int:
    """The threshold that best separates a 256-bin histogram into two classes."""
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    wb = sb = 0
    best_var, best_t = -1.0, 0
    for t in range(256):
        wb += hist[t]
        if wb == 0:
            continue
        wf = total - wb
        if wf == 0:
            break
        sb += t * hist[t]
        mb, mf = sb / wb, (sum_all - sb) / wf
        var = wb * wf * (mb - mf) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def fit_line(pairs: List[Point], rounds: int = 3) -> Tuple[float, float]:
    """Robust least squares for v = a*u + b: refit after dropping points far from the line."""
    if len(pairs) < 2:
        raise ValueError("not enough edge points")
    for _ in range(rounds):
        n = len(pairs)
        mu = sum(u for u, _ in pairs) / n
        mv = sum(v for _, v in pairs) / n
        suu = sum((u - mu) ** 2 for u, _ in pairs) or 1e-9
        a = sum((u - mu) * (v - mv) for u, v in pairs) / suu
        b = mv - a * mu
        res = [abs(v - (a * u + b)) for u, v in pairs]
        mad = statistics.median(res) or 0.5
        kept = [p for p, r in zip(pairs, res) if r <= 3 * mad + 1]
        if len(kept) < 2:
            break
        pairs = kept
    return a, b


def intersect(vertical: Tuple[float, float], horizontal: Tuple[float, float]) -> Point:
    """x = a1*y + b1 meets y = a2*x + b2."""
    a1, b1 = vertical
    a2, b2 = horizontal
    denom = 1 - a1 * a2
    if abs(denom) < 1e-9:
        raise ValueError("edges are parallel")
    x = (a1 * b2 + b1) / denom
    return x, a2 * x + b2


def polygon_area(pts: List[Point]) -> float:
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))) / 2


def is_convex(pts: List[Point]) -> bool:
    signs = set()
    for i in range(len(pts)):
        (x1, y1), (x2, y2), (x3, y3) = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        signs.add((x2 - x1) * (y3 - y2) - (y2 - y1) * (x3 - x2) > 0)
    return len(signs) == 1


def edge_lengths(q: List[Point]) -> dict:
    d = lambda p, r: math.hypot(p[0] - r[0], p[1] - r[1])
    tl, tr, br, bl = q
    return {"top": d(tl, tr), "right": d(tr, br), "bottom": d(bl, br), "left": d(tl, bl)}


def output_size(q: List[Point]) -> Tuple[int, int]:
    e = edge_lengths(q)
    return round((e["top"] + e["bottom"]) / 2), round((e["left"] + e["right"]) / 2)


def inset(q: List[Point], ratio: float) -> List[Point]:
    """Move each corner toward the centre, to drop a sliver of background along the edges."""
    cx = sum(p[0] for p in q) / 4
    cy = sum(p[1] for p in q) / 4
    return [(x + (cx - x) * ratio, y + (cy - y) * ratio) for x, y in q]


@dataclass
class Check:
    ok: bool
    reasons: List[str] = field(default_factory=list)
    region_fill: float = 0.0
    area_fraction: float = 0.0


def check_quad(q: List[Point], image_size: Tuple[int, int], region_pixels: int, recipe: dict) -> Check:
    """Confidence: a sensible, convex outline that the detected region actually fills."""
    rules = recipe["confidence"]
    w, h = image_size
    reasons = []
    area = polygon_area(q)
    fill = region_pixels / area if area else 0.0
    frac = area / (w * h)
    if not is_convex(q):
        reasons.append("outline is not convex")
    if not rules["min_area_fraction"] <= frac <= rules["max_area_fraction"]:
        reasons.append(f"outline covers {frac:.0%} of the photo")
    if fill < rules["min_region_fill"]:
        reasons.append(f"detected region fills only {fill:.0%} of the outline")
    e = edge_lengths(q)
    for a, b in (("top", "bottom"), ("left", "right")):
        if min(e[a], e[b]) / max(e[a], e[b]) < rules["min_opposite_edge_ratio"]:
            reasons.append(f"{a} and {b} edges differ too much (strong perspective)")
    margin = rules["edge_margin_px"]
    if any(x < -margin or y < -margin or x > w + margin or y > h + margin for x, y in q):
        reasons.append("a corner falls outside the photo")
    return Check(not reasons, reasons, round(fill, 3), round(frac, 3))


# ---------------------------------------------------------------- detection and rectification (Pillow)

@dataclass
class Proposal:
    corners: List[Point]          # tl, tr, br, bl in original-photo pixels (after EXIF rotation)
    threshold: int
    check: Check
    method: str = "saturation-otsu-edge-fit"

    def as_dict(self) -> dict:
        d = asdict(self)
        d["corners"] = [[round(x, 1), round(y, 1)] for x, y in self.corners]
        return d


def open_photo(path: Path):
    from PIL import Image, ImageOps
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def detect(photo, recipe: dict) -> Proposal:
    from PIL import ImageDraw, ImageFilter
    det = recipe["detection"]
    W, H = photo.size
    scale = det["work_size_px"] / max(W, H)
    small = photo.resize((max(1, round(W * scale)), max(1, round(H * scale))))
    sat = small.convert("HSV").split()[1]
    t = otsu(sat.histogram())
    k = det["trim_px"]
    mask = (sat.point(lambda v: 255 if v <= t else 0)
            .filter(ImageFilter.MedianFilter(det["median_px"]))
            .filter(ImageFilter.MinFilter(k)))
    w, h = mask.size
    seed = (w // 2, h // 2)
    if mask.getpixel(seed) != 255:
        raise ValueError("the centre of the photo isn't on the artwork")
    ImageDraw.floodfill(mask, seed, 128)
    region = mask.point(lambda v: 255 if v == 128 else 0).filter(ImageFilter.MaxFilter(k))
    px = region.load()
    rows, cols, count = {}, {}, 0
    for y in range(h):
        xs = [x for x in range(w) if px[x, y]]
        if xs:
            rows[y] = (xs[0], xs[-1])
            count += len(xs)
    for x in range(w):
        ys = [y for y in range(h) if px[x, y]]
        if ys:
            cols[x] = (ys[0], ys[-1])
    lo, hi = det["edge_middle"]

    def middle(keys):
        keys = sorted(keys)
        return keys[int(len(keys) * lo):int(len(keys) * hi)]

    left = fit_line([(y, rows[y][0]) for y in middle(rows)])
    right = fit_line([(y, rows[y][1]) for y in middle(rows)])
    top = fit_line([(x, cols[x][0]) for x in middle(cols)])
    bottom = fit_line([(x, cols[x][1]) for x in middle(cols)])
    small_q = [intersect(left, top), intersect(right, top), intersect(right, bottom), intersect(left, bottom)]
    check = check_quad(small_q, (w, h), count, recipe)
    q = [(x / scale, y / scale) for x, y in small_q]
    return Proposal(q, t, check)


def rectify(photo, corners: List[Point], recipe: dict):
    """Straighten and crop: map the outline onto an upright rectangle."""
    from PIL import Image
    q = inset(corners, recipe["output"]["inset_ratio"])
    size = output_size(q)
    tl, tr, br, bl = q
    data = (*tl, *bl, *br, *tr)                    # Pillow QUAD order: UL, LL, LR, UR
    return photo.transform(size, Image.QUAD, data, resample=Image.BICUBIC)


def review_image(photo, proposal: Proposal, width: int = 900):
    """The photo with the proposed outline drawn on it, for the reviewer."""
    from PIL import ImageDraw
    s = width / photo.width
    im = photo.resize((width, round(photo.height * s)))
    q = [(x * s, y * s) for x, y in proposal.corners]
    d = ImageDraw.Draw(im)
    colour = (0, 200, 80) if proposal.check.ok else (230, 40, 40)
    d.line(q + [q[0]], fill=colour, width=4)
    for x, y in q:
        d.ellipse((x - 8, y - 8, x + 8, y + 8), outline=colour, width=3)
    return im


def crop_artwork(source: Path, out_dir: Path, recipe_id: str = "crop-perspective",
                 corners: Optional[List[Point]] = None) -> dict:
    """Propose a crop. Pass `corners` to use a reviewer's corrected outline instead of detection."""
    recipe = load_recipe(recipe_id)
    source, out_dir = Path(source), Path(out_dir)
    before = sha256_file(source)
    photo = open_photo(source)
    if corners is None:
        proposal = detect(photo, recipe)
    else:
        proposal = Proposal([tuple(c) for c in corners], -1,
                            check_quad([tuple(c) for c in corners], photo.size, 0, {**recipe, "confidence": {
                                **recipe["confidence"], "min_region_fill": 0}}), method="manual")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{source.stem}.{recipe['id']}-v{recipe['version']}"
    cropped_path, review_path = out_dir / f"{stem}.png", out_dir / f"{stem}.review.jpg"
    if source.resolve() in (cropped_path.resolve(), review_path.resolve()):
        raise ValueError("refusing to overwrite the original")
    rectify(photo, proposal.corners, recipe).save(cropped_path, "PNG", optimize=True)
    review_image(photo, proposal).save(review_path, "JPEG", quality=85)
    if sha256_file(source) != before:
        raise RuntimeError("the original changed during cropping")
    return {
        "recipe": recipe["id"], "recipe_version": recipe["version"],
        "consequential": True, "accepted": False,       # a reviewer must accept before use
        "needs_review": True if not proposal.check.ok else "accept_or_adjust",
        "source": source.name, "source_sha256": before,
        "output": str(cropped_path), "output_sha256": sha256_file(cropped_path),
        "review_image": str(review_path),
        "proposal": proposal.as_dict(),
    }
