#!/usr/bin/env python3
"""The publishing worker: the only program that can write to a store (B-070). Started by ./start.sh.

    .venv/bin/python services/workers/publisher.py [--storefront storefront-a] [--once]

Its target is the local test store, unless the owner has turned the live store on (scripts/go_live.py). Then its
logins come through packages/publisher/live_store.py, which checks them first, and it never falls back to the other
target. One worker at a time, enforced with a lock. If the store can't run, it says why and the dashboard shows it.
"""
import argparse
import fcntl
import importlib.util
import signal
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from packages.publisher import live_store  # noqa: E402
from packages.publisher.assets import LocalAssetStore  # noqa: E402
from packages.publisher.local_store import LocalStore, StoreUnavailable  # noqa: E402
from packages.publisher.worker import Worker  # noqa: E402

POLL_SECONDS = 2
LIVE_RETRY_SECONDS = 60      # a live store that isn't ready: don't keep trying its logins every two seconds


def load_app(storefront: str):
    spec = importlib.util.spec_from_file_location("local_api", REPO / "services" / "local_api" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.App(storefront=storefront)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--storefront", default="storefront-a")
    ap.add_argument("--once", action="store_true", help="handle what's waiting, then stop")
    args = ap.parse_args(argv)

    app = load_app(args.storefront)
    pubs = app.pubs
    pubs.root.mkdir(parents=True, exist_ok=True)
    lock = (pubs.root / "worker.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("A publishing worker is already running.")
        return 0

    live = app.storefront_entry().get("publish_target") == live_store.LIVE
    store, worker = None if live else LocalStore(args.storefront), None

    def stop(*_):                                  # leave nothing running; it picks up where it was next time
        if store:
            store.down(delete=False)
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        try:
            if worker is None:
                mapping = app.mapping()
                if not mapping:
                    raise StoreUnavailable("The store's categories aren't set up yet: finish Getting started.")
                if live:
                    worker = Worker(app, pubs, *live_store.connect(app))
                else:
                    store.up(mapping)
                    worker = Worker(app, pubs, store.adapter(app.storefront_entry()), LocalAssetStore(store.assets))
                worker.recover()
            app._reset_store()                     # pick up mapping changes made in the dashboard
            if store:
                store.sync(app.mapping())
            pubs.beat(True)
            worker.run_once()
        except StoreUnavailable as e:
            pubs.beat(False, str(e))
        except Exception as e:                     # say so and keep going; a publish in flight is handled by recover()
            print(f"publisher: {type(e).__name__}: {e}", file=sys.stderr)
            pubs.beat(False, "The worker hit a problem and will try again.")
        if args.once:
            return 0
        time.sleep(LIVE_RETRY_SECONDS if live and worker is None else POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
