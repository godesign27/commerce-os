"""Phase 2's first leg: reading a store's catalog and matching against it (B-065), and the local inbox (B-066).

No database, no network: a stand-in plays the store. Every product and name is invented.
"""
import json
import time
import unittest

from PIL import Image

from packages.adapters import artstore_map as am
from packages.adapters import catalog as cat
from packages.image_pipeline import intake
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, record_for, tmp
from tests.test_storefront_preview import ASSETS, FACTS, ITEM, MAPPING

READ_ONLY = {t: {"SELECT": True} for t in cat.ALLOWED}
LION = {"id": "p1", "name": "Quiet Lion", "slug": "quiet-lion", "sku": None, "status": "active", "category_id": "c1",
        "is_original": True, "medium": "acrylic on canvas", "dimensions": "16 x 20 in"}
OWL = {"id": "p2", "name": "Night Owl", "slug": "night-owl", "sku": None, "status": "active", "category_id": "c1",
       "is_original": False, "medium": "giclee", "dimensions": "8 x 10 in"}
ROOSTER = {"id": "p3", "name": "Lion Among Roosters", "slug": "lion-among-roosters", "sku": None, "status": "draft",
           "category_id": "c1", "is_original": True, "medium": None, "dimensions": None}


def snapshot(products, storefront="storefront-a"):
    return {"storefront": storefront, "read_at": "2026-11-04T10:00:00Z", "products": products,
            "categories": [], "tags": []}


class FakePg:
    def __init__(self, privileges, products=()):
        self.privileges, self.products, self.queries = privileges, list(products), []

    def rows(self, sql):
        self.queries.append(sql)
        if "pg_class" in sql:
            return [dict(row, t=t) for t, row in self.privileges.items()]
        return [dict(p) for p in self.products] if "public.products" in sql else []


class ReadingTheStore(unittest.TestCase):
    def test_a_catalog_only_login_is_fine(self):
        self.assertEqual(cat.guard(READ_ONLY), [])

    def test_a_login_that_can_write_is_refused_before_any_row_is_read(self):
        pg = FakePg(dict(READ_ONLY, products={"SELECT": True, "INSERT": True}), [LION])
        with self.assertRaisesRegex(cat.CatalogError, "can change data"):
            cat.read_snapshot(pg, "storefront-a", "now")
        self.assertFalse([q for q in pg.queries if "public.products" in q])

    def test_a_login_that_sees_customer_tables_is_refused(self):
        with self.assertRaisesRegex(cat.CatalogError, "beyond the catalog"):
            cat.read_snapshot(FakePg(dict(READ_ONLY, orders={"SELECT": True})), "storefront-a", "now")

    def test_a_login_missing_a_catalog_table_is_refused(self):
        self.assertIn("can't read: tags", cat.guard({"products": {"SELECT": True}, "categories": {"SELECT": True}})[0])

    def test_only_reads_and_never_prices_or_stock(self):
        pg = FakePg(READ_ONLY, [LION])
        snap = cat.read_snapshot(pg, "storefront-a", "now")
        self.assertEqual(snap["products"][0]["name"], "Quiet Lion")
        for q in pg.queries:
            self.assertTrue(q.startswith("SELECT"), q)
        products = next(q for q in pg.queries if "public.products" in q)
        for col in ("price", "stock", "pricing_tiers", "*"):
            self.assertNotIn(col, products)


