"""Framed listing image: artwork, white mat, thin oak frame and a soft shadow on a near-white canvas (B-050).

`layout()` is pure arithmetic (stdlib only, unit-tested everywhere). `render()` needs Pillow, from the
project environment (`.venv`, requirements.txt). The artwork's pixels are only resized, never edited,
and the original file is never modified.
"""
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
RECIPES = REPO / "resources" / "image-recipes"
ASSETS = REPO / ".commerce-os" / "assets"

Box = Tuple[int, int, int, int]   # left, top, right, bottom (right/bottom exclusive)


def load_recipe(recipe_id: str = "framed-oak-white-mat") -> dict:
    return json.loads((RECIPES / f"{recipe_id}.json").read_text())


@dataclass(frozen=True)
class Layout:
    canvas: Tuple[int, int]
    orientation: str    # portrait, square or landscape: decides the canvas shape
    frame: Box          # outer edge of the frame
    opening: Box        # inside edge of the frame = the mat's outer edge
    art: Box            # where the artwork sits on the mat
    frame_px: int

    def as_dict(self) -> dict:
        return asdict(self)


def orientation(art_size: Tuple[int, int], recipe: dict) -> str:
    """Square within the recipe's tolerance; otherwise portrait or landscape."""
    w, h = art_size
    if abs(w - h) / max(w, h) <= recipe["canvas"]["square_tolerance"]:
        return "square"
    return "portrait" if h > w else "landscape"


def layout(art_size: Tuple[int, int], recipe: dict, canvas_width: Optional[int] = None) -> Layout:
    """Where everything goes, for an artwork of `art_size`, on a canvas shaped like the artwork."""
    aw, ah = art_size
    if aw <= 0 or ah <= 0:
        raise ValueError("artwork has no size")
    shape = orientation(art_size, recipe)
    place = recipe["canvas"]["orientations"][shape]
    cw, ch = place["size_px"]
    if canvas_width:
        cw, ch = canvas_width, round(canvas_width * ch / cw)
    mat, fr = recipe["mat"], recipe["frame"]
    aspect = ah / aw
    # Outer frame size as multiples of the displayed artwork width W.
    outer_w_per_w = 1 + 2 * mat["side_ratio"] + 2 * fr["width_ratio"]
    outer_h_per_w = aspect + mat["top_ratio"] + mat["bottom_ratio"] + 2 * fr["width_ratio"]
    w = min(place["max_width_ratio"] * cw / outer_w_per_w, place["max_height_ratio"] * ch / outer_h_per_w)
    art_w, art_h = round(w), round(w * aspect)
    f = max(1, round(w * fr["width_ratio"]))
    side, top, bottom = (round(w * mat[k]) for k in ("side_ratio", "top_ratio", "bottom_ratio"))
    outer_w = art_w + 2 * side + 2 * f
    outer_h = art_h + top + bottom + 2 * f
    left = (cw - outer_w) // 2
    top_edge = round((ch - outer_h) / 2 + place["vertical_offset_ratio"] * ch)
    frame = (left, top_edge, left + outer_w, top_edge + outer_h)
    opening = (left + f, top_edge + f, left + outer_w - f, top_edge + outer_h - f)
    art = (opening[0] + side, opening[1] + top, opening[0] + side + art_w, opening[1] + top + art_h)
    return Layout((cw, ch), shape, frame, opening, art, f)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- rendering (Pillow)

def _open_artwork(path: Path):
    from PIL import Image, ImageCms, ImageOps
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)               # phone photos store rotation in EXIF
    icc = im.info.get("icc_profile")
    if icc:                                        # convert to sRGB so colours match on the web
        try:
            import io
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            im = ImageCms.profileToProfile(im.convert("RGB"), src, dst, outputMode="RGB")
        except Exception:                          # an unreadable profile: keep pixels as they are
            im = im.convert("RGB")
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        base = Image.new("RGB", rgba.size, (255, 255, 255))
        base.paste(rgba, mask=rgba.split()[3])
        im = base
    return im.convert("RGB")


def _oak_bar(recipe: dict, length: int, thickness: int):
    """A straight oak strip `length` x `thickness`, from the texture asset or a flat fallback."""
    from PIL import Image
    tex = recipe["frame"]["texture"]
    path = ASSETS / f"{tex['asset']}.png"
    if path.exists():
        b = tex["bar"]
        bar = Image.open(path).convert("RGB").crop((b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]))
        if tex.get("tone_rgb"):                   # match the house oak colour, keep the grain
            from PIL import ImageStat
            mean = ImageStat.Stat(bar).mean
            gains = [t / max(m, 1) for t, m in zip(tex["tone_rgb"], mean)]
            bar = Image.merge("RGB", [ch.point(lambda v, g=g: min(255, round(v * g)))
                                      for ch, g in zip(bar.split(), gains)])
        # Tile along the length so the grain isn't stretched on large frames.
        scale = thickness / bar.height
        seg = bar.resize((max(1, round(bar.width * scale)), thickness), Image.LANCZOS)
        strip = Image.new("RGB", (length, thickness))
        x, flip = 0, False
        while x < length:
            strip.paste(seg.transpose(Image.FLIP_LEFT_RIGHT) if flip else seg, (x, 0))
            x += seg.width
            flip = not flip                       # mirror alternate tiles: no visible seams
        return strip
    return Image.new("RGB", (length, thickness), tuple(recipe["frame"]["fallback_rgb"]))


