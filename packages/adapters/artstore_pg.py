"""The real adapter for catalog profile replit-artstore-v1: Postgres writes behind the adapter contract (PRD §15).

It inherits the rules from the fake storefront (validate, plan, dry_run, reconcile), reading the real rows first,
so anything that passes against the fake has been held to the same rules, and the two can't drift apart. What
it adds is the write: one transaction, parameters only (a title can never be read as SQL), and exact reporting.
If a write was sent and its result wasn't seen, that's OutcomeUnknown, never a guess.

The write login is passed in by the publishing worker alone. Any target but a local Unix socket is refused here
(require_local), unless packages/publisher/live_store.py has passed its checks and names the one live host it allows
(require_live). Whatever it's given, this adapter only ever adds Drafts.
"""
import datetime
import decimal
import uuid
from typing import Callable, Optional

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.adapters import artstore_map
from packages.adapters.contract import Issue, OutcomeUnknown, PublishResult, Refused, approval_issues
from packages.adapters.fake import ENTITY_TABLES, FakeStorefront

CONNECT = {"connect_timeout": 10, "options": "-c statement_timeout=15000"}


class NotLocal(ValueError):
    """The target isn't the local test store, so nothing connected to it."""


def require_local(dsn: str) -> str:
    """Only a Unix socket on this computer: the local test store."""
    info = conninfo_to_dict(dsn)
    host = info.get("host") or ""
    if not host.startswith("/") or "," in host or info.get("hostaddr"):
        raise NotLocal("Publishing can only reach the local test store for now, so nothing was connected.")
    return dsn


def require_live(dsn: str, host: str) -> str:
    """Only the one host live_store named, with an encrypted connection."""
    info = conninfo_to_dict(dsn)
    if not host or info.get("host") != host or info.get("hostaddr") or info.get("sslmode") not in ("require", "verify-ca", "verify-full"):
        raise NotLocal("That login isn't for the live store over an encrypted connection, so nothing was connected.")
    return dsn


class PgRows:
    """A read-only `.rows(sql)` over one connection, for the structure queries."""

    def __init__(self, conn):
        self.conn = conn

    def rows(self, query: str) -> list:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query)
            return list(cur.fetchall())


