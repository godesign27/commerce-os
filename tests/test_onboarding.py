"""First run and the start page (B-068): each step's rules, credential handling, any-store previews, HEIC.

No database and no network: a stand-in plays the store. Every name, login and key here is invented.
"""
import json
import stat
import subprocess
import time
import unittest

from PIL import Image

from packages import onboarding as ob
from packages.adapters import artstore_map as am
from packages.image_pipeline import intake
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, record_for, tmp

GOOD_URL = "postgresql://commerce_os_read:s3cret-Pass@db.invented.test/store?sslmode=require"
OWNER_URL = "postgresql://postgres:0wner-Pass@db.invented.test/store?sslmode=require"
PROFILE = json.loads((REPO / "resources/catalog-profiles/replit-artstore-v1.json").read_text())
TABLES = json.loads((REPO / "database/storefronts/storefront-a/catalog-structure.json").read_text())["tables"]
CATS = [{"id": "c1", "name": "Originals", "slug": "originals"}, {"id": "c2", "name": "Prints", "slug": "prints"},
        {"id": "c3", "name": "Journal", "slug": "journal"}]
TAGS = [{"id": "t1", "name": "Bold", "slug": "bold"}, {"id": "t2", "name": "Calm", "slug": "calm"}]
SNAP = {"storefront": "storefront-c", "read_at": "t", "products": [], "categories": CATS, "tags": TAGS,
        "tier_types": ["Original", "Print"]}
CHOICES = {"categories": ["originals", "prints"], "tags": ["bold"], "tier_types": ["Original", "Print"],
           "product_types": {"artwork": {"category": "originals", "alternative": "prints"}}}
STORE = {"display_name": "Invented Gallery", "site_kind": "artist", "provider": "supabase", "currency": "usd"}


class StorePg:
    """Plays a store for one login."""

    def __init__(self, write=False, customers=False, tables=TABLES, fail=None, products=()):
        self.write, self.customers, self.tables, self.fail, self.products = write, customers, tables, fail, list(products)

    def rows(self, sql):
        if self.fail:
            raise SystemExit(self.fail)
        if "rolsuper" in sql:
            return [{"user": "commerce_os_read", "db": "store", "rolsuper": False, "rolcreaterole": False, "rolcreatedb": False,
                     "rolbypassrls": False, "rolreplication": False}]
        if "pg_auth_members" in sql:
            return []
        if "has_table_privilege" in sql:
            rows = [{"t": t, "SELECT": True, "INSERT": self.write, "UPDATE": False, "DELETE": False, "TRUNCATE": False}
                    for t in ("products", "categories", "tags")]
            return rows + ([{"t": "orders", "SELECT": True, "INSERT": False, "UPDATE": False, "DELETE": False, "TRUNCATE": False}]
                           if self.customers else [])
        if "relrowsecurity" in sql:
            return [{"t": t, "rls": False, "policies": []} for t in ("products", "categories", "tags")]
        if "pg_attribute" in sql:
            return [dict(c, t=t, col=col) for t, spec in self.tables.items() for col, c in spec["columns"].items()]
        if "pg_constraint" in sql:
            return []
        if "jsonb_array_elements" in sql:
            return [{"type": "Original"}, {"type": "Print"}]
        if "public.products" in sql:
            return [dict(p) for p in self.products]
        if "public.categories" in sql:
            return [dict(c) for c in CATS]
        if "public.tags" in sql:
            return [dict(t) for t in TAGS]
        raise AssertionError(f"unexpected query: {sql}")


