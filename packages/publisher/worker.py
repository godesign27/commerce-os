"""The publishing worker's steps: Gate 4, delivery, the write, the read-back, and recovery (PRD §13, §16).

Nothing else may write to a store. It takes a publish the dashboard queued, checks everything again right
before writing, and only reports SUCCEEDED once the product has been read back and matches. A result it didn't
see is OUTCOME_UNKNOWN, and nothing is retried until the store has been checked.
"""
from typing import List, Optional

from packages import policy
from packages.adapters import artstore_map
from packages.adapters.contract import OutcomeUnknown, Refused, approval_issues
from packages.publisher import assets as asset_store
from packages.publisher.records import FAILED, QUEUED, SUCCEEDED, UNKNOWN, WRITING, Publications, _seconds_since

NOT_FOUND_WAIT = 60     # seconds: a write that wasn't found twice, this far apart, was not written
BY = "publishing-worker"


class Worker:
    def __init__(self, app, publications: Publications, adapter, images: asset_store.LocalAssetStore):
        self.app, self.pubs, self.adapter, self.images = app, publications, adapter, images

    # ------------------------------------------------------------ Gate 4
    def gate4(self, item: str, queued: dict) -> List[str]:
        """Why this publish must not go ahead, checked right before writing. Empty means it may."""
        problems = []
        if self.pubs.kill_switch()["on"]:
            problems.append("Writing is switched off.")
        last = self.app.approvals.latest(item)
        if not last:
            return problems + ["There's no approval for this piece."]
        approval, approved = last["approval"], last["change_set"]
        if approval["approval_id"] != queued.get("approval_id"):
            problems.append("A different approval is now the latest one: ask to publish again.")
        if approved["change_set_hash"] != queued.get("change_set_hash"):
            problems.append("This isn't the change set you asked to publish.")
        current, _, _ = self.app.change_set(item)
        if current["change_set_hash"] != approved["change_set_hash"]:
            changed = artstore_map.differences(approved, current)
            problems.append("The listing changed since you approved it (" + ", ".join(changed) + "): approve it again.")
        if not artstore_map.approvable(approved):
            problems.append("Something still blocks this listing.")
        problems += [i.message for i in approval_issues(approved, approval)]
        problems += [str(v) for v in policy.validate(approval, related=[approved])]
        self.adapter.refresh()
        self.adapter.delivered = {a["derivative_id"] for a in approved["assets"]}    # delivered next, if this passes
        problems += [i.message for i in self.adapter.validate(approved)]
        problems += [p["issue"].message for p in self.adapter.plan(approved) if p["issue"] and not self.adapter._matches(
            next(op for op in approved["operations"] if op["seq"] == p["seq"]))]
        return problems

    # ------------------------------------------------------------ one publish
    def _fail(self, item: str, reasons: List[str], event: str = "failed"):
        self.pubs.append(item, event, FAILED, reasons=reasons)
        self.pubs.audit.append(item, "publish_failed", "Not published: " + " ".join(reasons), by=BY)

    def _unknown(self, item: str, why: str, **data):
        self.pubs.append(item, "outcome_unknown", UNKNOWN, why=why, **data)
        self.pubs.audit.append(item, "publish_unknown", f"Publish outcome unknown: {why}", by=BY)

    def _succeed(self, item: str, change_set: dict, receipt: Optional[str], operations: list, report: dict):
        self.pubs.append(item, "published", SUCCEEDED, receipt_id=receipt, operations=operations,
                         product_id=change_set["operations"][0]["key"], report=report)
        self.pubs.audit.append(item, "published", f"Published to the {self.adapter.environment} store as a hidden "
                               f"draft (receipt {receipt})", by=BY, receipt_id=receipt,
                               change_set_hash=change_set["change_set_hash"])

    def publish(self, item: str):
        queued = self.pubs.latest(item, "queued")
        try:
            problems = self.gate4(item, queued)
        except Exception as e:                     # nothing has been written: safe to stop here
            problems = [f"The final check couldn't run: {type(e).__name__}: {e}"]
        if problems:
            return self._fail(item, problems, "gate4_refused")
        self.pubs.append(item, "gate4_passed")
        last = self.app.approvals.latest(item)
        approval, approved = last["approval"], last["change_set"]
        self.pubs.append(item, "writing", WRITING, attempt_of=queued["change_set_hash"])
        try:
            _, files, _ = self.app.change_set(item)
            delivered = self.images.deliver(approved["assets"], {a["derivative_id"]: a for a in files})
        except (asset_store.DeliveryError, OSError) as e:
            return self._fail(item, [f"An image couldn't be delivered: {e}"])
        self.pubs.append(item, "images_delivered", delivered=delivered)
        self.adapter.delivered = {d["derivative_id"] for d in delivered}
        self.adapter.writes_enabled = not self.pubs.kill_switch()["on"]    # the last look before writing
        try:
            result = self.adapter.publish_approved(approved, approval)
        except Refused as e:
            return self._fail(item, [i.message for i in e.issues])
        except OutcomeUnknown as e:
            self._unknown(item, "the write was sent, but its result wasn't seen", attempt_id=e.attempt_id)
            return self.recheck(item)
        except Exception as e:                     # after this point a write may have happened
            self._unknown(item, f"the publish stopped unexpectedly: {type(e).__name__}")
            return self.recheck(item)
        if result.state != SUCCEEDED:
            return self._fail(item, [result.error or "The store didn't take it."])
        report = self.adapter.reconcile(approved, [{"attempt_id": result.attempt_id, "state": SUCCEEDED,
                                                    "receipt_id": result.receipt_id}])
        if report["verified_state"] != SUCCEEDED:
            return self._unknown(item, "the product didn't match when read back", report=report)
        self._succeed(item, approved, result.receipt_id, result.operations, report)

    # ------------------------------------------------------------ recovery
    def recheck(self, item: str):
        """Look in the store. It never writes: a retry is the owner's decision, once the outcome is known."""
        last = self.app.approvals.latest(item)
        unknown = self.pubs.latest(item, "outcome_unknown") or {}
        attempts = [{"attempt_id": unknown["attempt_id"], "state": UNKNOWN}] if unknown.get("attempt_id") else []
        report = self.adapter.reconcile(last["change_set"], attempts)
        ops = report["operations"]
        if report["verified_state"] == SUCCEEDED:
            return self._succeed(item, last["change_set"], f"recovered-{unknown.get('attempt_id') or 'check'}", ops, report)
        if any(o["result"] == "mismatch" for o in ops):
            wrong = sorted({f for o in ops for f in o.get("mismatched_fields", [])})
            self.pubs.append(item, "rechecked", finding="mismatch", fields=wrong, report=report)
            self.pubs.audit.append(item, "publish_mismatch", "The store's product doesn't match what was approved: "
                                   + ", ".join(wrong), by=BY)
            return None
        first = next((e for e in self.pubs.events(item) if e["event"] == "rechecked" and e.get("finding") == "not_found"
                      and e["at"] >= unknown.get("at", "")), None)
        if first and _seconds_since(first["at"], self.pubs.clock()) >= NOT_FOUND_WAIT:
            return self._fail(item, ["It was checked twice and isn't in the store, so it wasn't written. "
                                     "It's safe to publish again."], "verified_not_written")
        self.pubs.append(item, "rechecked", finding="not_found", report=report)
        return None

    def recover(self):
        """A worker that stopped mid-write doesn't know what happened. Look before anything else runs."""
        for item in self.pubs.in_state(WRITING):
            self._unknown(item, "the worker stopped while writing")
            self.recheck(item)

    def run_once(self) -> int:
        """Everything waiting, once: asked-for checks, then queued publishes. Returns how many it handled."""
        handled = 0
        for item in self.pubs.in_state(UNKNOWN):
            if self.pubs.recheck_wanted(item):
                self.recheck(item)
                handled += 1
        for item in self.pubs.in_state(QUEUED):
            self.publish(item)
            handled += 1
        return handled
