#!/usr/bin/env python3
"""Make the framed listing image for one artwork file (B-050 prototype).

Usage:
    .venv/bin/python scripts/frame_artwork.py <artwork image> [--out PATH] [--width 1024]

Writes a new PNG (default: .commerce-os/derivatives/<name>.framed-v<version>.png, gitignored) and prints
the derivative record. The original is never modified. Needs the project environment:
    python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from packages.image_pipeline.framing import frame_artwork, load_recipe  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source")
    ap.add_argument("--out")
    ap.add_argument("--width", type=int, help="canvas width in pixels (default from the recipe)")
    ap.add_argument("--recipe", default="framed-oak-white-mat")
    args = ap.parse_args(argv)
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise SystemExit("Pillow isn't installed. Run: python3 -m venv .venv && "
                         ".venv/bin/python -m pip install -r requirements.txt")
    recipe = load_recipe(args.recipe)
    source = Path(args.source)
    out = Path(args.out) if args.out else (REPO / ".commerce-os" / "derivatives" /
                                           f"{source.stem}.{recipe['id']}-v{recipe['version']}.png")
    record = frame_artwork(source, out, args.recipe, args.width)
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