class EnvFile(unittest.TestCase):
    def setUp(self):
        self.path = tmp() / ".env"

    def test_setting_one_value_leaves_the_rest(self):
        self.path.write_text("# a note\nOTHER=1\nKEY=old\n")
        ob.set_env(self.path, "KEY", "new")
        self.assertEqual(self.path.read_text(), "# a note\nOTHER=1\nKEY=new\n")
        ob.set_env(self.path, "ADDED", "x")
        self.assertEqual(ob.read_env(self.path), {"OTHER": "1", "KEY": "new", "ADDED": "x"})

    def test_only_this_user_can_read_it(self):
        self.path.write_text("OTHER=1\n")
        self.path.chmod(0o644)
        ob.set_env(self.path, "KEY", "v")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_a_value_cannot_add_another_line(self):
        with self.assertRaises(ob.SetupError):
            ob.set_env(self.path, "KEY", "a\nEVIL=1")
        with self.assertRaises(ob.SetupError):
            ob.set_env(self.path, "not a key", "v")

    def test_scrub_hides_the_login_and_its_password(self):
        msg = ob.scrub(f"failed for {GOOD_URL} using s3cret-Pass", GOOD_URL, ob.url_password(GOOD_URL))
        self.assertNotIn("s3cret-Pass", msg)
        self.assertNotIn("invented.test", msg)


class YourStore(unittest.TestCase):
    def setUp(self):
        self.path = tmp() / "config" / "stores.json"

    def test_writes_stay_off_whatever_is_sent(self):
        entry = ob.save_store(self.path, "storefront-c", dict(STORE, writes_enabled=True, asset_upload="authorized"))
        self.assertIs(entry["writes_enabled"], False)
        self.assertEqual(entry["asset_upload"], "not_authorized")
        self.assertEqual(entry["env_prefix"], "STOREFRONT_C")
        self.assertEqual(entry["currency"], "USD")

    def test_it_needs_real_answers(self):
        for bad in ({"display_name": ""}, {"site_kind": "other"}, {"provider": "made-up"}, {"currency": "dollars"},
                    {"catalog_profile": "made-up"}):
            with self.assertRaises(ob.SetupError, msg=bad):
                ob.save_store(self.path, "storefront-c", dict(STORE, **bad))

    def test_other_stores_are_left_alone(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"version": 1, "note": "keep", "storefronts": [{"id": "other", "env_prefix": "OTHER"}]}))
        ob.save_store(self.path, "storefront-c", STORE)
        cfg = json.loads(self.path.read_text())
        self.assertEqual(cfg["note"], "keep")
        self.assertEqual(cfg["storefronts"][0], {"id": "other", "env_prefix": "OTHER"})

    def test_two_stores_never_share_a_prefix(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"storefronts": [{"id": "other", "env_prefix": "STOREFRONT_C"}]}))
        with self.assertRaises(ob.SetupError):
            ob.save_store(self.path, "storefront-c", STORE)


class LoginScript(unittest.TestCase):
    def test_it_grants_reading_three_tables_and_nothing_else(self):
        sql = ob.login_sql()
        self.assertIn("GRANT SELECT ON public.products, public.categories, public.tags TO", sql)
        self.assertIn("default_transaction_read_only = on", sql)
        for forbidden in ("BYPASSRLS", "SUPERUSER", "INSERT", "UPDATE", "DELETE", "GRANT ALL"):
            self.assertNotIn(forbidden, sql)
        self.assertEqual(sql.count("<password>"), 1)

    def test_it_works_where_row_level_security_is_on(self):
        """Found running it for real: without policies, the login was refused with no way forward."""
        sql = ob.login_sql()
        self.assertEqual(sql.count("CREATE POLICY"), 3)
        self.assertEqual(sql.count("FOR SELECT TO"), 3)

    def test_it_matches_the_runbook(self):
        runbook = read(REPO / "docs/runbooks/read-only-role.md")
        self.assertIn("GRANT SELECT ON public.products, public.categories, public.tags TO commerce_os_read;", runbook)
        self.assertIn(f"{ob.READ_ROLE} SET default_transaction_read_only = on;", runbook)


