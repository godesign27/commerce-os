"""Publishing to a live store (B-073), and the Support page (B-076). Every login here is invented, nothing here reads
.env, and nothing can reach a real store: uploads go to a stand-in, and the database tests use a private local
Postgres, set up with the very SQL the runbook gives the owner.
"""
import io
import json
import re
import shutil
import unittest
from contextlib import redirect_stdout
from unittest import mock

from packages.adapters import artstore_map
from packages.publisher.assets import DeliveryError, SupabaseAssetStore
from tests._helpers import REPO, read
from tests.test_listing_copy import load_server, record_for, tmp
from tests.test_storefront_preview import FACTS, ITEM, MAPPING

try:
    import psycopg
    from packages.adapters.artstore_pg import NotLocal, PgRows, PostgresArtStore, require_live
    from packages.adapters.contract import Refused
    from packages.publisher import live_store
    from packages.publisher.local_store import READ_ROLE, WRITE_ROLE, LocalStore
    from packages.publisher.worker import Worker
    HAVE_PG = LocalStore("storefront-a", tmp() / "x").ldb.available()
except ImportError:
    psycopg, live_store, HAVE_PG = None, None, False

needs_psycopg = unittest.skipUnless(psycopg, "psycopg not installed")
needs_pg = unittest.skipUnless(HAVE_PG, "Postgres or psycopg not installed")
HOST = "pooler.example.test"
REF = "abcdefgh"


def found(**changes):
    out = {"read": f"postgresql://{READ_ROLE}.{REF}:invented-read-pw@{HOST}:5432/postgres?sslmode=require",
           "write": f"postgresql://{WRITE_ROLE}.{REF}:invented-write-pw@{HOST}:5432/postgres?sslmode=require",
           "url": f"https://{REF}.supabase.co", "key": "sb_publishable_invented", "email": "uploads@example.test",
           "password": "invented-upload-pw", "bucket": "artwork"}
    return dict(out, **changes)


ENV = {f"STOREFRONT_A_{live_store.SUFFIXES[k]}": v for k, v in found().items()} if live_store else {}
ENTRY = {"id": "storefront-a", "env_prefix": "STOREFRONT_A", "catalog_profile": "replit-artstore-v1", "currency": "USD",
         "features": [], "provider": "supabase", "site_kind": "artist", "display_name": "Trial Shop"}


@needs_psycopg
class Settings(unittest.TestCase):
    def test_missing_settings_are_named_and_values_never_shown(self):
        env = dict(ENV)
        del env["STOREFRONT_A_WRITE_DB_URL"]
        with self.assertRaises(live_store.LiveNotReady) as e:
            live_store.settings(ENTRY, env)
        self.assertIn("STOREFRONT_A_WRITE_DB_URL", str(e.exception))
        self.assertNotIn("invented", str(e.exception))

    def test_the_runbook_logins_pass(self):
        self.assertEqual(live_store.check_settings(live_store.settings(ENTRY, ENV)), [])

    def test_anything_else_is_refused(self):
        bad = {"another login": {"write": f"postgresql://postgres.{REF}:pw@{HOST}:5432/postgres?sslmode=require"},
               "another database": {"write": f"postgresql://{WRITE_ROLE}.{REF}:pw@other.example.test:5432/postgres"},
               "another project": {"write": f"postgresql://{WRITE_ROLE}.zzzzzzzz:pw@{HOST}:5432/postgres"},
               "another read login": {"read": f"postgresql://someone.{REF}:pw@{HOST}:5432/postgres"},
               "the secret key": {"key": "sb_secret_invented"},
               "not a Supabase address": {"url": "http://localhost:9000"}}
        for why, change in bad.items():
            problems = live_store.check_settings(found(**change))
            self.assertTrue(problems, why)
            self.assertNotIn("pw", " ".join(x for x in problems if "password" not in x), why)