class TheSavedCopy(unittest.TestCase):
    def setUp(self):
        self.c = cat.Catalog(tmp(), "storefront-a")

    def test_saves_and_loads(self):
        self.assertIsNone(self.c.load())
        self.c.save(snapshot([LION]))
        self.assertEqual(self.c.load()["products"][0]["id"], "p1")

    def test_zero_rows_never_replaces_a_catalog_that_had_products(self):
        self.c.save(snapshot([LION]))
        with self.assertRaisesRegex(cat.CatalogError, "read policy"):
            self.c.save(snapshot([]))
        self.assertEqual(len(self.c.load()["products"]), 1)

    def test_one_stores_catalog_is_never_used_for_the_other(self):
        with self.assertRaisesRegex(cat.CatalogError, "another storefront"):
            self.c.save(snapshot([LION], "storefront-b"))
        self.c.path.parent.mkdir(parents=True, exist_ok=True)
        self.c.path.write_text(json.dumps(snapshot([LION], "storefront-b")))
        with self.assertRaisesRegex(cat.CatalogError, "another storefront"):
            self.c.load()

    def test_answers_are_kept_per_piece_and_the_latest_counts(self):
        self.c.answer("a", "p1", "same", "owner", "t1")
        self.c.answer("a", "p1", "different", "owner", "t2")
        self.c.answer("b", "p1", "same", "owner", "t3")
        self.assertEqual(self.c.answers("a"), {"p1": "different"})
        self.c.answer("a", "p1", None, "owner", "t4")
        self.assertEqual(self.c.answers("a"), {})
        self.assertEqual(self.c.answers("b"), {"p1": "same"})


class Matching(unittest.TestCase):
    def find(self, title="Quiet Lion", **kw):
        kw.setdefault("products", [OWL, ROOSTER, LION])
        return cat.find_matches(title=title, **kw)

    def test_same_title_is_likely_and_ranks_first(self):
        found = self.find()
        self.assertEqual((found[0]["product_id"], found[0]["level"]), ("p1", "likely"))
        self.assertIn("Same web address", found[0]["matching"])

    def test_sharing_one_word_is_only_possible(self):
        found = self.find("The Lion Sleeps", products=[ROOSTER])
        self.assertEqual(found[0]["level"], "possible")
        self.assertFalse(cat.issues(found))

    def test_generic_words_and_plurals(self):
        self.assertEqual(cat.words("The Lions of Art Painting"), {"lion"})
        self.assertFalse(self.find("Original Art Print", products=[OWL]))

    def test_the_subject_finds_a_differently_titled_piece(self):
        found = self.find("Golden Morning", subject="owl", products=[OWL])
        self.assertEqual(found[0]["level"], "possible")
        self.assertIn("owl", found[0]["matching"][0])

    def test_nothing_in_common_gives_nothing(self):
        self.assertEqual(self.find("Blue Horizon"), [])

    def test_conflicts_are_shown_and_do_not_decide(self):
        found = self.find(facts={"medium": "oil", "dimensions": "20 x 24 in", "sold_as": "Print"})
        self.assertEqual(found[0]["level"], "likely")
        self.assertEqual(len(found[0]["conflicting"]), 3)

    def test_the_same_size_written_differently_is_not_a_conflict(self):
        found = self.find(facts={"dimensions": '16.0" x 20"'})
        self.assertEqual(found[0]["conflicting"], [])

    def test_a_likely_match_asks_until_answered(self):
        self.assertEqual(cat.issues(self.find())[0]["target"], "catalog.match")
        self.assertEqual(cat.issues(self.find(answers={"p1": "different"})), [])

    def test_same_piece_keeps_blocking(self):
        issues = cat.issues(self.find(answers={"p1": "same"}))
        self.assertIn("can't be approved as a new one", issues[0]["question"])

    def test_an_answered_candidate_stays_visible(self):
        many = [dict(LION, id=f"x{i}", name=f"Quiet Lion {i}", slug=f"s{i}") for i in range(9)]
        tail = dict(ROOSTER, id="zz")
        found = cat.find_matches(title="Quiet Lion", products=many + [tail], answers={"zz": "same"})
        self.assertIn("zz", [c["product_id"] for c in found])