class CheckTheStore(unittest.TestCase):
    def test_the_known_structure_fits(self):
        self.assertEqual(ob.fit(TABLES, PROFILE), [])

    def test_missing_columns_and_tables_are_named(self):
        short = json.loads(json.dumps(TABLES))
        del short["products"]["columns"]["price"]
        self.assertIn("price", ob.fit(short, PROFILE)[0])
        short["tags"]["columns"] = {}
        self.assertTrue(any("no tags table" in x for x in ob.fit(short, PROFILE)))

    def test_features_come_from_real_columns(self):
        found = ob.detect_features(TABLES, PROFILE)
        self.assertIn("is_sold", found)
        self.assertNotIn("color_variants", found)


class Mapping(unittest.TestCase):
    def build(self, choices=None, old=None):
        return ob.build_mapping("storefront-c", SNAP, choices or CHOICES, old, "2026-11-04")

    def test_ids_come_only_from_the_store(self):
        m = self.build()
        self.assertEqual(next(c for c in m["categories"] if c["key"] == "originals")["id"], {"production": "c1"})

    def test_what_is_not_chosen_is_excluded_not_lost(self):
        m = self.build()
        self.assertEqual({c["key"]: c["status"] for c in m["categories"]},
                         {"originals": "in_scope", "prints": "in_scope", "journal": "excluded"})
        self.assertEqual({t["key"]: t["status"] for t in m["tags"]}, {"bold": "in_scope", "calm": "excluded"})

    def test_it_is_refused_when_incomplete_or_invented(self):
        for bad in ({"categories": []}, {"categories": ["made-up"]}, {"tags": ["made-up"]}, {"tier_types": []},
                    {"tier_types": ["Made Up"]}, {"product_types": {}},
                    {"product_types": {"artwork": {"category": "journal"}}},
                    {"product_types": {"artwork": {"category": "originals", "alternative": "journal"}}}):
            with self.assertRaises(ob.SetupError, msg=bad):
                self.build(dict(CHOICES, **bad))
        with self.assertRaises(ob.SetupError):
            self.build({"categories": ["originals"]})

    def test_saving_again_is_a_new_version_and_keeps_existing_keys(self):
        old = self.build()
        old["categories"][0]["key"] = "my-key"
        old["product_types"]["hat"] = {"category": "prints", "type_tags": []}
        again = self.build(old=old)
        self.assertEqual(again["version"], 2)
        self.assertEqual(len(again["changes"]), 2)
        self.assertEqual(again["categories"][0]["key"], "my-key")
        self.assertEqual(again["product_types"]["artwork"]["category"], "my-key")
        self.assertIn("hat", again["product_types"])

    def test_it_is_ready_only_when_it_can_place_a_piece(self):
        self.assertTrue(ob.mapping_ready(self.build()))
        self.assertFalse(ob.mapping_ready(None))
        self.assertFalse(ob.mapping_ready({"categories": [{"status": "in_scope"}], "tier_types": []}))

    def test_a_piece_finds_its_category_from_it(self):
        m = self.build()
        store = am.test_store("storefront-a", m)
        self.assertEqual(am._category("artwork", "Original", m, store), "test-category-originals")
        self.assertEqual(am._category("artwork", "Print", m, store), "test-category-prints")


class Steps(unittest.TestCase):
    ENTRY = {"provider": "supabase", "site_kind": "artist", "display_name": "x"}
    READY = {"categories": [{"status": "in_scope"}], "tier_types": ["x"], "product_types": {"artwork": {"category": "x"}}}

    def steps(self, **kw):
        args = dict(entry=self.ENTRY, login=True, snapshot=True, mapping=self.READY, key=True, brand=True, photos=1)
        return ob.steps(**dict(args, **kw))

    def test_a_finished_install_shows_everything_done(self):
        d = self.steps()
        self.assertTrue(d["complete"])
        self.assertIsNone(d["next"])

    def test_nothing_set_up_starts_at_the_store(self):
        d = self.steps(entry=None, login=False, snapshot=False, mapping=None, key=False, brand=False, photos=0)
        self.assertEqual((d["complete"], d["next"]), (False, "store"))

    def test_each_missing_piece_is_the_next_step(self):
        for kw, step in (({"login": False}, "login"), ({"snapshot": False}, "check"), ({"mapping": None}, "mapping"),
                         ({"key": False}, "key"), ({"brand": False}, "voice")):
            d = self.steps(**kw)
            self.assertEqual((d["complete"], d["next"]), (False, step))

    def test_a_login_without_a_store_entry_does_not_count(self):
        self.assertFalse(self.steps(entry=None)["steps"][1]["done"])

    def test_no_photos_yet_does_not_hold_up_setup(self):
        d = self.steps(photos=0)
        self.assertTrue(d["complete"])
        self.assertEqual(d["next"], "photos")


