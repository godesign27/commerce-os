"""Gate 3 for each listing: the owner's approval of one exact storefront change set (PRD §13, B-064).

    .commerce-os/approvals/<item>.jsonl   append-only: {"event": "approved", "approval", "change_set"} and
                                          {"event": "out_of_date", "approval_id", "changes", "at"}

An approval binds the sealed change set's hash and every binding in packages/policy (revision, asset
manifest, mapping version, schema fingerprint, status). It is never edited or carried over: whenever the
listing is read, its change set is rebuilt and compared. If anything differs, the approval is out of date,
that is recorded once (here and in the audit trail) with what changed, and a new approval is needed.
Nothing here writes to a storefront; publishing is Phase 3, and Gate 4 checks all of this again.
"""
import json
import threading
import uuid
from pathlib import Path
from typing import List, Optional

from packages import policy
from packages.adapters import artstore_map
from packages.adapters.contract import approval_issues
from packages.drafting import brand
from packages.drafting.audit import Audit

REPO = Path(__file__).resolve().parents[2]
APPROVALS = REPO / ".commerce-os" / "approvals"
_LOCK = threading.Lock()


class ApprovalError(ValueError):
    """The approval can't be recorded; nothing was saved."""


class Approvals:
    def __init__(self, root: Path = APPROVALS, audit: Optional[Audit] = None):
        self.root = Path(root)
        self.audit = audit or Audit()

    def _path(self, item: str) -> Path:
        if not item or "/" in item or item.startswith("."):
            raise ValueError(f"bad item id {item!r}")
        return self.root / f"{item}.jsonl"

    def records(self, item: str) -> List[dict]:
        p = self._path(item)
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []

    def _append(self, item: str, rec: dict):
        self.root.mkdir(parents=True, exist_ok=True)
        with self._path(item).open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    def latest(self, item: str) -> Optional[dict]:
        approved = [r for r in self.records(item) if r["event"] == "approved"]
        return approved[-1] if approved else None

    def approve(self, item: str, change_set: dict, *, seen_hash: str, status: str, actor_id: str) -> dict:
        """Record the owner's approval of the change set they were shown. Refused when the listing has changed
        since (`seen_hash`), when anything but image delivery still blocks it, or when a policy rule fails."""
        if seen_hash != change_set["change_set_hash"]:
            raise ApprovalError("the listing changed since you looked at it: check the preview again, then approve")
        if status != change_set["requested_status"]:
            raise ApprovalError(f"this change set goes in as {change_set['requested_status']!r}, not {status!r}")
        if not artstore_map.approvable(change_set):
            left = [b["question"] for b in change_set["blockers"]
                    if b["severity"] == "blocking" and b["target"] not in artstore_map.AFTER_APPROVAL]
            raise ApprovalError("not ready to approve: " + " ".join(left))
        approval = {
            "contract": "approval", "contract_version": 1,
            "approval_id": f"apr-{uuid.uuid4().hex[:16]}",
            "actor": {"kind": "human", "id": actor_id, "role": "approver"},
            "approved_at": brand.now(),
            "change_set_id": change_set["change_set_id"],
            "prepared_by": dict(artstore_map.PREPARED_BY),
            **{k: change_set[k] for k in policy.APPROVAL_BINDINGS},
        }
        problems = [str(v) for v in policy.validate(change_set)]
        problems += [str(v) for v in policy.validate(approval, related=[change_set])]
        problems += [f"{i.code}: {i.message}" for i in approval_issues(change_set, approval)]
        if problems:
            raise ApprovalError("; ".join(problems))
        with _LOCK:
            self._append(item, {"event": "approved", "at": approval["approved_at"], "approval": approval,
                                "change_set": change_set})
        self.audit.append(item, "storefront_approved", f"Approved for {change_set['destination']} as "
                          f"{status} (change set {change_set['change_set_hash'][:12]})", by=actor_id,
                          change_set_id=change_set["change_set_id"], change_set_hash=change_set["change_set_hash"],
                          approval_id=approval["approval_id"])
        return approval

    def status(self, item: str, current: dict) -> dict:
        """none, current or out_of_date, for the change set the listing gives now. An approval that has
        stopped matching is recorded as out of date once, with what changed."""
        last = self.latest(item)
        if not last:
            return {"state": "none", "approval": None, "changes": []}
        approval, approved_cs = last["approval"], last["change_set"]
        if approved_cs["change_set_hash"] == current["change_set_hash"]:
            return {"state": "current", "approval": approval, "changes": []}
        changes = artstore_map.differences(approved_cs, current)
        with _LOCK:
            recorded = any(r["event"] == "out_of_date" and r["approval_id"] == approval["approval_id"]
                           for r in self.records(item))
            if not recorded:
                at = brand.now()
                self._append(item, {"event": "out_of_date", "at": at, "approval_id": approval["approval_id"],
                                    "changes": changes, "now_hash": current["change_set_hash"]})
        if not recorded:
            self.audit.append(item, "approval_out_of_date", "Storefront approval out of date: changed "
                              + ", ".join(changes), by="commerce-os", approval_id=approval["approval_id"],
                              changes=changes)
        return {"state": "out_of_date", "approval": approval, "changes": changes}