@needs_psycopg
class Target(unittest.TestCase):
    GOOD = f"host={HOST} port=5432 dbname=postgres user=u sslmode=require"

    def test_only_the_named_host_with_encryption(self):
        self.assertTrue(require_live(self.GOOD, HOST))
        for dsn in ("host=other.example.test sslmode=require user=u", f"host={HOST} user=u", f"host={HOST} sslmode=disable user=u",
                    f"host={HOST} hostaddr=10.0.0.1 sslmode=require user=u", "host=/tmp user=u sslmode=require"):
            with self.assertRaises(NotLocal, msg=dsn):
                require_live(dsn, HOST)

    def test_no_named_host_is_no_live_store(self):
        with self.assertRaises(NotLocal):
            require_live(self.GOOD, "")
        with self.assertRaises(NotLocal):
            PostgresArtStore("s", "production", {}, {"tables": {}}, write_dsn=self.GOOD, read_dsn=self.GOOD, currency="USD", features=[])

    def test_the_adapter_only_adds_drafts(self):
        store = PostgresArtStore("s", "production", {}, {"tables": {}}, write_dsn=self.GOOD, read_dsn=self.GOOD, currency="USD",
                                 features=[], live_host=HOST)
        change = {"change_set_id": "c", "change_set_hash": "a" * 64, "requested_status": "active", "operations": [],
                  "environment": "production", "destination": "s"}
        with self.assertRaises(Refused) as e:
            store.publish_approved(change, {"approval_id": "a"})
        self.assertIn("not_a_draft", [i.code for i in e.exception.issues])
        change = dict(change, requested_status="draft", operations=[{"fields": {"status": {"value": "active"}}}])
        with self.assertRaises(Refused) as e:
            store.publish_approved(change, {"approval_id": "a"})
        self.assertIn("not_a_draft", [i.code for i in e.exception.issues])


class Bucket:
    """A stand-in for Supabase's sign-in and storage."""

    def __init__(self, sign_in=(200, b'{"access_token": "invented-token"}')):
        self.sign_in, self.calls, self.objects, self.answer = sign_in, [], {}, None

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        if "/auth/v1/token" in url:
            return self.sign_in
        if self.answer:
            return self.answer
        name = url.split("/storage/v1/object/artwork/")[1]
        if name in self.objects:
            return 400, b'{"statusCode":"409","error":"Duplicate"}'
        self.objects[name] = body
        return 200, b"{}"


class Upload(unittest.TestCase):
    def setUp(self):
        self.bucket = Bucket()
        self.store = SupabaseAssetStore("https://abc.supabase.co/", "pk", "u@example.test", "invented-pw", "artwork", send=self.bucket)
        self.file = tmp() / "fox.framed.jpg"
        self.file.write_bytes(b"approved bytes")
        import hashlib
        self.sha = hashlib.sha256(b"approved bytes").hexdigest()
        self.assets = [{"derivative_id": "d1", "destination_key": f"/objects/uploads/fox-framed-{self.sha[:12]}"}]
        self.files = {"d1": {"file": str(self.file), "sha256": self.sha}}

    def test_the_image_and_its_record_both_go_up(self):
        out = self.store.deliver(self.assets, self.files)
        self.assertEqual(out[0]["result"], "written")
        name = f"uploads/fox-framed-{self.sha[:12]}"
        self.assertEqual(self.bucket.objects[name], b"approved bytes")
        record = json.loads(self.bucket.objects[f"_meta/{name}.json"])
        self.assertEqual(json.loads(record["custom:aclPolicy"])["visibility"], "public", "the store serves only images with this")

    def test_it_never_overwrites_and_uses_the_upload_login(self):
        self.store.deliver(self.assets, self.files)
        uploads = [c for c in self.bucket.calls if "/storage/" in c[1]]
        for _, url, headers, _ in uploads:
            self.assertTrue(url.startswith("https://abc.supabase.co/storage/v1/object/artwork/"))
            self.assertNotIn("x-upsert", {k.lower() for k in headers})
            self.assertEqual(headers["Authorization"], "Bearer invented-token")

    def test_delivering_twice_changes_nothing(self):
        self.store.deliver(self.assets, self.files)
        self.assertEqual(self.store.deliver(self.assets, self.files)[0]["result"], "already_present")

    def test_a_changed_file_never_goes_up(self):
        self.file.write_bytes(b"something else")
        with self.assertRaises(DeliveryError):
            self.store.deliver(self.assets, self.files)
        self.assertEqual(self.bucket.objects, {})

    def test_a_refusal_stops_it_and_shows_no_login(self):
        for answer in ((403, b"denied"), (401, b"denied"), (500, b"broken")):
            self.bucket.answer = answer
            with self.assertRaises(DeliveryError) as e:
                self.store.deliver(self.assets, self.files)
            self.assertNotIn("invented", str(e.exception))

    def test_a_refused_sign_in_stops_before_any_upload(self):
        self.bucket.sign_in = (400, b'{"error": "invalid_grant"}')
        with self.assertRaises(DeliveryError) as e:
            self.store.deliver(self.assets, self.files)
        self.assertNotIn("invented", str(e.exception))
        self.assertFalse([c for c in self.bucket.calls if "/storage/" in c[1]])

    def test_only_the_uploads_folder(self):
        for key in ("/objects/other/x", "/objects/uploads/", "/objects/uploads/a/b", "/objects/uploads/..", "uploads/x"):
            with self.assertRaises(DeliveryError, msg=key):
                SupabaseAssetStore.object_name(key)