class Api(unittest.TestCase):
    def setUp(self):
        self.srv = load_server()
        self.dir = tmp()
        self.out = self.dir / "review"
        self.out.mkdir()
        self.pg = StorePg()
        self.keys = []
        self.app = self.make("storefront-c")

    def make(self, storefront):
        return self.srv.App(out=self.out, source=self.dir / "source", storefront=storefront, config=self.dir / "stores.json",
                            mapping=self.dir / "map.json", brand_root=self.dir / "brand", learning_root=self.dir / "learning",
                            rooms_root=self.dir / "rooms", connect=lambda url: self.pg, check_key=self.check_key)

    def check_key(self, key):
        self.keys.append(key)
        if key != "good-key":
            raise type("AuthenticationError", (Exception,), {})("refused " + key)

    def connected(self):
        self.app.onboarding_store(STORE)
        self.app.onboarding_login({"url": GOOD_URL})
        self.app.onboarding_check()

    def everything_seen(self):
        return json.dumps([self.app.onboarding_doc(), self.app.home(), self.app.state()], default=str)

    def test_it_never_writes_to_the_real_env_in_tests(self):
        self.assertEqual(self.app.env_file, self.dir / ".env")

    def test_a_good_login_is_saved_and_never_shown(self):
        self.app.onboarding_store(STORE)
        doc = self.app.onboarding_login({"url": GOOD_URL})
        self.assertEqual(ob.read_env(self.app.env_file)["STOREFRONT_C_DB_URL"], GOOD_URL)
        self.assertTrue(doc["login"]["saved"])
        for secret in (GOOD_URL, "s3cret-Pass"):
            self.assertNotIn(secret, json.dumps(doc))
            self.assertNotIn(secret, self.everything_seen())

    def test_a_login_that_can_write_or_see_customers_is_not_saved(self):
        self.app.onboarding_store(STORE)
        for pg, why in ((StorePg(write=True), "write privileges"), (StorePg(customers=True), "non-catalog")):
            self.pg = pg
            with self.assertRaises(self.srv.ApiError) as e:
                self.app.onboarding_login({"url": OWNER_URL})
            self.assertIn(why, str(e.exception))
            self.assertNotIn("0wner-Pass", str(e.exception))
            self.assertFalse(self.app.env_file.exists())

    def test_a_failed_connection_says_why_without_the_login(self):
        self.app.onboarding_store(STORE)
        self.pg = StorePg(fail=f"could not connect: {GOOD_URL}")
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.onboarding_login({"url": GOOD_URL})
        self.assertIn("Couldn't connect", str(e.exception))
        self.assertNotIn("s3cret-Pass", str(e.exception))
        self.assertFalse(self.app.env_file.exists())

    def test_another_stores_login_is_refused(self):
        self.app.onboarding_store(STORE)
        ob.set_env(self.app.env_file, "OPS_DB_URL", GOOD_URL)
        with self.assertRaisesRegex(self.srv.ApiError, "belongs to something else"):
            self.app.onboarding_login({"url": GOOD_URL})

    def test_checking_reads_the_store_and_records_what_it_has(self):
        self.connected()
        doc = self.app.onboarding_doc()
        self.assertEqual(doc["check"]["categories"], 3)
        self.assertEqual(doc["choices"]["tier_types"], ["Original", "Print"])
        self.assertTrue(self.app.catalog.structure())
        entry = self.app.storefront_entry()
        self.assertIn("is_sold", entry["features"])

    def test_a_store_that_does_not_fit_stops_there(self):
        self.app.onboarding_store(STORE)
        self.app.onboarding_login({"url": GOOD_URL})
        short = json.loads(json.dumps(TABLES))
        del short["products"]["columns"]["price"]
        self.pg = StorePg(tables=short)
        with self.assertRaisesRegex(self.srv.ApiError, "new catalog profile"):
            self.app.onboarding_check()
        self.assertIsNone(self.app.catalog.load())

    def test_a_new_store_gets_a_working_preview(self):
        """A store with nothing committed for it: this used to crash."""
        (self.out / "items.json").write_text(json.dumps([{"id": "fox", "source": "Fox.jpg", "kind": "photo", "art_file": "x"}]))
        self.app.store.save_draft("fox", record_for("fox"))
        self.assertFalse(self.app.storefront_preview("fox")["available"])
        self.assertIsNone(self.app.state()["items"][0]["storefront"])
        self.connected()
        self.app.onboarding_mapping(CHOICES)
        doc = self.app.storefront_preview("fox")
        self.assertTrue(doc["available"])
        self.assertEqual(doc["storefront"], "storefront-c")
        self.assertFalse([b for b in doc["blockers"] if b["target"] == "product.category"], "a phone photo finds its category")
        self.assertIn(self.app.state()["items"][0]["storefront"], ("blocked", "ready"))

    def test_saving_the_mapping_takes_effect_at_once(self):
        self.connected()
        self.assertEqual(self.app.tier_types(), [])
        self.app.onboarding_mapping(CHOICES)
        self.assertEqual(self.app.tier_types(), ["Original", "Print"])
        self.assertEqual(self.app.onboarding_doc()["choices"]["chosen"]["categories"], ["originals", "prints"])

    def test_a_refused_key_is_not_saved_and_not_repeated(self):
        with self.assertRaises(self.srv.ApiError) as e:
            self.app.onboarding_key({"key": "bad-key"})
        self.assertIn("refused", str(e.exception))
        self.assertNotIn("bad-key", str(e.exception))
        self.assertFalse(self.app.env_file.exists())

    def test_a_good_key_is_saved_and_never_shown(self):
        self.app.onboarding_key({"key": "good-key"})
        self.assertEqual(self.app._key(), "good-key")
        self.assertNotIn("good-key", self.everything_seen())

    def test_the_start_page_with_nothing_connected(self):
        d = self.app.home()
        self.assertFalse(d["store"]["connected"])
        self.assertEqual(d["photos"]["total"], 0)
        self.assertEqual(d["onboarding"]["next"], "store")

    def test_the_start_page_once_connected(self):
        self.pg = StorePg(products=[{"id": "p1", "name": "Quiet Lion", "slug": "q", "sku": None, "status": "active",
                                     "category_id": "c1", "is_original": True, "medium": None, "dimensions": None}])
        self.connected()
        d = self.app.home()
        self.assertTrue(d["store"]["connected"])
        self.assertEqual(d["store"]["display_name"], "Invented Gallery")
        self.assertEqual(d["store"]["products"], 1)
        self.assertIs(d["store"]["writes_enabled"], False)

    def test_new_photos_are_announced_but_known_problems_are_not(self):
        self.app.inbox.mkdir(parents=True)
        Image.new("RGB", (300, 400), (9, 90, 9)).save(self.app.inbox / "New.jpg")
        (self.app.inbox / "bad.jpg").write_bytes(b"nope")
        self.assertEqual(self.app.inbox_status()["new"], 2)
        self.assertEqual(self.app.home()["inbox"]["new"], 2)
        res = self.app.scan_inbox()
        for _ in range(500):
            if not self.app.jobs[res["job"]]["running"]:
                break
            time.sleep(0.01)
        status = self.app.inbox_status()
        self.assertEqual((status["new"], status["waiting"]), (0, 1))
        Image.new("RGB", (300, 400), (90, 9, 9)).save(self.app.inbox / "Another.jpg")
        self.assertEqual(self.app.inbox_status()["new"], 1)


