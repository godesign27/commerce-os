"""An in-memory storefront that honours the adapter contract (B-019). It never touches a real store.

It lets Phase 1 run end to end, from photos to a "published" product, on one machine. It enforces
every guard a real adapter must: the kill switch, approval bindings, the sealed hash, preconditions,
explicit status, known columns and atomic writes. So a workflow that passes against the fake has been
held to the real rules. Its catalog structure, defaults and seed come from the same files as the local
database stand-in (database/storefronts/<id>/), so the two can't drift apart.

Test controls: `fail_next("before_write")` makes the next publish fail with nothing written;
`fail_next("lose_response")` commits the write, then raises OutcomeUnknown, as a timeout would.
"""
import copy
import datetime
import decimal
import json
import re
import uuid
from pathlib import Path
from typing import List, Optional

from packages.adapters.contract import (Adapter, Issue, OutcomeUnknown, PublishResult, Refused,
                                        approval_issues, canonical_json, change_set_hash, row_hash,
                                        snapshot)

REPO = Path(__file__).resolve().parents[2]
ENTITY_TABLES = {"product": "products", "category": "categories", "tag": "tags"}
FIXED_CLOCK = datetime.datetime(2026, 1, 1, 12, 0, 0)


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


class FakeStorefront(Adapter):

    def __init__(self, storefront_id: str, environment: str, profile: dict, structure: dict, *,
                 currency: str, features: list, seed: Optional[dict] = None, writes_enabled: bool = False,
                 clock=None):
        self.storefront_id, self.environment = storefront_id, environment
        self.profile, self.structure = profile, structure
        self.currency, self.features = currency, list(features)
        self.writes_enabled = writes_enabled
        self.clock = clock or (lambda: FIXED_CLOCK)
        self.tables = {t: {} for t in structure["tables"]}
        self.receipts = {}       # change_set_id -> (hash, PublishResult)
        self.calls = []          # every method call, for tests to assert on
        self._fail = None
        for table, rows in (seed or {}).items():
            if table in self.tables:
                for row in rows:
                    stored = self._with_defaults(table, {k: v for k, v in row.items() if k != "case"})
                    self.tables[table][stored["id"]] = stored

    @classmethod
    def from_repo(cls, storefront_id: str, environment: str = "test", *, seed: bool = True,
                  writes_enabled: bool = False) -> "FakeStorefront":
        """Build from the committed config, catalog profile, structure snapshot and seed."""
        cfg = _load(REPO / "config" / "storefronts.example.json")
        entry = next(s for s in cfg["storefronts"] if s["id"] == storefront_id)
        base = REPO / "database" / "storefronts" / storefront_id
        profile = _load(REPO / "resources" / "catalog-profiles" / f"{entry['catalog_profile']}.json")
        structure = _load(base / "catalog-structure.json")
        return cls(storefront_id, environment, profile, structure, currency=entry["currency"],
                   features=entry["features"], seed=_load(base / "seed.json") if seed else None,
                   writes_enabled=writes_enabled)

    # ------------------------------------------------------------ helpers

    @property
    def fingerprint(self) -> str:
        return self.structure["fingerprint"]

    def columns(self, table: str) -> dict:
        return self.structure["tables"][table]["columns"]

    def _default(self, spec: dict):
        """Evaluate the column defaults this schema actually uses, as Postgres would."""
        d = spec["default"]
        if d is None:
            return None
        if d == "gen_random_uuid()":
            return str(uuid.uuid4())
        if d == "now()":
            return self.clock().isoformat(sep=" ")
        if d in ("true", "false"):
            return d == "true"
        if re.fullmatch(r"-?\d+", d):
            return int(d)
        m = re.fullmatch(r"'(.*)'::(text|jsonb)", d)
        if m:
            return json.loads(m.group(1)) if m.group(2) == "jsonb" else m.group(1)
        raise ValueError(f"fake storefront can't evaluate default {d!r}")

    def _with_defaults(self, table: str, row: dict) -> dict:
        out = {}
        for col, spec in self.columns(table).items():
            out[col] = self._normalize(spec, row[col]) if col in row else self._default(spec)
        return out

    @staticmethod
    def _normalize(spec: dict, value):
        """Store numerics the way Postgres returns them: exact decimals at the column's scale."""
        m = re.fullmatch(r"numeric\((\d+),(\d+)\)", spec["type"])
        if m and value is not None:
            return str(decimal.Decimal(str(value)).quantize(decimal.Decimal(1).scaleb(-int(m.group(2)))))
        return value

    def _to_destination(self, table: str, column: str, value):
        """Change-set value -> stored value. Money arrives as integer minor units."""
        money_cols = self.profile["product"]["money"]["columns"] if table == "products" else []
        if column in money_cols and isinstance(value, dict):
            return str(decimal.Decimal(value["amount_minor"]).scaleb(-2).quantize(decimal.Decimal("0.01")))
        return self._normalize(self.columns(table)[column], value)

    def row_hash(self, entity: str, key: str) -> Optional[str]:
        row = self.tables[ENTITY_TABLES[entity]].get(key)
        return row_hash(row) if row is not None else None

    def _log(self, method: str, change_set: Optional[dict] = None):
        self.calls.append((method, change_set.get("change_set_id") if change_set else None))

    # ------------------------------------------------------------ contract

    def capabilities(self) -> dict:
        self._log("capabilities")
        status = self.profile["product"]["status"]
        return {
            "storefront": self.storefront_id,
            "environment": self.environment,
            "writable_entities": [e for e, t in ENTITY_TABLES.items() if t in self.profile["write_tables"]],
            "statuses": status["values"],
            "hidden_on_create": status["hidden_on_create"],
            "currency": self.currency,
            "features": self.features,
            "schema_fingerprint": self.fingerprint,
            "writes_enabled": self.writes_enabled,
            "dry_run": True,
            "fake": True,
        }

    def read_catalog(self) -> dict:
        self._log("read_catalog")
        return {t: sorted(snapshot(list(rows.values())), key=lambda r: (r.get("name") or "", r["id"]))
                for t, rows in self.tables.items()}

    def validate(self, change_set: dict) -> List[Issue]:
        self._log("validate", change_set)
        issues = []
        if change_set.get("destination") != self.storefront_id:
            issues.append(Issue("wrong_destination", f"change set targets {change_set.get('destination')}"))
        if change_set.get("environment") != self.environment:
            issues.append(Issue("wrong_environment", f"change set targets {change_set.get('environment')}"))
        if change_set.get("schema_fingerprint") != self.fingerprint:
            issues.append(Issue("schema_changed", "the destination schema fingerprint differs; re-map and re-approve"))
        status_rule = self.profile["product"]["status"]
        requested = change_set.get("requested_status")
        if requested not in status_rule["values"]:
            issues.append(Issue("invalid_status", f"{requested!r} isn't a destination status"))
        seqs = [op.get("seq") for op in change_set.get("operations", [])]
        if seqs != sorted(set(seqs)):
            issues.append(Issue("bad_sequence", "operation seq values must be unique and ascending"))
        if any(not a.get("delivered") for a in change_set.get("assets", [])):
            issues.append(Issue("assets_not_delivered", "every asset must be delivered before publishing"))
        for op in change_set.get("operations", []):
            issues += self._op_issues(op, requested, status_rule)
        return issues

    def _op_issues(self, op: dict, requested: str, status_rule: dict) -> List[Issue]:
        seq, issues = op.get("seq"), []
        table = ENTITY_TABLES.get(op.get("entity"))
        if table not in self.profile["write_tables"]:
            return [Issue("entity_not_writable", f"{op.get('entity')} can't be written here", seq)]
        fields = op.get("fields", {})
        cols = self.columns(table)
        for name in fields:
            if name not in cols:
                issues.append(Issue("unknown_column", f"{table}.{name} doesn't exist", seq))
        if "id" in fields and fields["id"].get("value") != op.get("key"):
            issues.append(Issue("key_mismatch", "fields.id must equal the operation key", seq))
        status_field = status_rule["column"]
        if status_field in fields and fields[status_field].get("value") != requested:
            issues.append(Issue("status_mismatch", "the status field differs from requested_status", seq))
        if op.get("op") == "create":
            if status_rule.get("always_set_explicitly") and status_field not in fields:
                issues.append(Issue("status_not_explicit", "creates must set status; never rely on the default", seq))
            required = [c for c in self.profile["product"]["required_on_insert"] if c != "id"]
            for c in required:
                if c not in fields:
                    issues.append(Issue("missing_required", f"{table}.{c} is required on create", seq))
        for name in self.profile["product"]["money"]["columns"]:
            money = (fields.get(name) or {}).get("value")
            if isinstance(money, dict) and money.get("currency") != self.currency:
                issues.append(Issue("wrong_currency", f"{name} is {money.get('currency')}, store is {self.currency}", seq))
        category = (fields.get(self.profile["product"]["category"]["column"]) or {}).get("value")
        if category is not None and category not in self.tables["categories"]:
            issues.append(Issue("unknown_category", f"category {category} doesn't exist", seq))
        for tag in (fields.get(self.profile["product"]["tags"]["column"]) or {}).get("value") or []:
            if tag not in self.tables["tags"]:
                issues.append(Issue("unknown_tag", f"tag {tag} doesn't exist", seq))
        return issues

    def plan(self, change_set: dict, tables: Optional[dict] = None) -> list:
        self._log("plan", change_set)
        tables = tables if tables is not None else self.tables
        planned = []
        for op in change_set.get("operations", []):
            table = ENTITY_TABLES.get(op.get("entity"))
            if table not in tables:
                continue
            before = tables[table].get(op["key"])
            issue = None
            if op["op"] == "create" and before is not None:
                issue = Issue("already_exists", f"{op['key']} already exists", op["seq"])
            elif op["op"] == "update" and before is None:
                issue = Issue("not_found", f"{op['key']} doesn't exist", op["seq"])
            elif op["op"] == "update" and row_hash(before) != op["precondition"].get("expected_row_hash"):
                issue = Issue("row_changed", f"{op['key']} changed since the change set was made", op["seq"])
            after = None
            if issue is None:
                values = {c: self._to_destination(table, c, f["value"]) for c, f in op.get("fields", {}).items()
                          if c in self.columns(table)}
                if op["op"] == "create":
                    after = self._with_defaults(table, {"id": op["key"], **values})
                else:
                    after = {**before, **values}
                    if "updated_at" in after and "updated_at" not in values:
                        after["updated_at"] = self.clock().isoformat(sep=" ")
            planned.append({"seq": op["seq"], "op": op["op"], "key": op["key"], "table": table,
                            "before": snapshot(before), "after": after,
                            "changed": sorted(k for k in (after or {}) if (before or {}).get(k) != after[k]),
                            "issue": issue})
        return planned

    def dry_run(self, change_set: dict) -> dict:
        self._log("dry_run", change_set)
        before = canonical_json(self.tables)
        issues = self.validate(change_set)
        planned = self.plan(change_set, tables=copy.deepcopy(self.tables))
        issues += [p["issue"] for p in planned if p["issue"]]
        if canonical_json(self.tables) != before:     # belt and braces: a dry run must never write
            raise AssertionError("dry run changed destination state")
        return {
            "dry_run": True,
            "destination": self.storefront_id,
            "environment": self.environment,
            "change_set_id": change_set.get("change_set_id"),
            "would_publish": not issues,
            "issues": [i.as_dict() for i in issues],
            "plan": [{k: (v.as_dict() if isinstance(v, Issue) else v) for k, v in p.items()} for p in planned],
            "receipt_id": None,
        }

    def publish_approved(self, change_set: dict, approval: dict) -> PublishResult:
        self._log("publish_approved", change_set)
        cs_id = change_set.get("change_set_id")
        if cs_id in self.receipts:
            sealed, result = self.receipts[cs_id]
            if sealed != change_set.get("change_set_hash"):
                raise Refused([Issue("change_set_id_reused", "a different change set already used this id")])
            replay = copy.copy(result)
            replay.replayed = True
            return replay
        issues = []
        if not self.writes_enabled:
            issues.append(Issue("writes_disabled", "writes are disabled for this storefront (kill switch)"))
        if change_set.get("simulated"):
            issues.append(Issue("simulated", "a simulated change set can only be dry-run"))
        issues += approval_issues(change_set, approval)
        issues += self.validate(change_set)
        if issues:
            raise Refused(issues)

        attempt_id = f"att-{uuid.uuid4().hex[:12]}"
        working = copy.deepcopy(self.tables)
        planned = self.plan(change_set, tables=working)
        failed = [p["issue"] for p in planned if p["issue"]]
        if failed or self._fail == "before_write":
            self._fail = None
            error = "; ".join(f"{i.code}: {i.message}" for i in failed) or "injected failure before write"
            return PublishResult(cs_id, attempt_id, "FAILED", None,
                                 [{"seq": p["seq"], "key": p["key"], "result": "not_written"} for p in planned], error)
        for p in planned:                          # all or nothing: apply to the copy, then swap
            working[p["table"]][p["key"]] = p["after"]
        self.tables = working
        result = PublishResult(cs_id, attempt_id, "SUCCEEDED", f"rcpt-{uuid.uuid4().hex[:12]}",
                               [{"seq": p["seq"], "key": p["key"], "result": "written"} for p in planned])
        self.receipts[cs_id] = (change_set.get("change_set_hash"), result)
        if self._fail == "lose_response":
            self._fail = None
            raise OutcomeUnknown(cs_id, attempt_id)
        return result

    def reconcile(self, change_set: dict, attempts: Optional[list] = None) -> dict:
        self._log("reconcile", change_set)
        attempts = attempts or []
        ops = []
        for op in change_set["operations"]:
            table = ENTITY_TABLES[op["entity"]]
            row = self.tables[table].get(op["key"])
            if row is None:
                ops.append({"seq": op["seq"], "key": op["key"], "result": "not_found"})
                continue
            wrong = sorted(c for c, f in op.get("fields", {}).items()
                           if c in row and row[c] != self._to_destination(table, c, f["value"]))
            ops.append({"seq": op["seq"], "key": op["key"], "result": "mismatch", "mismatched_fields": wrong}
                       if wrong else {"seq": op["seq"], "key": op["key"], "result": "match"})
        results = {o["result"] for o in ops}
        last = attempts[-1]["state"] if attempts else None
        if results == {"match"}:
            state, action = "SUCCEEDED", "none"
        elif "mismatch" in results:
            state, action = "OUTCOME_UNKNOWN", "operator_review"
        elif last == "FAILED":
            state, action = "FAILED", "none"
        else:
            state, action = "OUTCOME_UNKNOWN", "recheck"
        return {
            "contract": "reconciliation-report",
            "contract_version": 1,
            "destination": self.storefront_id,
            "environment": self.environment,
            "change_set_id": change_set["change_set_id"],
            "verified_state": state,
            "attempts": attempts,
            "operations": ops,
            "checked_at": self.clock().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "recommended_action": action,
        }

    # ------------------------------------------------------------ test controls

    def fail_next(self, mode: str):
        if mode not in ("before_write", "lose_response"):
            raise ValueError(mode)
        self._fail = mode

    def set_writes_enabled(self, enabled: bool):
        self.writes_enabled = enabled


def seal(change_set: dict) -> dict:
    """What the workflow service does at sealing: fill in the hash. Returns a new document."""
    sealed = {**change_set, "change_set_hash": None}
    sealed["change_set_hash"] = change_set_hash(sealed)
    return sealed
