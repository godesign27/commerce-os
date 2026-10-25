"""database/operational/migrations: static checks that always run, plus an optional live run.

The static checks parse the SQL: structure, keys, isolation, append-only tables, state machines and
the rules shared with the evidence policy and contracts. The live run (scripts/test_operational_db.py)
applies everything to a real Postgres inside one rolled-back transaction, only when
COMMERCE_OS_TEST_DB_URL is set.
"""
import importlib.util
import os
import re
import unittest
from collections import defaultdict

from tests._helpers import REPO, SHARED, load_json, read

MIGRATIONS = REPO / "database" / "operational" / "migrations"
SMOKE = REPO / "database" / "operational" / "tests" / "smoke.sql"
COMMON = REPO / "packages" / "contracts" / "schemas" / "common.schema.json"
FILES = sorted(MIGRATIONS.glob("*.sql"))
SQL = {p.name: read(p) for p in FILES}
ALL = "\n".join(SQL.values())


def strip_comments(sql):
    return re.sub(r"--[^\n]*", "", sql)


def tables():
    """table name -> (migration file, body)"""
    out = {}
    for name, sql in SQL.items():
        for m in re.finditer(r"CREATE TABLE (\S+) \((.*?)\n\);", strip_comments(sql), re.S):
            out[m.group(1)] = (name, m.group(2))
    return out


def columns(body):
    cols = {}
    for line in body.splitlines():
        m = re.match(r"\s+([a-z_][a-z0-9_]*)\s+([a-z]+[^,]*)", line)
        if m and m.group(1).upper() not in ("PRIMARY", "UNIQUE", "CHECK", "FOREIGN"):
            cols[m.group(1)] = m.group(2)
    return cols


def values_of(table):
    m = re.search(rf"INSERT INTO {re.escape(table)} \([^)]*\) VALUES(.*?);", strip_comments(ALL), re.S)
    return re.findall(r"\('([A-Z_]+)'(?:,\s*'([A-Z_]+)')?", m.group(1))


def states(table):
    return {a for a, _ in values_of(table)}


def transitions(table):
    return {(a, b) for a, b in values_of(table)}


def terminal(table):
    m = re.search(rf"INSERT INTO {re.escape(table)} \(state, is_terminal\) VALUES(.*?);", ALL, re.S)
    return {s for s, t in re.findall(r"\('([A-Z_]+)', (true|false)\)", m.group(1)) if t == "true"}