def snapshot():
    seed = artstore_map.test_seed(MAPPING)
    rows = lambda table: [dict(r, id=f"real-{r['slug']}") for r in seed[table]]  # noqa: E731
    return {"storefront": "storefront-a", "read_at": "2026-11-05T00:00:00Z", "products": [], "categories": rows("categories"),
            "tags": rows("tags"), "tier_types": MAPPING.get("tier_types", [])}


class LiveListing(unittest.TestCase):
    def test_a_live_listing_uses_the_stores_real_ids(self):
        seed = artstore_map.live_seed(MAPPING, snapshot())
        self.assertTrue(seed["categories"])
        self.assertTrue(all(r["id"].startswith("real-") for r in seed["categories"] + seed["tags"]))

    def test_what_the_owner_left_out_stays_out(self):
        mapping = json.loads(json.dumps(MAPPING))
        mapping["categories"][0]["status"] = "excluded"
        chosen = {c["slug"] for c in artstore_map.live_seed(mapping, snapshot())["categories"]}
        self.assertNotIn(mapping["categories"][0].get("slug") or mapping["categories"][0]["key"], chosen)

    def test_the_recorded_id_wins_over_the_web_address(self):
        rows = [{"id": "x", "slug": "a", "name": "A"}, {"id": "y", "slug": "b", "name": "B"}]
        self.assertEqual(artstore_map._in_catalog({"key": "a", "slug": "a", "id": {"production": "y"}}, rows)["id"], "y")
        self.assertEqual(artstore_map._in_catalog({"key": "a", "slug": "a"}, rows)["id"], "x")
        self.assertIsNone(artstore_map._in_catalog({"key": "zzz"}, rows))


