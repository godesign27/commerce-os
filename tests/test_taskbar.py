"""The task bar (B-077): what's being processed, on every page. Everything here is invented and stays on this computer."""
import json
import re
import threading
import time
import unittest

from packages.publisher import records as pub
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, record_for, tmp
from tests.test_storefront_preview import ITEM, MAPPING

BAR = "apps/review-dashboard/src/components/TaskBar.tsx"


def make_app():
    srv = load_server()
    d = tmp()
    out = d / "review"
    (out / "img").mkdir(parents=True)
    (out / "items.json").write_text(json.dumps([dict(ITEM, id="fox", status="ready"), dict(ITEM, id="owl", status="ready")]))
    (d / "mapping.json").write_text(json.dumps(MAPPING))
    app = srv.App(out=out, brand_root=d / "brand", learning_root=d / "learning", config=d / "none.json", source=tmp(),
                  rooms_root=d / "rooms", mapping=d / "mapping.json")
    app.store.save_draft("fox", record_for("fox", 1))
    return app


def queue(app, item):
    app.pubs.append(item, "queued", pub.QUEUED, by="owner", change_set_id="cs", change_set_hash="a" * 64, approval_id="a")


class Activity(unittest.TestCase):
    def setUp(self):
        self.app = make_app()

    def row(self, item="fox"):
        return next(r for r in self.app.activity()["publishing"] if r["id"] == item)

    def test_nothing_happening_shows_nothing(self):
        a = self.app.activity()
        self.assertEqual((a["jobs"], a["publishing"], a["active"]), ([], [], False))

    def test_each_worker_step_has_its_own_words(self):
        self.app.pubs.beat(True)
        queue(self.app, "fox")
        self.assertEqual(self.row()["stage"], "Waiting for the publisher")
        self.assertTrue(self.app.activity()["active"])
        for event, state, words in (("gate4_passed", None, "Final check passed"), ("writing", pub.WRITING, "Sending images"),
                                    ("images_delivered", None, "Adding it to the store")):
            self.app.pubs.append("fox", event, state)
            self.assertEqual(self.row()["stage"], words)
            self.assertTrue(self.row()["active"])
        self.app.pubs.append("fox", "published", pub.SUCCEEDED, receipt_id="r")
        r = self.row()
        self.assertEqual((r["stage"], r["active"]), ("In the store as a Draft", False))
        self.assertFalse(self.app.activity()["active"], "a finished publish isn't still moving")

    def test_it_uses_the_listing_title(self):
        queue(self.app, "fox")
        self.assertNotEqual(self.row()["title"], "fox")

    def test_a_held_publish_says_why(self):
        queue(self.app, "fox")
        self.assertEqual(self.row()["stage"], "Held: the publisher isn't running")
        self.app.pubs.beat(False, "Check the store on Getting started first.")
        self.assertEqual(self.row()["stage"], "Held: Check the store on Getting started first.")
        self.app.pubs.set_kill_switch(True, "owner")
        self.assertEqual(self.row()["stage"], "Held: writing is switched off")

    def test_a_refusal_shows_its_reasons(self):
        queue(self.app, "fox")
        self.app.pubs.append("fox", "gate4_refused", pub.FAILED, reasons=["Changed since you approved it"])
        r = self.row()
        self.assertEqual((r["stage"], r["state"], r["detail"]), ("Didn't go in", pub.FAILED, "Changed since you approved it"))

    def test_old_finished_publishes_drop_off_but_stuck_ones_never_do(self):
        old = pub.Publications(self.app.pubs.root, self.app.pubs.audit, clock=lambda: "2026-01-01T00:00:00Z")
        old.append("owl", "queued", pub.QUEUED)
        old.append("fox", "queued", pub.QUEUED)
        old.append("fox", "published", pub.SUCCEEDED)
        ids = [r["id"] for r in self.app.activity()["publishing"]]
        self.assertEqual(ids, ["owl"], "a publish still queued shows however old it is")

    def test_moving_rows_come_first(self):
        queue(self.app, "owl")
        queue(self.app, "fox")
        self.app.pubs.append("fox", "published", pub.SUCCEEDED)
        self.assertEqual([r["id"] for r in self.app.activity()["publishing"]], ["owl", "fox"])

    def test_jobs_show_while_running_and_for_a_while_after(self):
        go = threading.Event()
        started = self.app._start("Drafting 3 listings", lambda job: (job.update(total=3, done=1), go.wait(5)))
        jobs = self.app.activity()["jobs"]
        self.assertEqual((jobs[0]["id"], jobs[0]["label"], jobs[0]["running"]), (started["job"], "Drafting 3 listings", True))
        self.assertTrue(self.app.activity()["active"])
        go.set()
        for _ in range(50):
            if not self.app.jobs[started["job"]]["running"]:
                break
            time.sleep(0.05)
        self.assertIn("finished_at", self.app.jobs[started["job"]])
        self.assertFalse(self.app.activity()["jobs"][0]["running"])
        self.app.jobs[started["job"]]["finished_at"] -= self.app.RECENT_SECONDS + 1
        self.assertEqual(self.app.activity()["jobs"], [])

    def test_it_is_reachable(self):
        self.assertIn('@route("GET", "/api/activity")', read(REPO / "services/local_api/server.py"))


class Bar(unittest.TestCase):
    def test_it_is_on_every_page(self):
        src = read(REPO / "apps/review-dashboard/src/main.tsx")
        self.assertIn("<TaskBar onSettled=", src)
        self.assertLess(src.index("<TaskBar"), src.index('<footer className="foot">'))

    def test_it_looks_at_once_after_a_change(self):
        api = read(REPO / "apps/review-dashboard/src/api.ts")
        self.assertIn('if (method !== "GET") window.dispatchEvent(new Event(ACTIVITY_EVENT));', api)
        self.assertIn("window.addEventListener(ACTIVITY_EVENT, look);", read(REPO / BAR))

    def test_it_looks_often_only_while_busy(self):
        src = read(REPO / BAR)
        self.assertIn("next.active ? BUSY_MS : IDLE_MS", src)
        self.assertIn("if (document.hidden) return;", src)
        self.assertLessEqual(int(re.search(r"BUSY_MS = (\d+)", src).group(1)), 3000)

    def test_it_refreshes_the_page_when_work_finishes(self):
        self.assertIn("if (wasActive.current && !next.active) onSettled();", read(REPO / BAR))

    def test_it_is_announced_and_respects_reduced_motion(self):
        self.assertIn('role="status" aria-live="polite"', read(REPO / BAR))
        css = read(REPO / "apps/review-dashboard/src/styles.css")
        self.assertIn("@media (prefers-reduced-motion: reduce) { .taskbar.busy .taskbar-dot { animation: none; } }", css)

    def test_storage_failures_dont_break_it(self):
        src = read(REPO / BAR)
        self.assertEqual(len(re.findall(r"try \{[^}]*localStorage", src)), 2)


class StartScript(unittest.TestCase):
    def test_a_failed_build_says_so(self):
        src = read(REPO / "start.sh")
        self.assertNotIn("npm run build --silent >/dev/null", src)
        self.assertIn('if ! out=$(cd "$dash" && npm run build --silent 2>&1); then', src)
        self.assertIn("The dashboard didn't build.", src)
        self.assertIn("The dashboard's packages didn't install.", src)


if __name__ == "__main__":
    unittest.main()
