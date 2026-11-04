"""Bring new photos in from a local folder (B-066). The owner's stand-in for Google Drive intake, which is deferred.

Put photos in inbox/ and press "Look for new photos": pressing it is the signal that the upload is complete, so
no ready marker is needed. One file is one piece. Each file is checked before any expensive processing (type,
bytes, pixels, a full decode), identified by its content hash rather than its name, and copied to the source
folder. A file already seen is recognised however it's named, so a repeated or interrupted scan adds nothing
twice. Originals are never changed: they move to inbox/imported/. A file with a problem stays where it is,
with the reason, until the owner deals with it.

The journal (.commerce-os/intake/journal.jsonl) is the source record PRD §7.3 asks for.
"""
import datetime
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import List, Optional

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
INBOX = REPO / "inbox"
INTAKE = REPO / ".commerce-os" / "intake"
POLICY_VERSION = 1
SUPPORTED = {"JPEG", "PNG", "WEBP", "TIFF", "MPO"}          # judged by the file's content, not its extension
LISTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}     # what the pipeline lists from the source folder
MAX_BYTES = 100_000_000
MAX_PIXELS = 120_000_000
MAX_BATCH = 100
DONE = "imported"


def _now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def waiting(inbox: Path = INBOX) -> List[Path]:
    inbox = Path(inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    return sorted(p for p in inbox.iterdir() if not p.name.startswith(".") and p.name != DONE)


def check(path: Path) -> dict:
    """{"format", "pixels", "bytes"} for a usable photo, or {"problem": "..."} saying why it isn't one."""
    p = Path(path)
    if p.is_symlink():
        return {"problem": "It's a shortcut, not a file. Put the photo itself here."}
    if p.is_dir():
        return {"problem": "Folders aren't read. Put each photo directly in the inbox."}
    size = p.stat().st_size
    if size == 0:
        return {"problem": "The file is empty."}
    if size > MAX_BYTES:
        return {"problem": f"It's over the {MAX_BYTES // 1_000_000} MB limit."}
    if p.suffix.lower() not in LISTED_EXT and p.suffix.lower() not in (".heic", ".heif"):
        return {"problem": "This isn't a photo type Commerce OS reads. Use JPEG, PNG, WebP or TIFF."}
    try:
        with Image.open(p) as im:                 # reads the header only, so the pixel limit comes before decoding
            fmt, (w, h) = im.format, im.size
            if fmt not in SUPPORTED:
                return {"problem": f"{fmt} isn't a type Commerce OS reads. Use JPEG, PNG, WebP or TIFF."}
            if w * h > MAX_PIXELS:
                return {"problem": f"It's {w * h // 1_000_000} megapixels, over the {MAX_PIXELS // 1_000_000} limit."}
            im.load()                             # a truncated or half-copied file fails here
    except Image.DecompressionBombError:
        return {"problem": f"It's over the {MAX_PIXELS // 1_000_000} megapixel limit."}
    except Exception:
        if p.suffix.lower() in (".heic", ".heif"):
            return {"problem": "HEIC photos can't be read yet. Export it as JPEG (or set the phone to Most Compatible)."}
        return {"problem": "The file can't be read as an image. It may be damaged or still copying."}
    return {"format": fmt, "pixels": w * h, "bytes": size}


def _free_name(folder: Path, name: str) -> str:
    stem, suffix, n, candidate = Path(name).stem, Path(name).suffix, 2, name
    while (folder / candidate).exists():
        candidate, n = f"{stem} ({n}){suffix}", n + 1
    return candidate


def _journal(root: Path) -> Path:
    return Path(root) / "journal.jsonl"


def known_hashes(source_dir: Path, root: Path) -> dict:
    """content hash -> the source file holding it, from the journal and whatever is in the source folder now."""
    known = {}
    j = _journal(root)
    if j.exists():
        for line in j.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                known[rec["sha256"]] = rec.get("source_name")
    source_dir = Path(source_dir)
    if source_dir.exists():
        for p in source_dir.iterdir():
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in LISTED_EXT:
                known[sha256(p)] = p.name
    return known


def scan(inbox: Path = INBOX, source_dir: Optional[Path] = None, root: Path = INTAKE, *, on_file=None) -> dict:
    """Bring in what's waiting. Returns {"at", "added", "duplicates", "problems", "left"} and saves it as the last
    result. `added` rows give the file's name in the source folder, which decides the item's id."""
    inbox, source_dir, root = Path(inbox), Path(source_dir), Path(root)
    files = waiting(inbox)
    batch, left = files[:MAX_BATCH], max(0, len(files) - MAX_BATCH)
    source_dir.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    done = inbox / DONE
    known = known_hashes(source_dir, root)
    result = {"at": _now(), "added": [], "duplicates": [], "problems": [], "left": left}

    def record(rec: dict):
        with _journal(root).open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    def retire(p: Path):
        done.mkdir(exist_ok=True)
        shutil.move(str(p), str(done / _free_name(done, p.name)))

    for p in batch:
        if on_file:
            on_file(p.name)
        found = check(p)
        if "problem" in found:
            result["problems"].append({"name": p.name, "reason": found["problem"]})
            continue
        digest = sha256(p)
        base = {"provider": "local_folder", "file_name": p.name, "sha256": digest, "bytes": found["bytes"],
                "format": found["format"], "pixels": found["pixels"], "policy_version": POLICY_VERSION,
                "submission_id": f"sub-{digest[:16]}", "at": _now()}
        if digest in known:
            record(dict(base, outcome="duplicate", source_name=known[digest]))
            result["duplicates"].append({"name": p.name, "same_as": known[digest]})
            retire(p)
            continue
        name = _free_name(source_dir, p.name)
        part = source_dir / f".{name}.part"       # dot-named, so nothing lists it until it's whole
        shutil.copyfile(p, part)
        if sha256(part) != digest:
            part.unlink()
            result["problems"].append({"name": p.name, "reason": "It changed while being copied. Try again."})
            continue
        os.replace(part, source_dir / name)
        known[digest] = name
        record(dict(base, outcome="added", source_name=name))
        result["added"].append({"name": p.name, "source_name": name})
        retire(p)
    (root / "last.json").write_text(json.dumps(result, indent=1))
    return result


def status(inbox: Path = INBOX, root: Path = INTAKE) -> dict:
    last = Path(root) / "last.json"
    return {"folder": str(Path(inbox)), "waiting": len(waiting(inbox)),
            "last": json.loads(last.read_text()) if last.exists() else None}
