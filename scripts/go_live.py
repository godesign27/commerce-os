#!/usr/bin/env python3
"""Check whether a store is ready for live publishing, and turn it on or off. Run by the owner. See docs/runbooks/write-role.md.

    .venv/bin/python scripts/go_live.py <storefront-id>         only check; changes nothing
    .venv/bin/python scripts/go_live.py <storefront-id> --on    check, then turn the live store on
    .venv/bin/python scripts/go_live.py <storefront-id> --off   go back to the local test store

It never writes to a store, and it never prints a login. Agents don't run this: turning it on is the owner's decision.
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from packages import onboarding  # noqa: E402
from packages.publisher import live_store  # noqa: E402
from packages.publisher.assets import SupabaseAssetStore  # noqa: E402

CONFIG = REPO / "config" / "storefronts.local.json"


def set_target(config: Path, storefront: str, on: bool):
    """Only this store's two settings change. Nothing else in the file is touched."""
    cfg = json.loads(config.read_text())
    entry = next(s for s in cfg["storefronts"] if s["id"] == storefront)
    entry["publish_target"] = live_store.LIVE if on else "local"
    entry["writes_enabled"] = on
    entry["asset_upload"] = "authorized" if on else "not_authorized"
    tmp = config.with_name(config.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n")
    os.replace(tmp, config)


def check(entry: dict, env: dict) -> list:
    try:
        found = live_store.settings(entry, env)
    except live_store.LiveNotReady as e:
        return [str(e)]
    images = SupabaseAssetStore(found["url"], found["key"], found["email"], found["password"], found["bucket"])
    return live_store.preflight(found, images)


def main(argv=None, config: Path = CONFIG, env_file: Path = live_store.ENV_FILE) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("storefront")
    ap.add_argument("--on", action="store_true")
    ap.add_argument("--off", action="store_true")
    args = ap.parse_args(argv)
    if args.on and args.off:
        ap.error("choose --on or --off")
    cfg = json.loads(config.read_text()) if config.exists() else {}
    entry = next((s for s in cfg.get("storefronts", []) if s["id"] == args.storefront), None)
    if not entry:
        print(f"There's no store called {args.storefront} in {config.name}.")
        return 2
    if args.off:
        set_target(config, args.storefront, False)
        print("Publish goes to the local test store. Restart Commerce OS for this to take effect.")
        return 0
    problems = check(entry, onboarding.read_env(env_file))
    if problems:
        print("Not ready for live publishing:")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("✓ Every check passed: the logins are limited, and only Drafts can be added.")
    if args.on:
        set_target(config, args.storefront, True)
        print("The live store is on. Restart Commerce OS, then publish one piece and check it in the store's admin.")
    else:
        print("Nothing changed. Run this again with --on to turn the live store on.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