class PostgresArtStore(FakeStorefront):

    def __init__(self, storefront_id: str, environment: str, profile: dict, structure: dict, *, write_dsn: str,
                 read_dsn: str, currency: str, features: list, writes_enabled: bool = False,
                 read_structure: Optional[Callable] = None, live_host: Optional[str] = None):
        super().__init__(storefront_id, environment, profile, structure, currency=currency, features=features,
                         writes_enabled=writes_enabled)
        allowed = (lambda dsn: require_live(dsn, live_host)) if live_host is not None else require_local
        self.write_dsn, self.read_dsn = allowed(write_dsn), allowed(read_dsn)
        self._read_structure = read_structure      # rows -> {"tables", "fingerprint"}, as the store is right now

    def _value(self, table: str, column: str, value):
        if isinstance(value, decimal.Decimal):
            return self._normalize(self.columns(table)[column], value)
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.isoformat(sep=" ") if isinstance(value, datetime.datetime) else value.isoformat()
        return value

    def refresh(self):
        """Read the store as it is now, with the read login: its structure first, then its rows."""
        with psycopg.connect(self.read_dsn, autocommit=True, **CONNECT) as conn:
            if self._read_structure:
                self.structure = dict(self.structure, **self._read_structure(PgRows(conn)))
            rows = PgRows(conn)
            self.tables = {t: {r["id"]: {c: self._value(t, c, v) for c, v in r.items()}
                               for r in rows.rows(f'SELECT * FROM public."{t}"')} for t in self.structure["tables"]}

    def capabilities(self) -> dict:
        return dict(super().capabilities(), fake=False)

    def _matches(self, op: dict) -> bool:
        table = ENTITY_TABLES[op["entity"]]
        row = self.tables[table].get(op["key"])
        return row is not None and all(row.get(c) == self._to_destination(table, c, f["value"])
                                       for c, f in op.get("fields", {}).items())

    def _insert(self, conn, table: str, values: dict):
        def param(col, value):
            return Jsonb(value) if self.columns(table)[col]["type"] == "jsonb" else value
        cols = list(values)
        statement = sql.SQL("INSERT INTO public.{} ({}) VALUES ({})").format(
            sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, cols)),
            sql.SQL(", ").join(sql.Placeholder() * len(cols)))
        conn.execute(statement, [param(c, values[c]) for c in cols])

    def publish_approved(self, change_set: dict, approval: dict) -> PublishResult:
        self._log("publish_approved", change_set)
        cs_id = change_set.get("change_set_id")
        issues = approval_issues(change_set, approval)
        if change_set.get("simulated"):
            issues.append(Issue("simulated", "a simulated change set can only be dry-run"))
        if change_set.get("requested_status") != artstore_map.STATUS or any(
                (op.get("fields", {}).get("status") or {}).get("value") != artstore_map.STATUS for op in change_set.get("operations", [])):
            issues.append(Issue("not_a_draft", "Commerce OS only adds Drafts: you make a product live in the store's admin"))
        if issues:
            raise Refused(issues)
        self.refresh()
        ops = change_set.get("operations", [])
        if ops and all(self._matches(op) for op in ops):       # a repeat of what's already there adds nothing
            return PublishResult(cs_id, f"att-{uuid.uuid4().hex[:12]}", "SUCCEEDED", f"rcpt-{uuid.uuid4().hex[:12]}",
                                 [{"seq": op["seq"], "key": op["key"], "result": "already_present"} for op in ops],
                                 replayed=True)
        if not self.writes_enabled:
            raise Refused([Issue("writes_disabled", "writes are disabled for this storefront (kill switch)")])
        issues = self.validate(change_set)
        if issues:
            raise Refused(issues)
        attempt = f"att-{uuid.uuid4().hex[:12]}"
        planned = self.plan(change_set)
        not_written = [{"seq": p["seq"], "key": p["key"], "result": "not_written"} for p in planned]
        failed = [p["issue"] for p in planned if p["issue"]]
        if failed or self._fail == "before_write":
            self._fail = None
            error = "; ".join(f"{i.code}: {i.message}" for i in failed) or "injected failure before write"
            return PublishResult(cs_id, attempt, "FAILED", None, not_written, error)
        try:
            conn = psycopg.connect(self.write_dsn, **CONNECT)
        except psycopg.OperationalError:               # nothing was sent
            return PublishResult(cs_id, attempt, "FAILED", None, not_written, "couldn't connect with the write login")
        try:
            with conn:                                 # commits on leaving; rolls back on any error
                for op in ops:
                    table = ENTITY_TABLES[op["entity"]]
                    self._insert(conn, table, {c: self._to_destination(table, c, f["value"])
                                               for c, f in op.get("fields", {}).items()})
                if self._fail == "lose_before_commit":
                    self._fail = None
                    conn.close()
                    raise psycopg.OperationalError("injected: connection lost before commit")
        except psycopg.errors.IntegrityError as e:    # the store refused it: rolled back, nothing written
            why = ("another product already uses this web address. Change the title, then approve it again"
                   if "slug" in (e.diag.constraint_name or "") else e.diag.message_primary)
            return PublishResult(cs_id, attempt, "FAILED", None, not_written, f"the store refused it: {why}")
        except psycopg.OperationalError:              # sent, but its result wasn't seen
            raise OutcomeUnknown(cs_id, attempt)
        if self._fail == "lose_response":
            self._fail = None
            raise OutcomeUnknown(cs_id, attempt)
        return PublishResult(cs_id, attempt, "SUCCEEDED", f"rcpt-{uuid.uuid4().hex[:12]}",
                             [{"seq": p["seq"], "key": p["key"], "result": "written"} for p in planned])

    def reconcile(self, change_set: dict, attempts: Optional[list] = None) -> dict:
        """Read-after-write, always with the read login."""
        self.refresh()
        return super().reconcile(change_set, attempts)

    def fail_next(self, mode: str):
        if mode not in ("before_write", "lose_response", "lose_before_commit"):
            raise ValueError(mode)
        self._fail = mode