class Rows:
    def __init__(self, role=None, member=(), privileges=None, secured=None, policies=None, upload=None):
        self.role = role or {"rolname": WRITE_ROLE, "rolsuper": False, "rolcreaterole": False, "rolcreatedb": False,
                             "rolbypassrls": False, "rolreplication": False}
        self.member, self.secured = list(member), secured if secured is not None else [{"rls": True, "owner": False}]
        self.privileges = privileges or [{"t": "products", "SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False},
                                         {"t": "categories", "SELECT": True}, {"t": "tags", "SELECT": True}, {"t": "orders", "SELECT": False}]
        self.policies = policies if policies is not None else [{"policyname": "p", "permissive": "PERMISSIVE", "with_check": "(status = 'draft'::text)"}]
        self.upload = upload

    def rows(self, query):
        if "FROM pg_roles WHERE" in query:
            return [dict(self.role)]
        if "pg_auth_members" in query:
            return self.member
        if "has_table_privilege" in query:
            return [dict(r) for r in self.privileges]
        if "relrowsecurity" in query:
            return self.secured
        if "schemaname = 'storage'" in query:
            return self.upload
        return self.policies


@needs_psycopg
class WriteLoginCheck(unittest.TestCase):
    def test_the_narrow_login_passes(self):
        self.assertEqual(live_store.check_write_login(Rows()), [])

    def test_anything_wider_fails(self):
        base = Rows().privileges
        cases = {"another role name": Rows(role=dict(Rows().role, rolname="postgres")),
                 "superuser": Rows(role=dict(Rows().role, rolsuper=True)),
                 "skips row rules": Rows(role=dict(Rows().role, rolbypassrls=True)),
                 "a member of a role": Rows(member=[{"name": "postgres"}]),
                 "can edit": Rows(privileges=[dict(base[0], UPDATE=True)] + base[1:]),
                 "can delete": Rows(privileges=[dict(base[0], DELETE=True)] + base[1:]),
                 "can read orders": Rows(privileges=base[:3] + [{"t": "orders", "SELECT": True}]),
                 "can write elsewhere": Rows(privileges=base + [{"t": "users", "INSERT": True}]),
                 "can't add": Rows(privileges=[dict(base[0], INSERT=False)] + base[1:]),
                 "no row rules": Rows(secured=[{"rls": False, "owner": False}]),
                 "owns the table": Rows(secured=[{"rls": True, "owner": True}]),
                 "no add rule": Rows(policies=[]),
                 "adds anything": Rows(policies=[{"policyname": "p", "permissive": "PERMISSIVE", "with_check": "true"}]),
                 "a draft check that isn't only that": Rows(policies=[{"policyname": "p", "permissive": "PERMISSIVE", "with_check": "((status = 'draft'::text) OR true)"}]),
                 "a second wide rule": Rows(policies=Rows().policies + [{"policyname": "q", "permissive": "PERMISSIVE", "with_check": "true"}])}
        for why, rows in cases.items():
            self.assertTrue(live_store.check_write_login(rows), why)

    def test_the_upload_rule(self):
        good = "((bucket_id = 'artwork'::text) AND (auth.uid() = 'u'::uuid) AND ((name ~~ 'uploads/%'::text) OR (name ~~ '_meta/uploads/%'::text)))"
        self.assertEqual(live_store.check_upload_policy(Rows(upload=[{"policyname": "commerce_os_upload", "cmd": "INSERT", "with_check": good}]), "artwork"), [])
        for upload, bucket in (([], "artwork"), ([{"policyname": "commerce_os_upload", "cmd": "ALL", "with_check": good}], "artwork"),
                               ([{"policyname": "commerce_os_upload", "cmd": "INSERT", "with_check": "true"}], "artwork"),
                               ([{"policyname": "commerce_os_upload", "cmd": "INSERT", "with_check": good}], "other")):
            self.assertTrue(live_store.check_upload_policy(Rows(upload=upload), bucket), upload)


@needs_psycopg
class Connect(unittest.TestCase):
    class App:
        storefront = "storefront-a"

        def __init__(self, entry):
            self.entry = entry

        def storefront_entry(self):
            return self.entry

    def env(self):
        path = tmp() / ".env"
        path.write_text("".join(f"{k}={v}\n" for k, v in ENV.items()))
        return path

    def test_it_stops_unless_the_owner_turned_it_on(self):
        with self.assertRaises(live_store.LiveNotReady):
            live_store.connect(self.App(dict(ENTRY)), self.env())

    def test_it_stops_when_a_check_fails_and_shows_no_login(self):
        with mock.patch.object(live_store, "preflight", return_value=["The write login can edit."]):
            with self.assertRaises(live_store.LiveNotReady) as e:
                live_store.connect(self.App(dict(ENTRY, publish_target="live")), self.env())
        self.assertIn("The write login can edit.", str(e.exception))
        self.assertNotIn("invented", str(e.exception))


def go_live():
    import importlib.util
    spec = importlib.util.spec_from_file_location("go_live", REPO / "scripts" / "go_live.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@needs_psycopg
class GoLive(unittest.TestCase):
    def setUp(self):
        self.mod = go_live()
        self.dir = tmp()
        self.config = self.dir / "storefronts.local.json"
        self.config.write_text(json.dumps({"storefronts": [dict(ENTRY, writes_enabled=False, asset_upload="not_authorized"), {"id": "storefront-b", "writes_enabled": False}]}))
        self.env = self.dir / ".env"

    def entry(self, i=0):
        return json.loads(self.config.read_text())["storefronts"][i]

    def run_it(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.mod.main(["storefront-a", *args], config=self.config, env_file=self.env)
        return code, out.getvalue()

    def test_a_check_with_missing_settings_changes_nothing_and_shows_nothing(self):
        self.env.write_text("STOREFRONT_A_DB_URL=postgresql://u:invented-secret@h/d\n")
        for args in ((), ("--on",)):
            code, out = self.run_it(*args)
            self.assertEqual(code, 1)
            self.assertNotIn("invented-secret", out)
            self.assertNotIn("publish_target", self.entry())

    def test_it_turns_on_only_after_the_checks_pass(self):
        self.env.write_text("")
        self.mod.check = lambda entry, env: []
        code, _ = self.run_it()
        self.assertEqual(code, 0)
        self.assertNotIn("publish_target", self.entry(), "a check alone changes nothing")
        self.run_it("--on")
        self.assertEqual(self.entry()["publish_target"], "live")
        self.assertTrue(self.entry()["writes_enabled"])
        self.assertNotIn("publish_target", self.entry(1), "another store is untouched")

    def test_it_turns_off_without_any_login(self):
        self.mod.check = lambda entry, env: []
        self.env.write_text("")
        self.run_it("--on")
        self.mod.check = lambda entry, env: ["broken"]
        self.assertEqual(self.run_it("--off")[0], 0)
        self.assertEqual(self.entry()["publish_target"], "local")
        self.assertFalse(self.entry()["writes_enabled"])


class Dashboard(unittest.TestCase):
    def app(self, entry):
        d = tmp()
        out = d / "review"
        (out / "img").mkdir(parents=True)
        (out / "items.json").write_text("[]")
        (d / "config.json").write_text(json.dumps({"storefronts": [entry]}))
        (d / "mapping.json").write_text(json.dumps(MAPPING))
        return load_server().App(out=out, brand_root=d / "brand", learning_root=d / "learning", config=d / "config.json", source=tmp(),
                                 rooms_root=d / "rooms", mapping=d / "mapping.json")

    def test_it_starts_on_the_test_store(self):
        app = self.app(dict(ENTRY))
        self.assertEqual(app._target(), "Local test store")
        self.assertEqual(app.state()["publish_target"], "local")
        self.assertEqual(app.pubs.root.name, "publications")

    def test_live_is_said_plainly_and_kept_apart(self):
        app = self.app(dict(ENTRY, publish_target="live"))
        self.assertEqual(app._target(), "Live store")
        self.assertEqual(app.state()["publish_target"], "live")
        self.assertEqual(app.pubs.root.name, "publications-live", "a test publish isn't a live one")

    def test_a_live_preview_uses_real_ids_and_can_not_write(self):
        app = self.app(dict(ENTRY, publish_target="live"))
        structure = json.loads((REPO / "database/storefronts/storefront-a/catalog-structure.json").read_text())
        app.catalog.save(snapshot())
        app.catalog.save_structure(structure["tables"], structure["fingerprint"], "replit-artstore-v1")
        store = app.fake_store()
        self.assertEqual(store.environment, "production")
        self.assertFalse(store.writes_enabled)
        self.assertTrue(all(i.startswith("real-") for i in store.tables["categories"]))

    def test_the_dashboard_can_not_turn_it_on_or_hold_a_write_login(self):
        src = read(REPO / "services/local_api/server.py")
        self.assertNotIn("WRITE_DB_URL", src)
        self.assertNotIn("UPLOAD_PASSWORD", src)
        self.assertNotIn('"publish_target"] =', src)
        self.assertNotIn("live_store", src)


class Wiring(unittest.TestCase):
    def test_only_live_store_reads_the_write_login(self):
        self.assertNotIn("read_env", read(REPO / "services/workers/publisher.py"))
        self.assertIn("live_store.connect(app)", read(REPO / "services/workers/publisher.py"))
        self.assertIn("if live:", read(REPO / "services/workers/publisher.py"))
        self.assertIn("LIVE_RETRY_SECONDS if live and worker is None", read(REPO / "services/workers/publisher.py"))

    def test_the_example_settings_stay_empty(self):
        for line in read(REPO / ".env.example").splitlines():
            if re.match(r"#? *STOREFRONT_\w+_(UPLOAD_PASSWORD|WRITE_DB_URL|SUPABASE_PUBLISHABLE_KEY)\b", line):
                self.assertTrue(line.startswith("#") and line.rstrip().endswith("="), line)

    def test_the_runbook_scripts_name_what_the_checks_expect(self):
        book = read(REPO / "docs/runbooks/write-role.md")
        for name in live_store.SUFFIXES.values() if live_store else ():
            self.assertIn(f"STOREFRONT_A_{name}", book + "STOREFRONT_A_DB_URL")
        self.assertIn("WITH CHECK (status = 'draft')", book)
        self.assertIn("scripts/go_live.py storefront-a --on", book)


class Support(unittest.TestCase):
    PAGE = "apps/review-dashboard/src/pages/Support.tsx"

    def test_it_can_be_reached(self):
        src = read(REPO / "apps/review-dashboard/src/main.tsx")
        self.assertIn('["support", "Support"]', src)
        self.assertIn("<Support state={state} />", src)

    def test_it_shows_both_halves_of_the_flow_and_who_does_what(self):
        src = read(REPO / self.PAGE)
        self.assertIn('<Lane title="In Commerce OS, on your computer" steps={HERE} start={1} />', src)
        self.assertIn('<Lane title="In your store" steps={STORE} start={5} />', src)
        self.assertEqual(src.count("{ title: \""), 8)
        self.assertEqual(src.count("you: true"), 4)
        self.assertIn("You set it to Active", src)

    def test_it_says_where_publish_goes_today(self):
        src = read(REPO / self.PAGE)
        self.assertIn('state.publish_target === "live"', src)
        self.assertIn("a local test store on this computer", src)

    def test_what_it_promises_is_there(self):
        self.assertIn("<InstallHelp />", read(REPO / self.PAGE))
        self.assertIn("Stop all writing", read(REPO / self.PAGE))
        self.assertIn("Stop all writing", read(REPO / "apps/review-dashboard/src/pages/Publish.tsx"))


def runbook_sql(start: str) -> str:
    blocks = re.findall(r"```sql\n(.*?)```", read(REPO / "docs/runbooks/write-role.md"), re.S)
    return next(b for b in blocks if b.startswith(start))


@needs_pg
class RunbookOnRealPostgres(unittest.TestCase):
    """The owner's exact SQL, on a private Postgres shaped like the store, then a whole publish through it."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tmp()
        cls.store = LocalStore("storefront-a", cls.dir / "store", port=55442)
        cls.cluster = cls.store.cluster
        cls.cluster.start()
        cls.cluster.run_sql((cls.store.base / "schema.sql").read_text())
        cls.cluster.run_sql(cls.store.ldb.runbook_read_role_sql("invented-read-pw"))
        cls.cluster.run_sql("ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;")
        cls.cluster.run_sql(runbook_sql("CREATE ROLE commerce_os_write").replace("<password>", "invented-write-pw"))
        seed = snapshot()
        lit = cls.store.ldb.lit
        for table in ("categories", "tags"):
            for row in seed[table]:
                cols = ", ".join(row)
                cls.cluster.run_sql(f"INSERT INTO public.{table} ({cols}) VALUES ({', '.join(lit(v) for v in row.values())});")

    @classmethod
    def tearDownClass(cls):
        cls.store.down(delete=True)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def rows(self, statement, user="postgres"):
        with psycopg.connect(self.store.dsn(user), autocommit=True) as conn:
            cur = conn.execute(statement)
            return cur.fetchall() if cur.description else None

    def test_the_runbook_login_passes_every_check(self):
        with psycopg.connect(self.store.dsn(WRITE_ROLE), autocommit=True) as conn:
            self.assertEqual(live_store.check_write_login(PgRows(conn)), [])

    def test_a_publish_through_it_goes_in_as_a_draft_with_real_ids(self):
        self.rows("DELETE FROM public.products")
        d = tmp()
        out = d / "review"
        (out / "img").mkdir(parents=True)
        from PIL import Image
        Image.new("RGB", (600, 600), (190, 110, 60)).save(out / "img" / "fox.framed.jpg")
        (out / "items.json").write_text(json.dumps([dict(ITEM, id="fox", source="Fox.jpg", kind="artwork", framed="img/fox.framed.jpg",
                                                         art_file="img/fox.framed.jpg", status="ready")]))
        (d / "config.json").write_text(json.dumps({"storefronts": [dict(ENTRY, publish_target="live")]}))
        (d / "mapping.json").write_text(json.dumps(MAPPING))
        app = load_server().App(out=out, brand_root=d / "brand", learning_root=d / "learning", config=d / "config.json", source=tmp(),
                                rooms_root=d / "rooms", mapping=d / "mapping.json")
        ldb = self.store.ldb

        def structure(rows):
            tables = ldb.read_structure(rows)
            return {"tables": tables, "fingerprint": ldb.fingerprint(tables)}
        with psycopg.connect(self.store.dsn(READ_ROLE), autocommit=True) as conn:
            live = structure(PgRows(conn))
        app.catalog.save(snapshot())
        app.catalog.save_structure(live["tables"], live["fingerprint"], "replit-artstore-v1")
        app.store.save_draft("fox", record_for("fox", 1))
        app.store.approve("fox", "owner")
        app.update_listing("fox", {"facts": FACTS})
        p = app.storefront_preview("fox")
        self.assertTrue(p["approvable"], p["blockers"])
        self.assertEqual(p["environment"], "production")
        approved = app.approve_storefront("fox", {"change_set_hash": p["change_set"]["change_set_hash"], "status": "draft"})
        app.publish("fox", {"change_set_hash": approved["change_set"]["change_set_hash"]})
        profile = json.loads((REPO / "resources/catalog-profiles/replit-artstore-v1.json").read_text())
        adapter = PostgresArtStore("storefront-a", "production", profile, live, write_dsn=self.store.dsn(WRITE_ROLE),
                                   read_dsn=self.store.dsn(READ_ROLE), currency="USD", features=[], read_structure=structure)
        bucket = Bucket()
        images = SupabaseAssetStore(f"https://{REF}.supabase.co", "pk", "u@example.test", "invented-pw", "artwork", send=bucket)
        Worker(app, app.pubs, adapter, images).run_once()
        self.assertEqual(app.pubs.state("fox"), "SUCCEEDED", app.pubs.events("fox")[-1])
        status, category, pics = self.rows("SELECT status, category_id, images FROM public.products")[0]
        self.assertEqual(status, "draft")
        self.assertTrue(category.startswith("real-"))
        self.assertTrue(pics[0].startswith("/objects/uploads/"))
        self.assertIn(pics[0].replace("/objects/", ""), bucket.objects)
        self.assertIn(f"_meta/{pics[0].replace('/objects/', '')}.json", bucket.objects)
        # the same login can't do anything else with what it just added
        for attempt in ("UPDATE public.products SET status = 'active'", "DELETE FROM public.products",
                        "SELECT * FROM public.users"):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=attempt):
                self.rows(attempt, WRITE_ROLE)
        row = self.rows("SELECT to_jsonb(p) FROM public.products p")[0][0]
        cols = [c for c in row if row[c] is not None and c not in ("id", "slug", "status", "created_at", "updated_at")]
        values = ", ".join(self.store.ldb.lit(json.dumps(row[c]) if isinstance(row[c], (list, dict)) else row[c]) for c in cols)
        for status_value in ("active", "archived"):
            statement = (f"INSERT INTO public.products (slug, status, {', '.join(cols)}) VALUES ('other-{status_value}', '{status_value}', {values})")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=status_value):
                self.rows(statement, WRITE_ROLE)