class PhoneAndHeic(unittest.TestCase):
    def test_a_phone_photo_of_a_painting_is_artwork(self):
        mapping = {"product_types": {"artwork": {"category": "x"}}}
        self.assertEqual(am._product_type({"kind": "photo"}, None, mapping), "artwork")
        self.assertEqual(am._product_type({"kind": "artwork"}, None, mapping), "artwork")

    def test_the_drafted_product_type_comes_first(self):
        mapping = {"product_types": {"artwork": {"category": "x"}, "hat": {"category": "y"}}}
        record = {"draft": {"product": {"attributes": {"category": {"value": "hat"}}}}}
        self.assertEqual(am._product_type({"kind": "artwork"}, record, mapping), "hat")

    def test_a_heic_photo_comes_in_and_gets_framed(self):
        srv = load_server()
        d = tmp()
        inbox, source = d / "inbox", d / "source"
        inbox.mkdir()
        Image.new("RGB", (600, 750), (150, 60, 30)).save(inbox / "IMG_0001.heic")
        res = intake.scan(inbox, source, d / "intake")
        self.assertEqual([a["source_name"] for a in res["added"]], ["IMG_0001.heic"])
        self.assertEqual(json.loads((d / "intake" / "journal.jsonl").read_text().splitlines()[0])["format"], "HEIF")
        items = srv.ri.build(source, d / "review", log=lambda *_: None)
        self.assertEqual(items[0]["source"], "IMG_0001.heic")
        self.assertNotEqual(items[0]["status"], "error", items[0].get("error"))


