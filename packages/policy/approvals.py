"""Approval rules (PRD §13): an approval binds one exact change set, and nobody approves their own work.

This is the single definition. The workflow service checks it before recording an approval, every
adapter checks it again before writing (packages/adapters/contract.py), and the operational database
enforces the same bindings in its approvals_bindings trigger (migration 0007).
"""
from typing import List

from packages.policy.violations import Violation

# Fields an approval must copy exactly from its change set. The change_set_id is matched by lookup.
APPROVAL_BINDINGS = ("destination", "environment", "change_set_hash", "canonical_revision",
                     "asset_manifest_hash", "mapping_version", "schema_fingerprint", "requested_status")


def self_approval(approval: dict) -> List[Violation]:
    prepared = (approval.get("prepared_by") or {}).get("id")
    approver = (approval.get("actor") or {}).get("id")
    if prepared and prepared == approver:
        return [Violation("self_approval", "prepared_by", "self-approval: the approver prepared the change set")]
    return []


def binding_violations(approval: dict, change_set: dict) -> List[Violation]:
    """Every binding must equal the change set's. Call only with the change set the approval names."""
    out = []
    if approval.get("change_set_id") != change_set.get("change_set_id"):
        out.append(Violation("binding_mismatch", "change_set_id", "approval change_set_id does not match change set"))
    for key in APPROVAL_BINDINGS:
        if approval.get(key) != change_set.get(key):
            out.append(Violation("binding_mismatch", key, f"approval {key} does not match change set"))
    return out
