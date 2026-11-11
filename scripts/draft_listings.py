#!/usr/bin/env python3
"""Draft titles, descriptions and tags for the artworks on the review page, with Claude (B-055, B-056).

Usage (project environment):
    .venv/bin/python scripts/draft_listings.py --limit 5        draft the first 5 not yet drafted
    .venv/bin/python scripts/draft_listings.py --only <id> ...  draft specific review items
    .venv/bin/python scripts/draft_listings.py --redo ...       draft again as a new revision
    .venv/bin/python scripts/draft_listings.py --estimate       count and estimate cost; call nothing
    .venv/bin/python scripts/draft_listings.py --learn          propose lessons from your edits

Reads .commerce-os/review/items.json (built by review_images.py), the image each item uses (the crop,
rotated if you rotated it, or the ready-cut file), and the storefront's brand context
(config/brand/<storefront>.local.json). Rejected and approved items are skipped. Each draft is a new
revision of a canonical-draft document, checked by packages/policy, the claim check and the repetition
checks, written to .commerce-os/review/drafts/. Pieces are drafted one after another so each sees the
titles the previous ones took. Nothing is published, and the drafts are marked simulated.

Needs ANTHROPIC_API_KEY in .env (or the environment). Every call costs money; the summary prints the
estimated total.
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from packages.drafting import brand, learning, listing, service  # noqa: E402
from packages.drafting.store import Store  # noqa: E402

OUT = REPO / ".commerce-os" / "review"
DRAFTS = OUT / "drafts"
STOREFRONT = "storefront-a"


def load_env_key() -> str:
    import importlib.util
    spec = importlib.util.spec_from_file_location("crr", REPO / "scripts" / "check_read_role.py")
    crr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crr)
    env_file = REPO / ".env"
    key = (crr.parse_dotenv(env_file.read_text()).get("ANTHROPIC_API_KEY") if env_file.exists() else None)
    return key or os.environ.get("ANTHROPIC_API_KEY") or ""


def candidates(items: list, decisions: dict, only=None, redo=False, listings=None) -> list:
    listings = listings or {}
    out = []
    for it in items:
        if only and it["id"] not in only:
            continue
        if not it.get("art_file") or decisions.get(it["id"], {}).get("decision") == "reject":
            continue
        if listings.get(it["id"], {}).get("approved"):
            continue                              # approved copy is locked; unlock it in the dashboard
        if not redo and (DRAFTS / f"{it['id']}.json").exists():
            continue
        out.append(it)
    return out


def client_from_env():
    key = load_env_key()
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY isn't set. Add a line to .env:  ANTHROPIC_API_KEY=sk-ant-...  "
                         "(never paste it into chat or commit it).")
    import anthropic
    return anthropic.Anthropic(api_key=key)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--learn", action="store_true")
    ap.add_argument("--model", default=listing.MODEL)
    ap.add_argument("--storefront", default=STOREFRONT)
    args = ap.parse_args(argv)

    if args.learn:
        import anthropic
        res = service.distil_lessons(client_from_env(), args.storefront,
                                     {"kind": "agent", "id": "learning-loop"}, model=args.model)
        print(f"{res['proposed']} lesson(s) proposed (brand context v{res['version']}, ${res['cost_usd']:.3f}). "
              "Approve or reject them on the dashboard's Learning page.")
        return 0

    items_path = OUT / "items.json"
    if not items_path.exists():
        raise SystemExit("No review items yet. Run: .venv/bin/python scripts/review_images.py build")
    items = json.loads(items_path.read_text())
    decisions = json.loads((OUT / "decisions.json").read_text()) if (OUT / "decisions.json").exists() else {}
    store = Store(OUT)
    todo = candidates(items, decisions, set(args.only or []), args.redo, store.listings())
    if args.limit:
        todo = todo[:args.limit]
    from packages.policy import load_product_types
    product_types = load_product_types()
    tags = service.store_tags(args.storefront)
    ctx = brand.load(args.storefront)
    voice = f"brand context v{ctx['version']} ({ctx['site_kind']} site)" if ctx else "NO brand context"
    print(f"{len(todo)} piece(s) to draft with {args.model}; {voice}; {len(tags)} store tags.")
    if args.estimate or not todo:
        print("Rough cost: about $0.08–0.12 per piece (one image, the brand context and a long draft).")
        return 0

    import anthropic
    client = client_from_env()
    learn = learning.Learning()
    total, done, failed = 0.0, 0, []
    for n, item in enumerate(todo, 1):
        try:
            record = service.draft_item(client, item, store=store, ctx=ctx, product_types=product_types,
                                        tags=tags, model=args.model, learn=learn,
                                        reference=brand.reference_text(args.storefront))
        except listing.ModelError as e:
            failed.append((item["source"], str(e)))
            print(f"[{n:>3}] failed   {item['source']}: {e}")
            continue
        except anthropic.AuthenticationError:
            raise SystemExit("The API key was rejected. Check ANTHROPIC_API_KEY in .env.")
        except anthropic.APIError as e:
            failed.append((item["source"], f"{type(e).__name__}: {e}"))
            print(f"[{n:>3}] failed   {item['source']}: {type(e).__name__}")
            continue
        total += record["cost_usd"]
        done += 1
        issues = record["draft"]["review_issues"]
        blocking = sum(1 for i in issues if i["severity"] == "blocking")
        warnings = sum(1 for i in issues if i["severity"] == "warning")
        title = record["draft"]["product"]["title"]["value"]
        print(f"[{n:>3}] drafted  {item['source']}: \"{title}\" (r{record['draft']['revision']}; {blocking} blocking, "
              f"{warnings} warnings; ${record['cost_usd']:.3f})"
              + (f"  POLICY: {record['policy_violations']}" if record["policy_violations"] else ""))
    print(f"\n{done} drafted, {len(failed)} failed; estimated cost ${total:.2f}.")
    print("Review them in the dashboard: .venv/bin/python services/local_api/server.py")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