class StartCommand(unittest.TestCase):
    def test_it_is_valid_and_runnable(self):
        path = REPO / "start.sh"
        self.assertTrue(path.stat().st_mode & stat.S_IXUSR)
        self.assertEqual(subprocess.run(["bash", "-n", str(path)]).returncode, 0)

    def test_it_says_how_to_fix_what_is_missing(self):
        src = read(REPO / "start.sh")
        for fix in ("brew install python", "brew install node", "brew install libpq"):
            self.assertIn(fix, src)

    def test_it_binds_nothing_beyond_the_local_server(self):
        self.assertIn("services/local_api/server.py", read(REPO / "start.sh"))
        self.assertIn('HOST = "127.0.0.1"', read(REPO / "services/local_api/server.py"))

    def test_heic_support_is_installed(self):
        self.assertIn("pillow-heif", read(REPO / "requirements.txt"))
        self.assertIn("register_heif_opener()", read(REPO / "packages/image_pipeline/__init__.py"))


class Wiring(unittest.TestCase):
    def test_the_routes_exist(self):
        src = read(REPO / "services/local_api/server.py")
        for route in ('("GET", "/api/home")', '("GET", "/api/inbox")', '("GET", "/api/onboarding")', '("PUT", "/api/onboarding/store")',
                      '("POST", "/api/onboarding/login")', '("POST", "/api/onboarding/check")', '("PUT", "/api/onboarding/mapping")',
                      '("POST", "/api/onboarding/key")'):
            self.assertIn(route, src)

    def test_the_start_page_is_the_front_door(self):
        src = read(REPO / "apps/review-dashboard/src/main.tsx")
        self.assertIn('location.hash.slice(1) || "/home"', src)
        self.assertIn("<GettingStarted", src)
        self.assertIn("<NewPhotos", src)

    def test_the_alert_and_the_null_state_exist(self):
        self.assertIn("in your inbox", read(REPO / "apps/review-dashboard/src/components/NewPhotos.tsx"))
        self.assertIn("No store connected yet", read(REPO / "apps/review-dashboard/src/pages/Home.tsx"))

    def test_credential_fields_are_masked(self):
        src = read(REPO / "apps/review-dashboard/src/pages/GettingStarted.tsx")
        self.assertEqual(src.count('type="password"'), 2)

    def test_the_agent_skill_still_never_handles_a_credential(self):
        skill = read(REPO / "plugins/commerce-os/skills/storefront-setup/SKILL.md")
        self.assertIn("Asking for, accepting, writing, or echoing a password", skill)
        self.assertIn("./start.sh", skill)


