"""Deliver a listing's approved image files before its product is written, so a product never points at a missing one.

Each file's name holds its content hash, so delivering it twice changes nothing. The destination is a local folder
standing in for the store's image storage, or, once the owner has turned the live store on, the store's own bucket.
"""
import hashlib
import json
import mimetypes
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote


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


def _send(method: str, url: str, headers: dict, body: bytes) -> Tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError) as e:     # the message is about the network, and holds no login
        raise DeliveryError(f"Couldn't reach the store's image storage ({type(e).__name__}).")


class SupabaseAssetStore:
    """The store's private bucket, as an upload-only user. It can add files and nothing else: never the secret key,
    and never an overwrite. Each image needs a record beside it (_meta/<path>.json) or the store won't serve it."""

    OWNER = "commerce-os"

    def __init__(self, url: str, key: str, email: str, password: str, bucket: str, send: Optional[Callable] = None):
        self.base, self.key, self.email, self.password, self.bucket = url.rstrip("/"), key, email, password, bucket
        self.send = send or _send

    def sign_in(self) -> str:
        status, body = self.send("POST", f"{self.base}/auth/v1/token?grant_type=password",
                                 {"apikey": self.key, "Content-Type": "application/json"},
                                 json.dumps({"email": self.email, "password": self.password}).encode())
        token = None
        if status == 200:
            try:
                token = json.loads(body).get("access_token")
            except ValueError:
                pass
        if not token:
            raise DeliveryError("The upload login was refused, so nothing was uploaded.")
        return token

    @staticmethod
    def object_name(destination_key: str) -> str:
        prefix = "/objects/uploads/"
        name = destination_key[len(prefix):] if destination_key.startswith(prefix) else ""
        if not name or "/" in name or ".." in name:
            raise DeliveryError(f"{destination_key} isn't in the store's uploads folder.")
        return f"uploads/{name}"

    def _add(self, token: str, name: str, body: bytes, content_type: str) -> str:
        """Add one file. Its name holds its content hash, so one already there is the same file."""
        status, reply = self.send("POST", f"{self.base}/storage/v1/object/{quote(self.bucket)}/{quote(name)}",
                                  {"apikey": self.key, "Authorization": f"Bearer {token}", "Content-Type": content_type}, body)
        if status in (200, 201):
            return "written"
        if status == 409 or (status == 400 and b"Duplicate" in reply):
            return "already_present"
        if status in (401, 403):
            raise DeliveryError("The store refused the upload: check the upload rule in the runbook.")
        raise DeliveryError(f"The store's image storage answered {status}, so the product wasn't written.")

    def deliver(self, assets: List[dict], files: Dict[str, dict]) -> List[dict]:
        """The same promise as the local store: every file checked against what was approved, or nothing is written."""
        token, out = self.sign_in(), []
        record = json.dumps({"custom:aclPolicy": json.dumps({"owner": self.OWNER, "visibility": "public"})}).encode()
        for a in assets:
            source = files.get(a["derivative_id"])
            if not source or not Path(source["file"]).exists():
                raise DeliveryError(f"The file for {a['derivative_id']} is missing.")
            data = Path(source["file"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != source["sha256"]:
                raise DeliveryError(f"The file for {a['derivative_id']} isn't the one you approved.")
            name = self.object_name(a["destination_key"])
            kind = mimetypes.guess_type(str(source["file"]))[0] or "application/octet-stream"
            result = self._add(token, name, data, kind)
            self._add(token, f"_meta/{name}.json", record, "application/json")
            out.append({"derivative_id": a["derivative_id"], "destination_key": a["destination_key"], "result": result})
        return out
