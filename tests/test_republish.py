"""Updating a piece that's already in the store (B-085). The owner's rule: edits made in the store's admin always win.

The planning rules run without a store. The whole path runs against a private Postgres cluster on a Unix socket, with
the same write login the runbook creates, and is skipped without Postgres or psycopg. All data is invented.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from packages.adapters import updates
from packages.publisher import records as pub
from tests._helpers import REPO, read
from tests import test_publishing as tp         # not its classes: they'd run again here

try:
    import psycopg  # noqa: F401
    from packages.publisher.local_store import LocalStore
    HAVE_PG = LocalStore("storefront-a", Path(tempfile.gettempdir()) / "cos-probe").ldb.available()
except Exception:                                   # noqa: BLE001
    HAVE_PG = False

PUBLISHED = {"name": {"value": "Fox", "status": "human_confirmed"}, "price": {"value": 450, "status": "supplied"},
             "medium": {"value": "Oil", "status": "supplied"}, "status": {"value": "draft", "status": "supplied"},
             "slug": {"value": "fox", "status": "inferred"}}
same_in_store = lambda col, v: v                    # noqa: E731


class Planning(unittest.TestCase):
    def test_only_what_changed_here_is_sent(self):
        now = dict(PUBLISHED, price={"value": 500, "status": "supplied"})
        plan = updates.plan(PUBLISHED, now, {"name": "Fox", "price": 450, "medium": "Oil"}, same_in_store)
        self.assertEqual((list(plan["send"]), plan["expected"], plan["kept"]), (["price"], {"price": 450}, []))

    def test_a_field_edited_in_the_store_is_kept(self):
        now = dict(PUBLISHED, price={"value": 500, "status": "supplied"}, medium={"value": "Acrylic", "status": "supplied"})
        plan = updates.plan(PUBLISHED, now, {"name": "Fox", "price": 475, "medium": "Oil"}, same_in_store)
        self.assertEqual(list(plan["send"]), ["medium"])
        self.assertEqual(plan["kept"], [{"column": "price", "store": 475, "ours": 500}])

    def test_price_and_tiers_are_kept_together(self):
        tiers = {"value": [{"type": "Original", "price": 450}], "status": "supplied"}
        was = dict(PUBLISHED, pricing_tiers=tiers)
        now = dict(was, price={"value": 500, "status": "supplied"},
                   pricing_tiers={"value": [{"type": "Original", "price": 500}], "status": "supplied"})
        store = {"name": "Fox", "price": 475, "medium": "Oil", "pricing_tiers": [{"type": "Original", "price": 450}]}
        plan = updates.plan(was, now, store, same_in_store)
        self.assertEqual((plan["send"], [k["column"] for k in plan["kept"]]), ({}, ["price", "pricing_tiers"]),
                         "never a tier list priced differently from the product")

    def test_status_web_address_and_id_are_never_sent(self):
        now = dict(PUBLISHED, status={"value": "active", "status": "supplied"}, slug={"value": "new", "status": "inferred"},
                   id={"value": "other", "status": "inferred"})
        self.assertEqual(updates.changed_here(PUBLISHED, now), [])
        self.assertNotIn("status", updates.UPDATABLE)
        self.assertNotIn("slug", updates.UPDATABLE)

    def test_values_compare_as_values(self):
        self.assertTrue(updates.same("450.00", 450))
        self.assertTrue(updates.same("450.00", {"x": 1}) is False)
        self.assertTrue(updates.same([{"b": 1, "a": "2"}], '[{"a": "2", "b": 1.0}]'))
        self.assertFalse(updates.same(450, 451))
        self.assertFalse(updates.same(None, ""))

    def test_later_publishes_sit_on_top(self):
        create = {"operations": [{"op": "create", "fields": PUBLISHED}]}
        update = {"operations": [{"op": "update", "fields": {"price": {"value": 500, "status": "supplied"}}}]}
        self.assertEqual(updates.published_fields([create, update])["price"]["value"], 500)
        self.assertEqual(updates.published_fields([create, update])["name"]["value"], "Fox")


@unittest.skipUnless(HAVE_PG, "needs Postgres and psycopg")
class Republish(unittest.TestCase):
    setUp, sql, products = tp.Live.setUp, tp.Live.sql, tp.Live.products

    def publish(self):
        p = self.app.storefront_preview("fox")
        self.app.approve_storefront("fox", {"change_set_hash": p["change_set"]["change_set_hash"], "status": "draft"})
        self.app.publish("fox", {"change_set_hash": p["change_set"]["change_set_hash"]})
        self.worker.run_once()
        self.assertEqual(self.app.pubs.state("fox"), pub.SUCCEEDED)
        return self.app.pubs.latest("fox", "published")["product_id"]

    def change_price(self, amount):
        from tests.test_storefront_preview import FACTS
        self.app.update_listing("fox", {"facts": dict(FACTS, price=str(amount))})
        self.app._rows.clear()                       # read the store afresh, as a page load a moment later would

    def send_update(self):
        p = self.app.storefront_preview("fox")
        self.assertIsNotNone(p["update"], "a changed piece in the store gets an update")
        self.assertTrue(p["approvable"], p["blockers"])
        self.app.approve_storefront("fox", {"change_set_hash": p["change_set"]["change_set_hash"], "status": "unchanged"})
        self.app.publish("fox", {"change_set_hash": p["change_set"]["change_set_hash"]})
        self.worker.run_once()
        return p

    def test_a_published_piece_stays_published_until_it_changes(self):
        self.publish()
        p = self.app.storefront_preview("fox")
        self.assertIsNone(p["update"])
        self.assertEqual(p["approval"]["state"], "current")
        section, row = self.app._queue_row(self.app.item("fox"), self.app.store.draft("fox"))
        self.assertEqual((section, row["status"]["id"]), ("published", "published"))

    def test_a_change_goes_in_as_an_update_and_the_status_stays(self):
        pid = self.publish()
        self.sql(f"UPDATE public.products SET status = 'active' WHERE id = '{pid}'")     # the owner set it live
        self.change_price(520)
        section, row = self.app._queue_row(self.app.item("fox"), self.app.store.draft("fox"))
        self.assertEqual((section, row["status"]["id"]), ("changed", "changed"))
        p = self.send_update()
        self.assertEqual([r["column"] for r in p["rows"]], ["price", "pricing_tiers"], "only what changed: the price and the tier that carries it")
        self.assertEqual(self.app.pubs.state("fox"), pub.SUCCEEDED, self.app.pubs.events("fox")[-3:])
        self.assertEqual(self.app.pubs.latest("fox", "published")["op"], "update")
        price, status = self.sql(f"SELECT price, status FROM public.products WHERE id = '{pid}'")[0]
        self.assertEqual((str(price), status), ("520.00", "active"), "the price changed; the live product stayed live")
        self.assertEqual(len(self.products()), 1, "an update adds nothing")
        self.app._rows.clear()
        self.assertIsNone(self.app.storefront_preview("fox")["update"], "and then it's published again, as it is")

    def test_a_store_edit_is_kept(self):
        pid = self.publish()
        self.sql(f"UPDATE public.products SET price = 499 WHERE id = '{pid}'")            # edited in the store's admin
        self.change_price(520)
        p = self.app.storefront_preview("fox")
        self.assertIsNone(p["update"], "the only change was also made in the store, whose edit wins: nothing to send")
        self.assertEqual(str(self.sql(f"SELECT price FROM public.products WHERE id = '{pid}'")[0][0]), "499.00")

    def test_a_store_edit_after_approving_stops_the_update(self):
        pid = self.publish()
        self.change_price(520)
        p = self.app.storefront_preview("fox")
        self.app.approve_storefront("fox", {"change_set_hash": p["change_set"]["change_set_hash"], "status": "unchanged"})
        self.app.publish("fox", {"change_set_hash": p["change_set"]["change_set_hash"]})
        self.sql(f"UPDATE public.products SET price = 499 WHERE id = '{pid}'")            # edited after the approval
        self.worker.run_once()
        self.assertEqual(self.app.pubs.state("fox"), pub.FAILED)
        self.assertEqual(str(self.sql(f"SELECT price FROM public.products WHERE id = '{pid}'")[0][0]), "499.00",
                         "the store's edit is never overwritten")

    def test_the_write_itself_checks_the_store_again(self):
        """The last line: inside the write's own transaction, after every earlier check has passed."""
        from packages.adapters.artstore_pg import StoreEdited
        from packages.publisher.local_store import WRITE_ROLE
        pid = self.publish()
        self.sql(f"UPDATE public.products SET medium = 'Edited in the store' WHERE id = '{pid}'")
        self.adapter.refresh()
        with psycopg.connect(self.store.dsn(WRITE_ROLE)) as conn:
            with self.assertRaises(StoreEdited):
                with conn:
                    self.adapter._update(conn, "products", pid, {"medium": "Ours"}, {"medium": "Oil on canvas"})
        self.assertEqual(self.sql(f"SELECT medium FROM public.products WHERE id = '{pid}'")[0][0], "Edited in the store")

    def test_the_write_login_can_change_only_the_listings_fields(self):
        from packages.publisher.local_store import WRITE_ROLE
        pid = self.publish()
        self.sql(f"UPDATE public.products SET name = 'Renamed' WHERE id = '{pid}'", WRITE_ROLE)
        for col, value in (("status", "'active'"), ("slug", "'x'"), ("stock", "5")):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=col):
                self.sql(f"UPDATE public.products SET {col} = {value} WHERE id = '{pid}'", WRITE_ROLE)