def reachable(edges, start):
    graph = defaultdict(set)
    for a, b in edges:
        graph[a].add(b)
    seen, todo = {start}, [start]
    while todo:
        for nxt in graph[todo.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


class Structure(unittest.TestCase):
    def test_migrations_are_numbered_contiguously(self):
        names = [p.name for p in FILES]
        for i, n in enumerate(names, 1):
            self.assertRegex(n, rf"^{i:04d}_[a-z_]+\.sql$")

    def test_everything_lives_in_the_commerce_os_schema(self):
        code = strip_comments(ALL)
        for m in re.finditer(r"CREATE (?:TABLE|FUNCTION|(?:UNIQUE )?INDEX \S+ ON|TRIGGER \S+ .*? ON) (\S+)", code):
            self.assertTrue(m.group(1).startswith("commerce_os."), m.group(0))
        self.assertNotRegex(code, r"\bpublic\.", "the operational schema never touches public (storefront) tables")

    def test_every_table_has_a_primary_key(self):
        for t, (_, body) in tables().items():
            self.assertIn("PRIMARY KEY", body, t)

    def test_foreign_keys_point_at_earlier_tables(self):
        created = {}
        order = [p.name for p in FILES]
        for t, (f, _) in tables().items():
            created[t] = order.index(f)
        for t, (f, body) in tables().items():
            for target in re.findall(r"REFERENCES (commerce_os\.[a-z_]+)", body):
                self.assertIn(target, created, f"{t} references unknown {target}")
                self.assertLessEqual(created[target], order.index(f), f"{t} references {target} before it exists")


class Isolation(unittest.TestCase):
    def test_tenant_isolation_runs_last_and_covers_tenant_tables(self):
        self.assertIn("tenant_isolation", FILES[-1].name)
        last = read(FILES[-1])
        self.assertIn("FORCE ROW LEVEL SECURITY", last)
        self.assertIn("column_name = 'tenant_id'", last)

    def test_tenant_sensitive_tables_carry_tenant_id(self):
        must = {"submissions", "source_snapshots", "source_files", "products", "variants", "field_evidence",
                "review_issues", "change_sets", "destination_drafts", "approvals", "reviews", "jobs",
                "publication_attempts", "publication_receipts", "audit_events", "connections", "storefronts"}
        t = tables()
        for name in must:
            cols = columns(t[f"commerce_os.{name}"][1])
            self.assertIn("tenant_id", cols, name)
            self.assertIn("NOT NULL", cols["tenant_id"], name)

    def test_no_secret_columns(self):
        allowed = {"secret_ref", "page_token"}
        for t, (_, body) in tables().items():
            for c in columns(body):
                if re.search(r"password|secret|token|api_key|credential", c):
                    self.assertIn(c, allowed, f"{t}.{c} looks like it stores a secret")

    def test_canonical_staging_has_no_commercial_destination_columns(self):
        t = tables()
        for name in ("products", "variants"):
            cols = set(columns(t[f"commerce_os.{name}"][1]))
            self.assertFalse(cols & {"price", "stock", "currency", "tax", "status_on_storefront"}, name)


class Guarantees(unittest.TestCase):
    def test_append_only_tables(self):
        for name in ("audit_events", "reviews", "source_snapshots", "source_files", "field_evidence",
                     "publication_receipts", "product_type_versions", "mapping_versions", "product_proposals"):
            self.assertRegex(ALL, rf"BEFORE UPDATE OR DELETE ON commerce_os\.{name}\s+FOR EACH ROW EXECUTE FUNCTION commerce_os\.forbid_mutation",
                             name)

    def test_idempotency_and_uniqueness_keys(self):
        for pattern in [
            r"UNIQUE \(provider, channel_id, message_number\)",                       # duplicate notifications
            r"UNIQUE \(submission_id, manifest_hash, intake_policy_version\)",        # intake work key
            r"UNIQUE \(tenant_id, source_sha256, recipe_id, recipe_version, destination\)",  # image work key
            r"UNIQUE \(tenant_id, kind, idempotency_key\)",                           # jobs
            r"UNIQUE \(storefront_id, environment, change_set_hash, try_number\)",    # publication key
            r"UNIQUE \(storefront_id, environment, external_id\)",                    # destination links
            r"UNIQUE \(product_id, option_values_key\)",                              # variant options
            r"approvals_one_live_per_change_set",
            r"FOR UPDATE SKIP LOCKED",                                                # atomic job claims
        ]:
            self.assertRegex(ALL, pattern)

    def test_revision_and_transition_triggers(self):
        for name in ("submissions", "products", "variants", "destination_drafts"):
            self.assertRegex(ALL, rf"BEFORE UPDATE ON commerce_os\.{name}\s+FOR EACH ROW EXECUTE FUNCTION commerce_os\.require_next_revision")
        self.assertRegex(ALL, r"BEFORE UPDATE OF state ON commerce_os\.submissions\s+FOR EACH ROW EXECUTE FUNCTION commerce_os\.enforce_transition\('submission_transitions'\)")
        self.assertRegex(ALL, r"BEFORE UPDATE OF state ON commerce_os\.destination_drafts\s+FOR EACH ROW EXECUTE FUNCTION commerce_os\.enforce_transition\('publication_transitions'\)")

    def test_approvals_are_human_and_never_self(self):
        body = tables()["commerce_os.approvals"][1]
        self.assertIn("CHECK (actor_kind = 'human')", body)
        self.assertIn("CHECK (actor_role = 'approver')", body)
        self.assertIn("CHECK (actor_id <> prepared_by)", body)
        self.assertIn("approvals_bindings BEFORE INSERT", ALL)

    def test_kill_switch_starts_disabled(self):
        body = tables()["commerce_os.system_settings"][1]
        self.assertRegex(body, r"writes_disabled\s+boolean NOT NULL DEFAULT true")


class StateMachines(unittest.TestCase):
    def test_submission_states_match_the_workflow(self):
        wf = read(SHARED / "WORKFLOW.md").split("## Per-destination", 1)[0]
        self.assertEqual(states("commerce_os.submission_states"), set(re.findall(r"\b[A-Z][A-Z_]{4,}\b", wf)))

    def test_publication_states_match_the_contracts(self):
        enum = set(load_json(COMMON)["$defs"]["publication_state"]["enum"])
        self.assertEqual(states("commerce_os.publication_states"), enum)

    def test_transitions_use_known_states_and_terminals_are_final(self):
        for st, tr in (("commerce_os.submission_states", "commerce_os.submission_transitions"),
                       ("commerce_os.publication_states", "commerce_os.publication_transitions")):
            known, edges, final = states(st), transitions(tr), terminal(st)
            for a, b in edges:
                self.assertIn(a, known, f"{tr}: unknown {a}")
                self.assertIn(b, known, f"{tr}: unknown {b}")
                self.assertNotIn(a, final, f"{tr}: terminal state {a} has an outgoing transition")

    def test_every_state_is_reachable(self):
        self.assertEqual(reachable(transitions("commerce_os.submission_transitions"), "RECEIVED"),
                         states("commerce_os.submission_states"))
        self.assertEqual(reachable(transitions("commerce_os.publication_transitions"), "NOT_SELECTED"),
                         states("commerce_os.publication_states"))

    def test_gates_cannot_be_skipped(self):
        sub = transitions("commerce_os.submission_transitions")
        pub = transitions("commerce_os.publication_transitions")
        self.assertEqual({a for a, b in sub if b == "APPROVED"}, {"READY_FOR_APPROVAL"})
        self.assertEqual({a for a, b in sub if b == "PUBLISHED"}, {"PUBLISHING"})
        self.assertEqual({a for a, b in pub if b == "APPROVED"}, {"AWAITING_APPROVAL"})
        self.assertEqual({a for a, b in pub if b == "QUEUED"}, {"APPROVED", "FAILED"})
        self.assertEqual({a for a, b in pub if b == "SUCCEEDED"}, {"VERIFYING", "OUTCOME_UNKNOWN"})

    def test_in_flight_writes_cannot_be_cancelled(self):
        pub = transitions("commerce_os.publication_transitions")
        for s in ("WRITING", "VERIFYING", "OUTCOME_UNKNOWN"):
            self.assertNotIn((s, "CANCELLED"), pub)


class MatchesPolicy(unittest.TestCase):
    def test_field_evidence_statuses_match_the_policy(self):
        table = read(SHARED / "evidence-policy.md").split("## Statuses", 1)[1].split("## Rules", 1)[0]
        policy = set(re.findall(r"^\| `(\w+)` \|", table, re.M))
        body = tables()["commerce_os.field_evidence"][1]
        m = re.search(r"status\s+text NOT NULL CHECK \(status IN \((.*?)\)\)", body, re.S)
        self.assertEqual(set(re.findall(r"'(\w+)'", m.group(1))), policy)

    def test_commercial_facts_are_never_observed_or_inferred(self):
        body = tables()["commerce_os.field_evidence"][1]
        m = re.search(r"CHECK \(NOT is_commercial OR status IN \((.*?)\)\)", body)
        self.assertIsNotNone(m)
        self.assertFalse(set(re.findall(r"'(\w+)'", m.group(1))) & {"observed", "inferred"})


class LiveTestHarness(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("todb", REPO / "scripts" / "test_operational_db.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_live_run_is_one_rolled_back_transaction(self):
        script = self.mod.build_script()
        self.assertTrue(script.startswith("\\set ON_ERROR_STOP on\nBEGIN;"))
        self.assertTrue(script.rstrip().endswith("ROLLBACK;"))
        self.assertNotRegex(strip_comments(script), r"(?m)^\s*COMMIT\b")

    def test_smoke_checks_are_unique_and_cover_the_rules(self):
        smoke = read(SMOKE)
        labels = re.findall(r"'([^']+)'\);", smoke)
        self.assertEqual(len(labels), len(set(labels)), "smoke labels must be unique")
        for rule in ("skips the gates", "without a revision bump", "audit rows are edited", "duplicate notification",
                     "commercial fact inferred", "sealed change set is edited", "agent approves",
                     "approves their own", "different mapping version", "same job is enqueued twice",
                     "second worker gets nothing", "another tenant sees no submissions"):
            self.assertIn(rule, smoke)

    @unittest.skipUnless(os.environ.get("COMMERCE_OS_TEST_DB_URL"), "COMMERCE_OS_TEST_DB_URL not set")
    def test_live_database(self):
        self.assertEqual(self.mod.main(), 0)


if __name__ == "__main__":
    unittest.main()
