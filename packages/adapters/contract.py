"""The storefront adapter contract (PRD §15), shared by every adapter, real or fake.

Only the interface and storefront-neutral guards live here: canonical hashing, approval binding checks
and result types. Schema translation, SQL, mappings and identity resolution belong to each storefront's
own adapter and are never shared (PRD §15, packages/README.md).

Stdlib only; Python 3.9+.
"""
import abc
import copy
import datetime
import decimal
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from packages.policy import approvals as policy_approvals

CONTRACT_VERSION = 1


# ---------------------------------------------------------------- canonical hashing

def _default(value):
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    raise TypeError(f"not canonicalizable: {type(value).__name__}")


def canonical_json(value) -> str:
    """Sorted keys, no whitespace, UTF-8. Decimals and timestamps as strings."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def change_set_hash(change_set: dict) -> str:
    """The hash an approval binds to: the whole change set except the hash field itself."""
    body = {k: v for k, v in change_set.items() if k != "change_set_hash"}
    return sha256_hex(canonical_json(body))


def row_hash(row: dict) -> str:
    """Hash of one destination row as the adapter reads it. An update's expected_row_hash must equal it."""
    return sha256_hex(canonical_json(row))


# ---------------------------------------------------------------- results

@dataclass
class Issue:
    code: str
    message: str
    seq: Optional[int] = None

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class Refused(Exception):
    """Nothing was attempted: a guard failed before any write. Safe to fix and re-approve."""

    def __init__(self, issues: List[Issue]):
        self.issues = issues
        super().__init__("; ".join(f"{i.code}: {i.message}" for i in issues))


class OutcomeUnknown(Exception):
    """A write was sent but its result wasn't observed. Never retry blindly: reconcile first (PRD §14)."""

    def __init__(self, change_set_id: str, attempt_id: str):
        self.change_set_id, self.attempt_id = change_set_id, attempt_id
        super().__init__(f"outcome unknown for {change_set_id} (attempt {attempt_id}); reconcile before retrying")


@dataclass
class PublishResult:
    change_set_id: str
    attempt_id: str
    state: str                     # SUCCEEDED or FAILED (publication_state)
    receipt_id: Optional[str]
    operations: list = field(default_factory=list)   # [{seq, key, result}]
    error: Optional[str] = None
    replayed: bool = False         # True when this is the stored receipt of an earlier identical publish

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- storefront-neutral guards

APPROVAL_BINDINGS = ("change_set_id",) + policy_approvals.APPROVAL_BINDINGS


def approval_issues(change_set: dict, approval: Optional[dict]) -> List[Issue]:
    """Every adapter checks these before writing, whatever the workflow service already checked.
    Bindings and self-approval come from packages/policy, their single definition."""
    if not approval:
        return [Issue("no_approval", "publishing needs a human approval of this exact change set")]
    issues = []
    sealed = change_set.get("change_set_hash")
    if not sealed:
        issues.append(Issue("not_sealed", "the change set has no hash; it was never sealed for approval"))
    elif change_set_hash(change_set) != sealed:
        issues.append(Issue("hash_mismatch", "the change set's contents don't match its sealed hash"))
    actor = approval.get("actor") or {}
    if actor.get("kind") != "human" or actor.get("role") != "approver":
        issues.append(Issue("not_a_human_approver", "approvals come from a human with the approver role"))
    for v in policy_approvals.self_approval(approval) + policy_approvals.binding_violations(approval, change_set):
        issues.append(Issue(v.code, v.message))
    return issues


# ---------------------------------------------------------------- the interface

class Adapter(abc.ABC):
    """One storefront, one environment. Methods map one-to-one to PRD §15.

    Only publish_approved() may change the destination. Everything else is read-only, and dry_run()
    must be provably side-effect free.
    """

    storefront_id: str
    environment: str

    @abc.abstractmethod
    def capabilities(self) -> dict:
        """What this destination supports: writable entities, statuses, currency, features, fingerprint."""

    @abc.abstractmethod
    def read_catalog(self) -> dict:
        """Categories, tags and products as the destination stores them. Copies, never live references."""

    @abc.abstractmethod
    def validate(self, change_set: dict) -> List[Issue]:
        """Destination rules: target, fingerprint, known columns, required fields, explicit status, refs."""

    @abc.abstractmethod
    def plan(self, change_set: dict) -> list:
        """Per operation: the row before, the row after, and whether its precondition holds now."""

    @abc.abstractmethod
    def dry_run(self, change_set: dict) -> dict:
        """validate() + plan(), reported with dry_run: true. No side effects, ever."""

    @abc.abstractmethod
    def publish_approved(self, change_set: dict, approval: dict) -> PublishResult:
        """Apply an approved change set atomically, or refuse. Idempotent per change_set_id."""

    @abc.abstractmethod
    def reconcile(self, change_set: dict, attempts: Optional[list] = None) -> dict:
        """Read-after-write check; returns a reconciliation-report contract document."""


def snapshot(value):
    """A deep copy, so callers can never hold a live reference into adapter state."""
    return copy.deepcopy(value)