def _shade(im, factor: float):
    from PIL import ImageEnhance
    return ImageEnhance.Brightness(im).enhance(factor) if factor != 1.0 else im


def _frame_image(recipe: dict, size: Tuple[int, int], f: int):
    """The frame as an RGBA image: four oak bars with mitred corners, transparent opening."""
    from PIL import Image, ImageDraw
    w, h = size
    shade = recipe["frame"]["shade"]
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    horizontal = _oak_bar(recipe, w, f)
    vertical = _oak_bar(recipe, h, f).rotate(90, expand=True)
    pieces = {
        "top": (_shade(horizontal, shade["top"]), (0, 0), [(0, 0), (w, 0), (w - f, f), (f, f)]),
        "bottom": (_shade(horizontal.rotate(180), shade["bottom"]), (0, h - f),
                   [(f, h - f), (w - f, h - f), (w, h), (0, h)]),
        "left": (_shade(vertical, shade["left"]), (0, 0), [(0, 0), (f, f), (f, h - f), (0, h)]),
        "right": (_shade(vertical.rotate(180), shade["right"]), (w - f, 0),
                  [(w - f, f), (w, 0), (w, h), (w - f, h - f)]),
    }
    for piece, at, polygon in pieces.values():
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        layer.paste(piece.convert("RGBA"), at)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).polygon(polygon, fill=255)
        out.paste(layer, (0, 0), mask)
    return out


def render(source: Path, recipe: dict, canvas_width: Optional[int] = None):
    """Returns (PIL image, layout). Never writes to `source`."""
    from PIL import Image, ImageDraw, ImageFilter
    art = _open_artwork(Path(source))
    lay = layout(art.size, recipe, canvas_width)
    cw, ch = lay.canvas
    canvas = Image.new("RGB", (cw, ch), tuple(recipe["canvas"]["background_rgb"]))

    # Soft drop shadow under the frame.
    sh = recipe["shadow"]
    shadow = Image.new("L", (cw, ch), 0)
    dy = round(sh["offset_y_ratio"] * ch)
    fl, ft, fr_, fb = lay.frame
    ImageDraw.Draw(shadow).rectangle((fl, ft + dy, fr_ - 1, fb - 1 + dy), fill=round(255 * sh["opacity"]))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, sh["blur_ratio"] * cw)))
    canvas.paste(Image.new("RGB", (cw, ch), (0, 0, 0)), (0, 0), shadow)

    # Mat, with the frame's soft inner shadow along its top and left edges.
    mat = recipe["mat"]
    ol, ot, or_, ob = lay.opening
    canvas.paste(Image.new("RGB", (or_ - ol, ob - ot), tuple(mat["rgb"])), (ol, ot))
    inner = mat["inner_shadow"]
    size = max(1, round(inner["size_ratio"] * (lay.art[2] - lay.art[0])))
    grad = Image.new("L", (or_ - ol, ob - ot), 0)
    gd = ImageDraw.Draw(grad)
    for i in range(size):
        a = round(255 * inner["opacity"] * (1 - i / size) ** 2)
        gd.line((0, i, or_ - ol, i), fill=a)
        gd.line((i, 0, i, ob - ot), fill=a)
    canvas.paste(Image.new("RGB", grad.size, (0, 0, 0)), (ol, ot), grad)

    # Artwork: resized only.
    al, at, ar, ab = lay.art
    canvas.paste(art.resize((ar - al, ab - at), Image.LANCZOS), (al, at))

    # Frame on top.
    frame = _frame_image(recipe, (fr_ - fl, fb - ft), lay.frame_px)
    canvas.paste(frame, (fl, ft), frame)
    return canvas, lay


def frame_artwork(source: Path, out: Path, recipe_id: str = "framed-oak-white-mat",
                  canvas_width: Optional[int] = None) -> dict:
    """Render, save, and return a derivative record (source and output hashes, recipe and version)."""
    recipe = load_recipe(recipe_id)
    source, out = Path(source), Path(out)
    if out.resolve() == source.resolve():
        raise ValueError("refusing to overwrite the original")
    before = sha256_file(source)
    image, lay = render(source, recipe, canvas_width)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, recipe["output"]["format"], optimize=True)
    if sha256_file(source) != before:
        raise RuntimeError("the original changed during rendering")
    return {
        "recipe": recipe["id"], "recipe_version": recipe["version"], "consequential": recipe["consequential"],
        "source": str(source.name), "source_sha256": before,
        "output": str(out), "output_sha256": sha256_file(out),
        "texture": "asset" if (ASSETS / f"{recipe['frame']['texture']['asset']}.png").exists() else "fallback",
        "layout": lay.as_dict(),
    }