class InstallGuide(unittest.TestCase):
    CLONE = "https://github.com/godesign27/commerce-os.git"
    HELP = "apps/review-dashboard/src/components/SetupHelp.tsx"

    def test_the_guide_gives_every_fix_the_start_command_gives(self):
        guide = read(REPO / "INSTALL.md")
        for fix in ("brew install python", "brew install node", "brew install libpq", "brew install postgresql@16"):
            self.assertIn(fix, read(REPO / "start.sh"))
            self.assertIn(fix, guide)

    def test_the_guide_only_uses_what_the_start_command_accepts(self):
        guide, start = read(REPO / "INSTALL.md"), read(REPO / "start.sh")
        for flag in ("--check", "COMMERCE_OS_PORT"):
            self.assertIn(flag, guide)
            self.assertIn(flag, start)
        self.assertIn("8770", guide)
        self.assertIn('COMMERCE_OS_PORT:-8770', start)

    def test_the_guide_warns_that_work_stays_on_this_computer(self):
        guide = read(REPO / "INSTALL.md")
        self.assertIn("Back up the folder", guide)
        for local in (".env", ".commerce-os/", "config/storefronts.local.json"):
            self.assertIn(local, read(REPO / ".gitignore"))

    def test_the_panel_and_the_guide_give_the_same_commands(self):
        guide, panel = read(REPO / "INSTALL.md"), read(REPO / self.HELP)
        for command in (f"cd ~ && git clone {self.CLONE} && cd commerce-os", "./start.sh --check", "./start.sh", "git pull"):
            self.assertIn(command, guide)
            self.assertIn(command, panel)
        self.assertIn("blob/main/INSTALL.md", panel)
        self.assertIn("INSTALL.md", read(REPO / "README.md"))

    def test_every_step_has_help(self):
        panel = read(REPO / self.HELP)
        for step, _ in ob.STEPS:
            self.assertIn(f'id === "{step}"', panel, step)

    def test_the_supabase_help_matches_the_login_step(self):
        panel = read(REPO / self.HELP)
        self.assertIn('provider === "supabase"', panel)
        self.assertIn("Session pooler", panel)
        self.assertIn("Session pooler", ob.login_where("supabase"))
        self.assertIn(f"{ob.READ_ROLE}.", panel)
        self.assertIn(f"{ob.READ_ROLE}.<project-ref>", ob.login_example("supabase"))

    def test_the_photo_help_matches_the_inbox_limits(self):
        panel = read(REPO / self.HELP)
        self.assertIn(f"up to {intake.MAX_BYTES // 1_000_000} MB", panel)
        self.assertIn("JPEG, HEIC, PNG, WebP or TIFF", panel)

    def test_the_help_never_takes_a_credential(self):
        self.assertNotIn("<input", read(REPO / self.HELP))

    def test_the_page_shows_the_help_beside_and_inside_the_steps(self):
        page, css = read(REPO / "apps/review-dashboard/src/pages/GettingStarted.tsx"), read(REPO / "apps/review-dashboard/src/styles.css")
        self.assertEqual(page.count("<StepHelp"), 2)
        self.assertIn("<InstallHelp", page)
        self.assertIn("gs-help-inline", css)
        narrow = css[css.index("@media (max-width: 1000px)"):]
        self.assertIn(".gs-help-side { display: none; }", narrow[:narrow.index("\n}\n")])


if __name__ == "__main__":
    unittest.main()