class ChangeSet(unittest.TestCase):
    def build(self, **kw):
        record = record_for("fox")
        entry = {"facts": FACTS, "approved": {"revision": 1}}
        copy = {"title": "Quiet Lion", "short_description": "s", "collector_description": "d", "store_tags": []}
        return am.build(item=ITEM, entry=entry, record=record, copy=copy, assets=ASSETS, mapping=MAPPING,
                        store=am.test_store("storefront-a", MAPPING), **kw)

    def test_a_catalog_value_never_becomes_a_field(self):
        plain, asked = self.build(), self.build(catalog_issues=[{"target": "catalog.match", "question": "same?"}])
        self.assertEqual(plain["operations"], asked["operations"])
        self.assertFalse(am.approvable(asked))
        self.assertTrue(am.approvable(plain))

    def test_a_new_match_puts_an_approval_out_of_date_and_says_why(self):
        plain, asked = self.build(), self.build(catalog_issues=[{"target": "catalog.match", "question": "same?"}])
        self.assertNotEqual(plain["change_set_hash"], asked["change_set_hash"])
        self.assertEqual(am.differences(plain, asked), ["Store catalog"])

    def test_a_taken_web_address_moves_aside(self):
        slug = self.build(taken_slugs={"quiet-lion"})["operations"][0]["fields"]["slug"]["value"]
        self.assertTrue(slug.startswith("quiet-lion-"), slug)


def photo(path, size=(40, 50), color=(200, 30, 30), fmt="JPEG"):
    Image.new("RGB", size, color).save(path, fmt)
    return path