Republish.setUpClass = classmethod(lambda cls: _up(cls))
Republish.tearDownClass = classmethod(lambda cls: _down(cls))


def _up(cls):
    cls.tmp = Path(tempfile.mkdtemp(prefix="cos-"))
    cls.store = LocalStore("storefront-a", cls.tmp / "store", port=55437)
    from tests.test_storefront_preview import MAPPING
    cls.store.up(MAPPING)


def _down(cls):
    cls.store.down(delete=True)
    shutil.rmtree(cls.tmp, ignore_errors=True)


class OneRead(unittest.TestCase):
    """Pages ask about every changed piece: the store is read once for all of them, not once each (B-085 fix)."""
    def test_one_read_serves_every_published_product_for_a_while(self):
        from tests.test_listing_copy import load_server, tmp
        srv = load_server()
        out = tmp() / "review"
        out.mkdir()
        reads = []
        app = srv.App(out=out, brand_root=out / "brand", learning_root=out / "learning", config=out / "none.json",
                      source=tmp(), read_product=lambda pid: reads.append(pid) or {"id": pid})
        for item, pid in (("fox", "cos-fox"), ("owl", "cos-owl")):
            app.pubs.append(item, "published", pub.SUCCEEDED, product_id=pid)
        self.assertEqual(app.store_product("cos-fox"), {"id": "cos-fox"})
        self.assertEqual(sorted(reads), ["cos-fox", "cos-owl"], "both read together")
        app.store_product("cos-owl")
        app.store_product("cos-fox")
        self.assertEqual(len(reads), 2, "and kept for the next page loads")
        app.store_product("cos-fox", fresh=True)
        self.assertEqual(len(reads), 4, "a fresh look reads again")
        self.assertGreaterEqual(srv.App.STORE_ROW_SECONDS, 30)


class Wiring(unittest.TestCase):
    def test_the_runbook_grants_exactly_the_updatable_columns(self):
        book = read(REPO / "docs/runbooks/write-role.md")
        self.assertIn(f"GRANT UPDATE ({', '.join(updates.UPDATABLE)}) ON public.products TO commerce_os_write;", book)
        self.assertIn("CREATE POLICY commerce_os_write_update ON public.products FOR UPDATE TO commerce_os_write", book)

    def test_the_pages_offer_it(self):
        panel = read(REPO / "apps/review-dashboard/src/components/StorefrontPanel.tsx")
        self.assertIn('"Approve update"', panel)
        self.assertIn('"Update in store"', panel)
        self.assertIn("Kept as the store has it", panel)
        self.assertIn("Changed since published", read(REPO / "apps/review-dashboard/src/pages/Publish.tsx"))


if __name__ == "__main__":
    unittest.main()
