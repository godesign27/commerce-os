"""Deliver a listing's approved image files before its product is written, so a product never points at a missing one.

Each file's name holds its content hash, so delivering it twice changes nothing. For now the destination is a local
folder standing in for the store's image storage: real upload isn't authorized (BACKLOG B-025).
"""
import hashlib
import os
import shutil
from pathlib import Path
from typing import Dict, List


class DeliveryError(Exception):
    """A file couldn't be delivered. Safe to show, and the product wasn't written."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class LocalAssetStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _target(self, key: str) -> Path:
        target = (self.root / key.lstrip("/")).resolve()
        if self.root.resolve() not in target.parents:
            raise DeliveryError(f"{key} is outside the image store")
        return target

    def deliver(self, assets: List[dict], files: Dict[str, dict]) -> List[dict]:
        """`assets` are the change set's; `files` maps derivative id -> {"file", "sha256"}, the approved bytes."""
        out = []
        for a in assets:
            source = files.get(a["derivative_id"])
            if not source or not Path(source["file"]).exists():
                raise DeliveryError(f"The file for {a['derivative_id']} is missing.")
            if _sha256(source["file"]) != source["sha256"]:
                raise DeliveryError(f"The file for {a['derivative_id']} isn't the one you approved.")
            target = self._target(a["destination_key"])
            if target.exists() and _sha256(target) == source["sha256"]:
                out.append({"derivative_id": a["derivative_id"], "destination_key": a["destination_key"], "result": "already_present"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(f".{target.name}.part")
            shutil.copyfile(source["file"], part)
            os.replace(part, target)
            out.append({"derivative_id": a["derivative_id"], "destination_key": a["destination_key"], "result": "written"})
        return out
