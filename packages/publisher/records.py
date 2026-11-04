"""What has happened to each publish, in append-only files, shared by the dashboard and the worker.

    .commerce-os/publications/<item>.jsonl   one event per line; the last with a "state" is the state now
    .commerce-os/publications/kill_switch.json   the owner's stop switch
    .commerce-os/publications/worker.json    the worker's heartbeat

The dashboard can only ask (a QUEUED event) and read. Only the worker moves a publish past QUEUED. Stdlib only.
"""
import datetime
import fcntl
import json
import os
from pathlib import Path
from typing import List, Optional

from packages.drafting.audit import Audit

QUEUED, WRITING, SUCCEEDED, FAILED, UNKNOWN = "QUEUED", "WRITING", "SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN"
HEARTBEAT_SECONDS = 15


class PublishError(ValueError):
    """Why a publish can't be asked for, in words for the owner. Nothing was queued."""


def _now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _seconds_since(at: str, now: Optional[str] = None) -> float:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    later = datetime.datetime.strptime(now, fmt) if now else datetime.datetime.utcnow()
    return (later - datetime.datetime.strptime(at, fmt)).total_seconds()


class Publications:
    def __init__(self, root: Path, audit: Optional[Audit] = None, clock=_now):
        self.root, self.audit, self.clock = Path(root), audit or Audit(Path(root) / "audit"), clock

    def _path(self, item: str) -> Path:
        if not item or "/" in item or item.startswith("."):
            raise ValueError(f"bad item id {item!r}")
        return self.root / f"{item}.jsonl"

    def events(self, item: str) -> List[dict]:
        p = self._path(item)
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []

    def append(self, item: str, event: str, state: Optional[str] = None, **data) -> dict:
        rec = {"at": self.clock(), "event": event, **data}
        if state:
            rec["state"] = state
        self.root.mkdir(parents=True, exist_ok=True)
        with self._path(item).open("a") as f:      # the worker and the dashboard are separate processes
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec

    def state(self, item: str) -> Optional[str]:
        return next((e["state"] for e in reversed(self.events(item)) if e.get("state")), None)

    def latest(self, item: str, event: str) -> Optional[dict]:
        return next((e for e in reversed(self.events(item)) if e["event"] == event), None)

    def items(self) -> List[str]:
        return sorted(p.stem for p in self.root.glob("*.jsonl")) if self.root.exists() else []

    def in_state(self, state: str) -> List[str]:
        return [i for i in self.items() if self.state(i) == state]

    def recheck_wanted(self, item: str) -> bool:
        for e in reversed(self.events(item)):
            if e["event"] == "recheck_requested":
                return True
            if e.get("state") or e["event"] == "rechecked":
                return False
        return False

    # ------------------------------------------------------------ what the dashboard may do
    def request(self, item: str, change_set: dict, approval: dict, by: str) -> dict:
        state = self.state(item)
        if state in (QUEUED, WRITING):
            raise PublishError("This piece is already being published.")
        if state == UNKNOWN:
            raise PublishError("The last publish has an unknown outcome. Check again first: publishing now could add it twice.")
        if state == SUCCEEDED:
            raise PublishError("This piece is already published. Only new products can go in for now.")
        if self.kill_switch()["on"]:
            raise PublishError("Writing is switched off, so nothing was queued.")
        rec = self.append(item, "queued", QUEUED, by=by, change_set_id=change_set["change_set_id"],
                          change_set_hash=change_set["change_set_hash"], approval_id=approval["approval_id"])
        self.audit.append(item, "publish_requested", f"Asked to publish change set {change_set['change_set_hash'][:12]}", by=by)
        return rec

    def ask_recheck(self, item: str, by: str):
        if self.state(item) != UNKNOWN:
            raise PublishError("There's nothing to check: this publish's outcome is known.")
        self.append(item, "recheck_requested", by=by)

    # ------------------------------------------------------------ the kill switch
    def kill_switch(self) -> dict:
        """On means nothing is written. Anything unreadable counts as on: failing safe."""
        if os.environ.get("COMMERCE_OS_WRITES_DISABLED", "").strip().lower() in ("1", "true", "yes"):
            return {"on": True, "forced": True, "at": None, "by": "the COMMERCE_OS_WRITES_DISABLED setting"}
        p = self.root / "kill_switch.json"
        if not p.exists():
            return {"on": False, "forced": False, "at": None, "by": None}
        try:
            d = json.loads(p.read_text())
            return {"on": d["on"] is not False, "forced": False, "at": d.get("at"), "by": d.get("by")}
        except (ValueError, KeyError, TypeError):
            return {"on": True, "forced": False, "at": None, "by": "an unreadable switch file"}

    def set_kill_switch(self, on: bool, by: str) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "kill_switch.tmp"
        tmp.write_text(json.dumps({"on": bool(on), "at": self.clock(), "by": by}))
        os.replace(tmp, self.root / "kill_switch.json")
        return self.kill_switch()

    # ------------------------------------------------------------ the worker's heartbeat
    def beat(self, ok: bool, reason: Optional[str] = None):
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f"worker.{os.getpid()}.tmp"
        tmp.write_text(json.dumps({"at": self.clock(), "ok": ok, "reason": reason}))
        os.replace(tmp, self.root / "worker.json")

    def worker(self) -> dict:
        p = self.root / "worker.json"
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            return {"running": False, "ok": False, "reason": None}
        return {"running": _seconds_since(d["at"], self.clock()) <= HEARTBEAT_SECONDS, "ok": bool(d.get("ok")),
                "reason": d.get("reason")}
