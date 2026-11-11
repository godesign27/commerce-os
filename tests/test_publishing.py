"""Phase 3 publishing (B-070): records, delivery, the worker's rules and recovery, on a real local Postgres.

The live tests start a private cluster on a Unix socket and are skipped without Postgres or psycopg. Everything
in the store is invented. Nothing here reads .env or can reach a real store.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from packages.drafting.audit import Audit
from packages.publisher import assets as asset_store
from packages.publisher import records as pub
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, record_for, tmp
from tests.test_storefront_preview import FACTS, ITEM, MAPPING

try:
    import psycopg
    from packages.adapters.contract import Refused
    from packages.adapters.artstore_pg import NotLocal, PostgresArtStore, require_local
    from packages.publisher.local_store import READ_ROLE, WRITE_ROLE, LocalStore, StoreUnavailable
    from packages.publisher.worker import NOT_FOUND_WAIT, Worker
    HAVE_PG = LocalStore("storefront-a", tmp() / "x").ldb.available()
except ImportError:
    psycopg, HAVE_PG = None, False


class Clock:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return f"2026-11-05T{self.t // 3600:02d}:{self.t // 60 % 60:02d}:{self.t % 60:02d}Z"

    def tick(self, seconds):
        self.t += seconds


def pubs(clock=None):
    root = tmp()
    return pub.Publications(root, Audit(root / "audit"), **({"clock": clock} if clock else {}))


CS = {"change_set_id": "cs-1", "change_set_hash": "a" * 64}
APPROVAL = {"approval_id": "apr-1"}


class Records(unittest.TestCase):
    def setUp(self):
        self.p = pubs()

    def test_asking_queues_it(self):
        self.p.request("fox", CS, APPROVAL, "owner")
        self.assertEqual(self.p.state("fox"), pub.QUEUED)
        self.assertEqual(self.p.in_state(pub.QUEUED), ["fox"])
        self.assertTrue(self.p.audit.events("fox"))

    def test_it_cannot_be_asked_for_twice_at_once(self):
        self.p.request("fox", CS, APPROVAL, "owner")
        with self.assertRaisesRegex(pub.PublishError, "already being published"):
            self.p.request("fox", CS, APPROVAL, "owner")

    def test_an_unknown_outcome_must_be_checked_first(self):
        self.p.append("fox", "outcome_unknown", pub.UNKNOWN)
        with self.assertRaisesRegex(pub.PublishError, "add it twice"):
            self.p.request("fox", CS, APPROVAL, "owner")

    def test_a_published_piece_goes_again_only_as_an_update(self):
        self.p.append("fox", "published", pub.SUCCEEDED)
        with self.assertRaisesRegex(pub.PublishError, "already published: approve an update"):
            self.p.request("fox", CS, APPROVAL, "owner")
        update = dict(CS, operations=[{"op": "update"}])
        self.p.request("fox", update, APPROVAL, "owner")
        self.assertEqual((self.p.state("fox"), self.p.latest("fox", "queued")["op"]), (pub.QUEUED, "update"))
        with self.assertRaisesRegex(pub.PublishError, "nothing to update"):
            self.p.request("owl", update, APPROVAL, "owner")

    def test_what_reached_the_store(self):
        self.p.append("fox", "queued", pub.QUEUED, change_set_hash="h1")
        self.p.append("fox", "published", pub.SUCCEEDED)                       # recorded before B-085: no hash
        self.p.append("fox", "queued", pub.QUEUED, change_set_hash="h2")
        self.p.append("fox", "failed", pub.FAILED)
        self.p.append("fox", "queued", pub.QUEUED, change_set_hash="h3")
        self.p.append("fox", "published", pub.SUCCEEDED, change_set_hash="h3")
        self.assertEqual(self.p.published_hashes("fox"), ["h1", "h3"])

    def test_a_failed_publish_can_be_asked_for_again(self):
        self.p.append("fox", "failed", pub.FAILED)
        self.p.request("fox", CS, APPROVAL, "owner")
        self.assertEqual(self.p.state("fox"), pub.QUEUED)

    def test_recheck_needs_an_unknown_outcome(self):
        with self.assertRaises(pub.PublishError):
            self.p.ask_recheck("fox", "owner")
        self.p.append("fox", "outcome_unknown", pub.UNKNOWN)
        self.assertFalse(self.p.recheck_wanted("fox"))
        self.p.ask_recheck("fox", "owner")
        self.assertTrue(self.p.recheck_wanted("fox"))
        self.p.append("fox", "rechecked", finding="not_found")
        self.assertFalse(self.p.recheck_wanted("fox"))

    def test_the_kill_switch_stops_new_requests(self):
        self.p.set_kill_switch(True, "owner")
        with self.assertRaisesRegex(pub.PublishError, "switched off"):
            self.p.request("fox", CS, APPROVAL, "owner")
        self.p.set_kill_switch(False, "owner")
        self.assertFalse(self.p.kill_switch()["on"])

    def test_the_kill_switch_fails_safe(self):
        (self.p.root).mkdir(parents=True, exist_ok=True)
        (self.p.root / "kill_switch.json").write_text("not json")
        self.assertTrue(self.p.kill_switch()["on"])

    def test_the_setting_forces_it_on(self):
        with mock.patch.dict(os.environ, {"COMMERCE_OS_WRITES_DISABLED": "true"}):
            self.assertTrue(self.p.kill_switch()["on"])
            self.assertTrue(self.p.kill_switch()["forced"])

    def test_a_silent_worker_counts_as_stopped(self):
        clock = Clock()
        p = pubs(clock)
        self.assertFalse(p.worker()["running"])
        p.beat(True)
        self.assertTrue(p.worker()["running"])
        clock.tick(pub.HEARTBEAT_SECONDS + 1)
        self.assertFalse(p.worker()["running"])


class Delivery(unittest.TestCase):
    def setUp(self):
        self.dir = tmp()
        self.file = self.dir / "framed.png"
        self.file.write_bytes(b"pixels")
        self.sha = asset_store._sha256(self.file)
        self.store = asset_store.LocalAssetStore(self.dir / "store")
        self.assets = [{"derivative_id": "d1", "destination_key": "/objects/uploads/fox-framed"}]
        self.files = {"d1": {"file": str(self.file), "sha256": self.sha}}

    def test_it_delivers_the_approved_bytes(self):
        self.assertEqual(self.store.deliver(self.assets, self.files)[0]["result"], "written")
        self.assertEqual((self.dir / "store/objects/uploads/fox-framed").read_bytes(), b"pixels")

    def test_delivering_twice_changes_nothing(self):
        self.store.deliver(self.assets, self.files)
        self.assertEqual(self.store.deliver(self.assets, self.files)[0]["result"], "already_present")

    def test_a_changed_file_is_refused(self):
        self.file.write_bytes(b"different")
        with self.assertRaisesRegex(asset_store.DeliveryError, "isn't the one you approved"):
            self.store.deliver(self.assets, self.files)

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(asset_store.DeliveryError):
            self.store.deliver(self.assets, {})

    def test_a_key_cannot_leave_the_store(self):
        with self.assertRaisesRegex(asset_store.DeliveryError, "outside"):
            self.store.deliver([{"derivative_id": "d1", "destination_key": "/../../escaped"}], self.files)


@unittest.skipUnless(psycopg, "psycopg not installed")
class OnlyLocal(unittest.TestCase):
    def test_a_network_host_is_refused(self):
        for dsn in ("host=db.example.test dbname=x user=y", "postgresql://u:p@127.0.0.1:5432/d", "postgresql://u:p@localhost/d",
                    "host=/tmp,db.example.test dbname=x", "host=/tmp hostaddr=10.0.0.1 dbname=x", "dbname=x"):
            with self.assertRaises(NotLocal, msg=dsn):
                require_local(dsn)

    def test_a_unix_socket_is_accepted(self):
        self.assertTrue(require_local("host=/tmp/socket port=5 dbname=x user=y"))

    def test_the_adapter_checks_both_logins(self):
        for write, reader in (("host=db.example.test", "host=/tmp"), ("host=/tmp", "host=db.example.test")):
            with self.assertRaises(NotLocal):
                PostgresArtStore("s", "test", {}, {"tables": {}}, write_dsn=write, read_dsn=reader, currency="USD", features=[])


@unittest.skipUnless(HAVE_PG, "Postgres or psycopg not installed")
class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="cos-"))
        cls.store = LocalStore("storefront-a", cls.tmp / "store", port=55436)
        cls.store.up(MAPPING)

    @classmethod
    def tearDownClass(cls):
        cls.store.down(delete=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.sql("DELETE FROM public.products")
        self.srv = load_server()
        self.dir = tmp()
        out = self.dir / "review"
        (out / "img").mkdir(parents=True)
        (out / "img" / "fox.framed.jpg").write_bytes(b"framed image")
        (out / "items.json").write_text(json.dumps([dict(ITEM, status="ready")]))
        (self.dir / "mapping.json").write_text(json.dumps(MAPPING))
        self.app = self.srv.App(out=out, brand_root=self.dir / "brand", learning_root=self.dir / "learning",
                                config=self.dir / "none.json", source=tmp(), rooms_root=self.dir / "rooms",
                                mapping=self.dir / "mapping.json")
        self.clock = Clock()
        self.app.pubs.clock = self.clock
        self.out = out
        self.adapter = self.store.adapter()
        self.adapter.writes_enabled = True
        self.images = asset_store.LocalAssetStore(self.dir / "images")
        self.worker = Worker(self.app, self.app.pubs, self.adapter, self.images)
        self.app.store.save_draft("fox", record_for("fox", 1))
        self.app.store.approve("fox", "owner")
        self.app.update_listing("fox", {"facts": FACTS})

    # helpers
    def sql(self, statement, user="postgres"):
        with psycopg.connect(self.store.dsn(user), autocommit=True) as conn:
            cur = conn.execute(statement)
            return cur.fetchall() if cur.description else None

    def products(self):
        return self.sql("SELECT id, status FROM public.products")

    def approve(self):
        p = self.app.storefront_preview("fox")
        self.assertTrue(p["approvable"], p["blockers"])
        return self.app.approve_storefront("fox", {"change_set_hash": p["change_set"]["change_set_hash"], "status": "draft"})

    def queue(self):
        p = self.approve()
        return self.app.publish("fox", {"change_set_hash": p["change_set"]["change_set_hash"]})

    def state(self):
        return self.app.pubs.state("fox")

    def reasons(self):
        return " ".join(self.app.pubs.latest("fox", "gate4_refused")["reasons"])

    # the whole path
    def test_publishing_creates_one_hidden_product_and_reads_it_back(self):
        self.queue()
        self.assertEqual(self.products(), [], "asking writes nothing")
        self.assertEqual(self.worker.run_once(), 1)
        self.assertEqual(self.state(), pub.SUCCEEDED)
        rows = self.products()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "draft", "new products go in hidden")
        price, tiers, tags = self.sql("SELECT price, pricing_tiers, tags FROM public.products")[0]
        self.assertEqual(str(price), "450.00")
        self.assertEqual(tiers[0]["type"], "Original")
        self.assertIsInstance(tags, list)
        done = self.app.pubs.latest("fox", "published")
        self.assertEqual(done["report"]["verified_state"], pub.SUCCEEDED)
        self.assertTrue(done["receipt_id"])

    def test_a_confirmed_ladder_goes_in_and_reads_back(self):
        from tests.test_tier_ladders import LADDER
        (self.dir / "mapping.json").write_text(json.dumps(dict(MAPPING, tier_ladders={"16x20": LADDER})))
        self.app._mapping = None
        self.app._reset_store()
        self.queue()
        self.assertEqual(self.worker.run_once(), 1)
        self.assertEqual(self.state(), pub.SUCCEEDED, self.app.pubs.events("fox"))
        tiers = self.sql("SELECT pricing_tiers FROM public.products")[0][0]
        self.assertEqual([(t["type"], t["price"], t.get("stock")) for t in tiers],
                         [("Original", 450, 1), ("Print", 185, 100), ("Canvas Print", 300, 100)])

    def test_images_go_first_and_are_the_approved_bytes(self):
        self.queue()
        self.worker.run_once()
        names = [e["event"] for e in self.app.pubs.events("fox")]
        self.assertLess(names.index("images_delivered"), names.index("published"))
        delivered = [p for p in (self.dir / "images").rglob("*") if p.is_file()]
        self.assertEqual(delivered[0].read_bytes(), b"framed image")

    def test_it_leaves_the_history_that_audit_needs(self):
        self.queue()
        self.worker.run_once()
        events = [e["event"] for e in self.app.storefront_preview("fox")["history"]]
        for e in ("storefront_approved", "publish_requested", "published"):
            self.assertIn(e, events)

    def test_the_dashboard_reports_it(self):
        self.queue()
        self.worker.run_once()
        doc = self.app.storefront_preview("fox")["publish"]
        self.assertEqual(doc["state"], pub.SUCCEEDED)
        self.assertTrue(doc["product_id"])
        self.assertEqual(self.app.home()["listings"]["published"], 1)

    # the publish page (B-071)
    def section(self):
        q = self.app.publish_queue()
        return next(s for s in ("ready", "working", "problems", "waiting", "published") if q[s])

    def test_a_listing_moves_through_the_publish_page(self):
        self.assertEqual(self.section(), "waiting")
        self.assertTrue(self.app.publish_queue()["waiting"][0]["next"], "it says what's needed next")
        self.approve()
        self.assertEqual(self.section(), "ready")
        self.assertEqual(self.app.home()["listings"]["to_publish"], 1)
        row = self.app.publish_queue()["ready"][0]
        self.assertEqual((row["price"]["amount_minor"], row["sold_as"]), (45000, "Original"))
        res = self.app.publish_many({"items": [{"id": "fox", "change_set_hash": row["change_set_hash"]}]})
        self.assertEqual(res["results"], [{"id": "fox", "ok": True}])
        self.assertEqual(self.products(), [], "asking writes nothing")
        self.assertTrue(res["queue"]["working"])
        self.worker.run_once()
        self.assertEqual(self.section(), "published")
        self.assertEqual(self.app.home()["listings"]["to_publish"], 0)
        self.assertTrue(self.app.publish_queue()["published"][0]["product_id"])

    def test_the_page_can_only_send_the_version_it_showed(self):
        self.approve()
        row = self.app.publish_queue()["ready"][0]
        self.app.update_listing("fox", {"facts": dict(FACTS, price="500.00")})
        res = self.app.publish_many({"items": [{"id": "fox", "change_set_hash": row["change_set_hash"]}]})
        self.assertFalse(res["results"][0]["ok"])
        self.assertIsNone(self.state(), "nothing was queued")
        self.assertEqual(self.section(), "waiting", "a changed listing needs approving again")

    def test_a_newer_approval_is_not_sent_by_an_old_page(self):
        self.approve()
        shown = self.app.publish_queue()["ready"][0]["change_set_hash"]
        self.app.update_listing("fox", {"facts": dict(FACTS, price="500.00")})
        self.approve()
        res = self.app.publish_many({"items": [{"id": "fox", "change_set_hash": shown}]})
        self.assertFalse(res["results"][0]["ok"], "the owner hasn't seen this version on this page")
        self.assertIsNone(self.state())

    def test_only_a_listing_that_can_be_sent_offers_a_version(self):
        self.assertIsNone(self.app.publish_queue()["waiting"][0]["change_set_hash"])
        self.queue()
        self.assertIsNone(self.app.publish_queue()["working"][0]["change_set_hash"])

    def test_one_refused_does_not_stop_the_rest(self):
        self.approve()
        row = self.app.publish_queue()["ready"][0]
        res = self.app.publish_many({"items": [{"id": "nope", "change_set_hash": "x"},
                                               {"id": "fox", "change_set_hash": row["change_set_hash"]}]})
        self.assertEqual([r["ok"] for r in res["results"]], [False, True])

    def test_the_kill_switch_stops_the_whole_page(self):
        self.approve()
        row = self.app.publish_queue()["ready"][0]
        self.app.kill_switch({"on": True})
        res = self.app.publish_many({"items": [{"id": "fox", "change_set_hash": row["change_set_hash"]}]})
        self.assertFalse(res["results"][0]["ok"])
        self.assertIsNone(self.state())

    def test_a_publish_all_without_versions_is_refused(self):
        for body in ({}, {"items": []}, {"items": ["fox"]}, {"items": [{"id": "fox"}]}, {"all": True}):
            with self.assertRaises(self.srv.ApiError):
                self.app.publish_many(body)

    def test_a_rejected_photo_is_not_on_the_page(self):
        with mock.patch.object(self.app, "decisions", return_value={"fox": {"decision": "reject"}}):
            q = self.app.publish_queue()
        self.assertFalse(q["ready"] or q["waiting"] or q["published"])

    # asking
    def test_it_must_be_approved_first(self):
        hash_ = self.app.storefront_preview("fox")["change_set"]["change_set_hash"]
        with self.assertRaisesRegex(self.srv.ApiError, "approve it first"):
            self.app.publish("fox", {"change_set_hash": hash_})

    def test_it_must_be_the_version_approved(self):
        self.approve()
        with self.assertRaisesRegex(self.srv.ApiError, "approve it first"):
            self.app.publish("fox", {"change_set_hash": "0" * 64})

    # Gate 4
    def test_a_listing_changed_after_asking_is_refused(self):
        self.queue()
        (self.out / "img" / "fox.framed.jpg").write_bytes(b"re-cropped")
        self.worker.run_once()
        self.assertEqual(self.state(), pub.FAILED)
        self.assertIn("changed since you approved", self.reasons())
        self.assertEqual(self.products(), [])

    def test_a_newer_approval_replaces_a_queued_one(self):
        self.queue()
        self.app.approvals.approve("fox", self.app.change_set("fox")[0], seen_hash=self.app.change_set("fox")[0]["change_set_hash"],
                                   status="draft", actor_id="owner")
        self.worker.run_once()
        self.assertEqual(self.state(), pub.FAILED)
        self.assertIn("different approval", self.reasons())
        self.assertEqual(self.products(), [])

    def test_the_kill_switch_stops_a_queued_publish(self):
        self.queue()
        self.app.pubs.set_kill_switch(True, "owner")
        self.worker.run_once()
        self.assertEqual(self.state(), pub.FAILED)
        self.assertIn("switched off", self.reasons())
        self.assertEqual(self.products(), [])

    def test_the_kill_switch_stops_it_at_the_last_moment(self):
        self.queue()
        real = self.images.deliver

        def deliver_then_stop(*a):
            out = real(*a)
            self.app.pubs.set_kill_switch(True, "owner")
            return out
        self.images.deliver = deliver_then_stop
        self.worker.run_once()
        self.assertEqual(self.state(), pub.FAILED)
        self.assertEqual(self.products(), [])

    def test_a_changed_store_structure_is_refused(self):
        self.queue()
        self.sql("ALTER TABLE public.products ADD COLUMN surprise text")
        try:
            self.worker.run_once()
        finally:
            self.sql("ALTER TABLE public.products DROP COLUMN surprise")
        self.assertEqual(self.state(), pub.FAILED)
        self.assertIn("schema fingerprint", self.reasons())
        self.assertEqual(self.products(), [])

    def test_a_taken_web_address_is_refused_by_the_store(self):
        self.queue()
        slug = self.app.change_set("fox")[0]["operations"][0]["fields"]["slug"]["value"]
        self.sql(f"INSERT INTO public.products (id, name, slug, price, status) VALUES ('other', 'Other', '{slug}', 1, 'active')")
        self.worker.run_once()
        self.assertEqual(self.state(), pub.FAILED)
        self.assertEqual(len(self.products()), 1)
        reason = self.app.pubs.latest("fox", "failed")["reasons"][0]
        self.assertIn("refused", reason)
        self.assertIn("web address", reason, "it says what to do, in plain words")
        self.assertNotIn("constraint", reason)

    def test_someone_elses_product_with_this_id_is_never_overwritten(self):
        self.queue()
        key = self.app.change_set("fox")[0]["operations"][0]["key"]
        self.sql(f"INSERT INTO public.products (id, name, slug, price, status) VALUES ('{key}', 'Theirs', 'theirs', 1, 'active')")
        self.worker.run_once()
        self.assertEqual(self.state(), pub.FAILED)
        self.assertEqual(self.sql("SELECT name FROM public.products")[0][0], "Theirs")

    def test_a_hostile_title_is_only_ever_text(self):
        title = "x'); DROP TABLE public.products; --"
        self.app.unlock("fox")
        self.app.save_copy("fox", {"fields": {"title": title}})
        self.app.store.approve("fox", "owner")
        self.queue()
        self.worker.run_once()
        self.assertEqual(self.state(), pub.SUCCEEDED, self.app.pubs.events("fox")[-1])
        self.assertEqual(self.sql("SELECT name FROM public.products")[0][0], title)

    def test_the_adapter_refuses_without_an_approval_whatever_the_worker_did(self):
        self.approve()
        approved = self.app.approvals.latest("fox")["change_set"]
        self.adapter.delivered = {a["derivative_id"] for a in approved["assets"]}
        with self.assertRaises(Refused) as e:
            self.adapter.publish_approved(approved, None)
        self.assertEqual(e.exception.issues[0].code, "no_approval")
        self.assertEqual(self.products(), [])

    def test_a_write_that_does_not_read_back_is_not_called_published(self):
        self.queue()
        real = self.adapter.reconcile
        self.adapter.reconcile = lambda *a: dict(real(*a), verified_state=pub.UNKNOWN)
        self.worker.run_once()
        self.adapter.reconcile = real
        self.assertEqual(self.state(), pub.UNKNOWN)
        self.assertIsNone(self.app.pubs.latest("fox", "published"))

    # recovery
    def test_a_repeat_adds_no_second_product(self):
        self.queue()
        self.worker.run_once()
        last = self.app.approvals.latest("fox")
        again = self.adapter.publish_approved(last["change_set"], last["approval"])
        self.assertTrue(again.replayed)
        self.assertEqual(again.operations[0]["result"], "already_present")
        self.assertEqual(len(self.products()), 1)

    def test_a_response_lost_after_commit_recovers_without_a_second_product(self):
        self.queue()
        self.adapter.fail_next("lose_response")
        self.worker.run_once()
        self.assertEqual(self.state(), pub.SUCCEEDED, "reading back finds what was written")
        self.assertEqual(len(self.products()), 1)
        self.assertTrue(self.app.pubs.latest("fox", "published")["receipt_id"].startswith("recovered-"))

    def test_a_connection_lost_before_commit_is_not_called_published(self):
        self.queue()
        self.adapter.fail_next("lose_before_commit")
        self.worker.run_once()
        self.assertEqual(self.state(), pub.UNKNOWN)
        self.assertEqual(self.products(), [])
        with self.assertRaisesRegex(self.srv.ApiError, "add it twice"):
            self.app.publish("fox", {"change_set_hash": self.app.storefront_preview("fox")["change_set"]["change_set_hash"]})

    def test_not_found_twice_apart_makes_it_safe_to_publish_again(self):
        self.queue()
        self.adapter.fail_next("lose_before_commit")
        self.worker.run_once()
        self.clock.tick(5)
        self.app.publish_recheck("fox")
        self.worker.run_once()
        self.assertEqual(self.state(), pub.UNKNOWN, "too soon to be sure")
        self.clock.tick(NOT_FOUND_WAIT)
        self.app.publish_recheck("fox")
        self.worker.run_once()
        self.assertEqual(self.state(), pub.FAILED)
        self.queue_again()
        self.worker.run_once()
        self.assertEqual(self.state(), pub.SUCCEEDED)
        self.assertEqual(len(self.products()), 1)

    def queue_again(self):
        p = self.app.storefront_preview("fox")
        self.app.publish("fox", {"change_set_hash": p["change_set"]["change_set_hash"]})

    def test_a_product_that_does_not_match_stops_and_asks(self):
        self.queue()
        self.adapter.fail_next("lose_response")
        real = self.adapter.reconcile
        self.adapter.reconcile = lambda *a: (self.sql("UPDATE public.products SET medium = 'changed by someone'"), real(*a))[1]
        self.worker.run_once()
        self.adapter.reconcile = real
        self.assertEqual(self.state(), pub.UNKNOWN)
        doc = self.app.storefront_preview("fox")["publish"]
        self.assertEqual((doc["finding"], doc["fields"]), ("mismatch", ["medium"]))
        self.assertEqual(self.sql("SELECT medium FROM public.products")[0][0], "changed by someone", "never overwritten")

    def test_a_worker_that_stopped_mid_write_looks_first(self):
        self.queue()
        self.app.pubs.append("fox", "writing", pub.WRITING)
        self.worker.recover()
        self.assertEqual(self.state(), pub.UNKNOWN)
        self.assertEqual(self.products(), [])

    def test_a_worker_that_stopped_after_committing_finds_it(self):
        self.queue()
        self.worker.run_once()
        self.app.pubs.append("fox", "writing", pub.WRITING)
        self.worker.recover()
        self.assertEqual(self.state(), pub.SUCCEEDED)
        self.assertEqual(len(self.products()), 1)

    def test_a_failed_delivery_writes_no_product(self):
        self.queue()
        self.images.deliver = mock.Mock(side_effect=asset_store.DeliveryError("disk full"))
        self.worker.run_once()
        self.assertEqual(self.state(), pub.FAILED)
        self.assertEqual(self.products(), [])

    # the logins
    def expect_denied(self, role, statement):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=statement):
            self.sql(statement, role)

    def test_the_write_login_can_only_add_products(self):
        self.sql("INSERT INTO public.products (id, name, slug, price, status) VALUES ('w', 'W', 'w', 1, 'draft')", WRITE_ROLE)
        self.expect_denied(WRITE_ROLE, "UPDATE public.products SET status = 'active'")    # updates never touch these (B-085)
        self.expect_denied(WRITE_ROLE, "UPDATE public.products SET slug = 'x'")
        self.expect_denied(WRITE_ROLE, "UPDATE public.products SET id = 'x'")
        self.expect_denied(WRITE_ROLE, "DELETE FROM public.products")
        self.expect_denied(WRITE_ROLE, "TRUNCATE public.products")
        self.expect_denied(WRITE_ROLE, "INSERT INTO public.categories (id, name, slug) VALUES ('c', 'c', 'c')")
        self.expect_denied(WRITE_ROLE, "SELECT * FROM public.users")
        self.expect_denied(WRITE_ROLE, "SELECT * FROM public.orders")

    def test_the_read_login_cannot_write(self):
        with self.assertRaises(psycopg.Error):
            self.sql("INSERT INTO public.products (id, name, slug, price, status) VALUES ('r', 'R', 'r', 1, 'draft')", READ_ROLE)
        self.assertEqual(self.products(), [])

    def test_the_store_has_the_real_structure(self):
        self.adapter.refresh()
        self.assertEqual(self.adapter.fingerprint, self.store._structure()["fingerprint"])

    def test_the_same_rules_as_the_fake(self):
        self.adapter.refresh()
        doc = self.adapter.dry_run(self.app.change_set("fox")[0])
        self.assertTrue(doc["dry_run"])
        self.assertIn("assets_not_delivered", [i["code"] for i in doc["issues"]])
        self.assertIs(self.adapter.capabilities()["fake"], False)


class Wiring(unittest.TestCase):
    SERVER = "services/local_api/server.py"
    WORKER_FILES = ("services/workers/publisher.py", "packages/publisher/worker.py", "packages/publisher/local_store.py",
                    "packages/publisher/records.py", "packages/adapters/artstore_pg.py")

    def test_the_dashboard_holds_no_way_to_write(self):
        src = read(REPO / self.SERVER)
        for forbidden in ("artstore_pg", "publisher.local_store", "publisher.worker", "import local_store", "import worker", "LocalStore", "publish_approved", "WRITE_DB_URL", "psycopg"):
            self.assertNotIn(forbidden, src)

    def test_the_worker_never_reads_a_real_login(self):
        for rel in self.WORKER_FILES:
            src = read(REPO / rel)
            self.assertNotIn('".env"', src, rel)
            self.assertNotIn("_DB_URL", src, rel)
            self.assertNotIn("read_env", src, rel)

    def test_the_adapter_is_local_only(self):
        src = read(REPO / "packages/adapters/artstore_pg.py")
        self.assertIn("if live_host is not None else require_local", src)
        self.assertIn("self.write_dsn, self.read_dsn = allowed(write_dsn), allowed(read_dsn)", src)
        for rel in self.WORKER_FILES:
            if rel != "packages/adapters/artstore_pg.py":
                self.assertNotIn("live_host", read(REPO / rel), "only live_store.py may name a live host")

    def test_writes_are_parameters_only(self):
        self.assertIn("sql.Placeholder()", read(REPO / "packages/adapters/artstore_pg.py"))

    def test_the_real_store_stays_locked(self):
        src = read(REPO / "packages/onboarding.py")
        self.assertIn('"asset_upload": "not_authorized", "writes_enabled": False', src)

    def test_change_sets_can_be_published_only_from_the_server_build(self):
        self.assertIn("simulated: bool = True", read(REPO / "packages/adapters/artstore_map.py"))
        self.assertIn("simulated=False", read(REPO / self.SERVER))

    def test_the_routes_exist(self):
        src = read(REPO / self.SERVER)
        for route in ('/publish")', '/publish/recheck")', '"/api/publishing/kill-switch"'):
            self.assertIn(route, src)

    def test_start_runs_the_worker_and_stops_it(self):
        src = read(REPO / "start.sh")
        self.assertIn("services/workers/publisher.py", src)
        self.assertIn("trap stop EXIT INT TERM", src)
        self.assertIn('kill "$SERVER" "$WORKER"', src, "stopping leaves nothing running")
        self.assertIn('wait "$SERVER"', src, "a foreground server would hold back the stop signal")

    def test_the_publish_page_sorts_by_what_happened_first(self):
        srv = load_server()
        where = srv.App._queue_section
        self.assertEqual(where(None, "current"), "ready")
        self.assertEqual(where(None, "none"), "waiting")
        self.assertEqual(where(None, "out_of_date"), "waiting")
        self.assertEqual(where(pub.FAILED, "current"), "problems")
        self.assertEqual(where(pub.FAILED, "out_of_date"), "waiting")
        self.assertEqual(where(pub.UNKNOWN, "out_of_date"), "problems", "an unknown result is never forgotten")
        self.assertEqual(where(pub.QUEUED, "out_of_date"), "working")
        self.assertEqual(where(pub.WRITING, "current"), "working")
        self.assertEqual(where(pub.SUCCEEDED, "out_of_date"), "published", "it stays published")

    def test_the_publish_page_is_honest_about_where_it_goes(self):
        page = read(REPO / "apps/review-dashboard/src/pages/Publish.tsx")
        self.assertEqual(page.count("Publishing to: {q.target}"), 2, "both targets name where it goes")
        self.assertIn("nothing appears on your site", page)
        self.assertIn("as a hidden draft on", page)
        self.assertIn("{q.live", page)
        self.assertIn("Stop all writing", page)
        self.assertIn("Select all", page)
        self.assertIn("disabled={busy || off || !ticked}", page, "Publish needs something ticked and writing on")
        self.assertIn("if (selected.length) send(selected);", page, "only ready listings are ever sent")
        self.assertIn("useState<Set<string>>(new Set())", page, "nothing is ticked until the owner ticks it")
        self.assertIn("const selected = q.ready.filter(", page, "what's sent comes from the ready list alone")
        self.assertIn("Not published: ", page, "a ticked listing that isn't ready says why")
        self.assertIn("change_set_hash: r.change_set_hash!", page, "each request names the version shown")
        self.assertIn('"Publish"]', read(REPO / "apps/review-dashboard/src/main.tsx"))

    def test_the_publish_page_routes_exist(self):
        src = read(REPO / self.SERVER)
        self.assertIn('@route("GET", "/api/publishing/queue")', src)
        self.assertIn('@route("POST", "/api/publishing/publish")', src)

    def test_the_dashboard_labels_the_target(self):
        panel = read(REPO / "apps/review-dashboard/src/components/StorefrontPanel.tsx")
        self.assertIn("api.publish(id", panel)
        self.assertIn("Check again", panel)
        self.assertIn("Stop all writing", panel)
        self.assertIn("{pub!.target.toLowerCase()}", panel)

    def test_the_store_address_is_the_same_in_every_process(self):
        self.assertNotIn("hash(str(", read(REPO / "packages/publisher/local_store.py"))

    def test_the_local_store_is_never_committed(self):
        self.assertIn(".commerce-os/", read(REPO / ".gitignore"))


if __name__ == "__main__":
    unittest.main()