class Inbox(unittest.TestCase):
    def setUp(self):
        self.dir = tmp()
        self.inbox, self.source, self.root = self.dir / "inbox", self.dir / "source", self.dir / "intake"
        self.inbox.mkdir()

    def scan(self):
        return intake.scan(self.inbox, self.source, self.root)

    def test_a_photo_comes_in_and_the_original_is_kept_unchanged(self):
        before = photo(self.inbox / "Fox.jpg").read_bytes()
        res = self.scan()
        self.assertEqual([a["source_name"] for a in res["added"]], ["Fox.jpg"])
        self.assertEqual((self.source / "Fox.jpg").read_bytes(), before)
        self.assertEqual((self.inbox / "imported" / "Fox.jpg").read_bytes(), before)
        self.assertEqual(intake.waiting(self.inbox), [])

    def test_the_journal_records_where_it_came_from(self):
        photo(self.inbox / "Fox.jpg")
        self.scan()
        rec = json.loads((self.root / "journal.jsonl").read_text().splitlines()[0])
        self.assertEqual(rec["provider"], "local_folder")
        self.assertEqual(rec["outcome"], "added")
        self.assertEqual(rec["sha256"], intake.sha256(self.source / "Fox.jpg"))
        self.assertTrue(rec["submission_id"].startswith("sub-"))

    def test_the_same_photo_under_another_name_is_not_added_twice(self):
        photo(self.inbox / "Fox.jpg")
        self.scan()
        photo(self.inbox / "Fox copy.jpg")
        res = self.scan()
        self.assertEqual(res["added"], [])
        self.assertEqual(res["duplicates"], [{"name": "Fox copy.jpg", "same_as": "Fox.jpg"}])
        self.assertEqual(sorted(p.name for p in self.source.iterdir()), ["Fox.jpg"])

    def test_two_identical_files_in_one_look_become_one(self):
        photo(self.inbox / "a.jpg"), photo(self.inbox / "b.jpg")
        res = self.scan()
        self.assertEqual((len(res["added"]), len(res["duplicates"])), (1, 1))

    def test_a_different_photo_with_a_taken_name_keeps_both(self):
        photo(self.inbox / "Fox.jpg")
        self.scan()
        photo(self.inbox / "Fox.jpg", color=(10, 200, 40))
        res = self.scan()
        self.assertEqual(res["added"][0]["source_name"], "Fox (2).jpg")
        self.assertEqual(len(list((self.inbox / "imported").iterdir())), 2)

    def test_a_photo_already_in_the_source_folder_counts_as_seen(self):
        self.source.mkdir()
        photo(self.source / "Old.jpg")
        photo(self.inbox / "New name.jpg")
        self.assertEqual(self.scan()["duplicates"][0]["same_as"], "Old.jpg")

    def test_problem_files_stay_put_with_a_reason(self):
        (self.inbox / "notes.txt").write_text("hello")
        (self.inbox / "broken.jpg").write_bytes(b"\xff\xd8\xff not really")
        (self.inbox / "empty.png").write_bytes(b"")
        (self.inbox / "phone.heic").write_bytes(b"not decodable here")
        (self.inbox / "a folder").mkdir()
        res = self.scan()
        reasons = {p["name"]: p["reason"] for p in res["problems"]}
        self.assertEqual(len(reasons), 5)
        self.assertIn("damaged or still copying", reasons["broken.jpg"])
        self.assertIn("Export it as JPEG", reasons["phone.heic"])
        self.assertEqual(res["added"], [])
        self.assertEqual(len(intake.waiting(self.inbox)), 5)
        self.assertFalse(self.source.exists() and list(self.source.iterdir()))

    def test_a_half_copied_photo_is_refused(self):
        p = photo(self.inbox / "big.jpg", size=(800, 800))
        data = p.read_bytes()
        p.write_bytes(data[:len(data) // 2])
        self.assertIn("still copying", self.scan()["problems"][0]["reason"])

    def test_limits_apply_before_decoding(self):
        p = photo(self.inbox / "wide.png", size=(100, 100), fmt="PNG")
        original = intake.MAX_PIXELS
        intake.MAX_PIXELS = 50
        try:
            self.assertIn("megapixel", intake.check(p)["problem"])
        finally:
            intake.MAX_PIXELS = original
        original = intake.MAX_BYTES
        intake.MAX_BYTES = 10
        try:
            self.assertIn("limit", intake.check(p)["problem"])
        finally:
            intake.MAX_BYTES = original

    def test_a_shortcut_is_not_followed(self):
        target = photo(self.dir / "elsewhere.jpg")
        (self.inbox / "link.jpg").symlink_to(target)
        self.assertIn("shortcut", self.scan()["problems"][0]["reason"])
        self.assertFalse(self.source.exists() and list(self.source.iterdir()))

    def test_a_big_batch_leaves_the_rest_for_next_time(self):
        for i in range(3):
            photo(self.inbox / f"p{i}.jpg", color=(i * 40, 10, 10))
        original = intake.MAX_BATCH
        intake.MAX_BATCH = 2
        try:
            res = self.scan()
        finally:
            intake.MAX_BATCH = original
        self.assertEqual((len(res["added"]), res["left"]), (2, 1))
        self.assertEqual(intake.status(self.inbox, self.root)["waiting"], 1)

    def test_everything_it_adds_gets_listed_by_the_pipeline(self):
        srv = load_server()
        self.assertLessEqual(intake.LISTED_EXT, srv.ri.IMAGE_EXT)


class Api(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        self.dir = tmp()
        self.out = self.dir / "review"
        self.out.mkdir()
        self.source = self.dir / "source"
        self.source.mkdir()
        (self.out / "items.json").write_text(json.dumps([dict(ITEM, id="fox", framed=None)]))
        mapping = self.dir / "mapping.json"
        mapping.write_text(json.dumps(MAPPING))
        self.snap = snapshot([LION, OWL])
        self.app = self.srv.App(out=self.out, source=self.source, mapping=mapping, config=self.dir / "none.json",
                                brand_root=self.dir / "brand", learning_root=self.dir / "learning",
                                rooms_root=self.dir / "rooms", read_catalog=lambda: self.snap)
        self.app.store.save_draft("fox", record_for("fox"))

    def wait(self, res):
        for _ in range(500):
            job = self.app.jobs[res["job"]]
            if not job["running"]:
                return job
            time.sleep(0.01)
        self.fail("job didn't finish")

    def test_reading_the_catalog_saves_a_copy(self):
        self.assertIsNone(self.app.storefront_preview("fox")["catalog"]["read_at"])
        job = self.wait(self.app.refresh_catalog())
        self.assertIsNone(job["error"])
        self.assertEqual(self.app.storefront_preview("fox")["catalog"]["products"], 2)

    def test_a_failed_read_says_why_and_keeps_the_last_copy(self):
        self.wait(self.app.refresh_catalog())
        self.snap = snapshot([])
        job = self.wait(self.app.refresh_catalog())
        self.assertIn("read policy", job["error"])
        self.assertEqual(self.app.storefront_preview("fox")["catalog"]["products"], 2)

    def test_answering_needs_a_product_in_the_catalog_and_is_audited(self):
        self.wait(self.app.refresh_catalog())
        with self.assertRaises(self.srv.ApiError):
            self.app.answer_match("fox", {"product_id": "nope", "answer": "same"})
        with self.assertRaises(self.srv.ApiError):
            self.app.answer_match("fox", {"product_id": "p1", "answer": "probably"})
        with self.assertRaises(self.srv.ApiError):
            self.app.answer_match("fox", {"product_id": "p1"})
        self.app.answer_match("fox", {"product_id": "p1", "answer": "different"})
        self.assertEqual(self.app.catalog.answers("fox"), {"p1": "different"})
        self.assertTrue(any("different piece" in e["label"] for e in self.app.storefront_preview("fox")["history"]))

    def test_a_likely_match_blocks_approval_until_answered(self):
        title = self.app.store.effective("fox", self.app.store.draft("fox"))["title"]
        self.snap = snapshot([dict(LION, name=title, slug=am.slugify(title))])
        self.wait(self.app.refresh_catalog())
        doc = self.app.storefront_preview("fox")
        self.assertEqual(doc["catalog"]["candidates"][0]["level"], "likely")
        self.assertTrue(any(b["target"] == "catalog.match" for b in doc["blockers"]))
        doc = self.app.answer_match("fox", {"product_id": "p1", "answer": "different"})
        self.assertFalse(any(b["target"] == "catalog.match" for b in doc["blockers"]))

    def test_looking_for_photos_brings_in_and_processes_only_new_ones(self):
        self.app.inbox.mkdir(parents=True, exist_ok=True)
        photo(self.app.inbox / "New.jpg", size=(300, 400))
        (self.app.inbox / "bad.jpg").write_bytes(b"nope")
        self.assertEqual(self.app.photos()["intake"]["waiting"], 2)
        job = self.wait(self.app.scan_inbox())
        self.assertIsNone(job["error"])
        self.assertEqual(job["results"], [{"added": 1, "duplicates": 0, "problems": 1}])
        self.assertIn("New.jpg", [i["source"] for i in self.app.items()])
        doc = self.app.photos()
        self.assertEqual(doc["intake"]["waiting"], 1)
        self.assertEqual(doc["intake"]["last"]["problems"][0]["name"], "bad.jpg")

    def test_the_routes_exist(self):
        src = read(REPO / "services" / "local_api" / "server.py")
        for path in ('"/api/intake/scan"', '"/api/catalog/refresh"'):
            self.assertIn(f'@route("POST", {path})', src)
        self.assertIn('@route("PUT", r"/api/items/([\\w.-]+)/catalog-match")', src)


class Wiring(unittest.TestCase):
    def test_the_inbox_is_never_committed(self):
        text = read(REPO / ".gitignore")
        self.assertIn("inbox/*\n", text)
        self.assertTrue((REPO / "inbox" / ".gitkeep").exists())

    def test_catalog_values_reach_the_change_set_only_as_blockers_and_slugs(self):
        src = read(REPO / "services" / "local_api" / "server.py")
        self.assertIn("catalog_issues=catalog.issues(self._candidates(item_id, entry, rec))", src)
        self.assertIn("taken_slugs=catalog.taken_slugs(self.catalog.load())", src)

    def test_the_catalog_read_uses_the_read_only_session(self):
        src = read(REPO / "services" / "local_api" / "server.py")
        self.assertIn("crr.Psql(crr.pg_env_from_url(url))", src)

    def test_the_dashboard_offers_both(self):
        self.assertIn("scanInbox", read(REPO / "apps/review-dashboard/src/pages/Photos.tsx"))
        panel = read(REPO / "apps/review-dashboard/src/components/StorefrontPanel.tsx")
        self.assertIn("refreshCatalog", panel)
        self.assertIn("answerMatch", panel)


if __name__ == "__main__":
    unittest.main()
