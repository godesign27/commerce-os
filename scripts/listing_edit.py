#!/usr/bin/env python3
"""Change a listing's copy from the command line: the engine behind /listing-edit (B-059).

Usage (project environment):
    .venv/bin/python scripts/listing_edit.py find <words>                 which listings match
    .venv/bin/python scripts/listing_edit.py show <listing>               the copy as it stands
    .venv/bin/python scripts/listing_edit.py set <listing> <field> <text> save your words for one field
    .venv/bin/python scripts/listing_edit.py set <listing> <field> --file <path>   (or - for stdin)
    .venv/bin/python scripts/listing_edit.py choose <listing> <1|2|3>     use one of the drafted titles
    .venv/bin/python scripts/listing_edit.py revert <listing> <field|all> go back to the draft

<listing> is an item ID, or words from its title or file name ("wolf"). Fields: title, short,
collector, tags, keywords (tags and keywords take a comma-separated list).

Writes the same local files as the dashboard (.commerce-os/review/listings.json), through the same
rules: only the named field changes, approved copy is locked until it's unlocked on the dashboard,
and the checks run on what you saved. Exit codes: 0 saved or shown, 1 refused, 2 no single listing
matches. Nothing is published and no model is called.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from packages.drafting import brand, editing  # noqa: E402
from packages.drafting.store import LIST_FIELDS, LockedError, Store  # noqa: E402

OUT = REPO / ".commerce-os" / "review"
DASHBOARD = "http://127.0.0.1:8770/#/listings/"


def show(store: Store, item: str) -> str:
    rec = store.draft(item)
    copy = store.effective(item)
    entry = store.listing(item)
    proposed = store.proposed(rec)
    options = rec["draft"]["product"]["attributes"].get("title_options", {}).get("value") or []
    status = "approved (locked)" if entry.get("approved") else ("edited" if entry.get("edits") else "draft")
    lines = [f"{item} · revision {rec['draft']['revision']} · {status}", f"Dashboard: {DASHBOARD}{item}", ""]
    for k in editing.FIELDS:
        v = copy[k]
        v = ", ".join(v) if k in LIST_FIELDS else v
        mark = "" if copy[k] == proposed[k] else "  [your edit]"
        lines += [f"{editing.LABELS[k]}{mark}:", f"  {v}", ""]
    if options:
        lines.append("Title options:")
        lines += [f"  {i}. {o['title']}" + ("  (current)" if o["title"] == copy["title"] else "")
                  for i, o in enumerate(options, 1)]
    return "\n".join(lines).rstrip()


def report(res: dict) -> str:
    copy = res["copy"]
    lines = []
    for k in res["saved"]:
        v = copy[k]
        lines.append(f"Saved {editing.LABELS[k].lower()}: {', '.join(v) if k in LIST_FIELDS else v}")
    if res["checks"]:
        lines.append("Checks:")
        lines += [f"  [{c['severity']}] {c['message']}" for c in res["checks"]]
    else:
        lines.append("Checks: nothing to flag.")
    lines.append(f"Refresh the dashboard to see it: {DASHBOARD}{res['item']}")
    return "\n".join(lines)


def resolve(items, store, query) -> str:
    found = editing.find_items(items, store, query)
    if len(found) == 1:
        return found[0]
    if not found:
        raise LookupError(f"No drafted listing matches {query!r}. Try: listing_edit.py find <words>")
    names = "\n".join(f"  {i}: {(store.effective(i) or {}).get('title', '')}" for i in found[:15])
    raise LookupError(f"{len(found)} listings match {query!r}; say which:\n{names}")


def main(argv=None, out: Path = OUT, brand_root: Path = brand.BRAND_DIR, stdin=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--storefront", default="storefront-a")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("find").add_argument("words", nargs="+")
    sub.add_parser("show").add_argument("listing")
    p = sub.add_parser("set")
    p.add_argument("listing"); p.add_argument("field"); p.add_argument("text", nargs="?")
    p.add_argument("--file", help="read the text from a file, or - for stdin")
    p = sub.add_parser("choose")
    p.add_argument("listing"); p.add_argument("number", type=int)
    p = sub.add_parser("revert")
    p.add_argument("listing"); p.add_argument("field")
    args = ap.parse_args(argv)

    store = Store(out)
    items_path = Path(out) / "items.json"
    items = json.loads(items_path.read_text()) if items_path.exists() else []
    try:
        if args.cmd == "find":
            found = editing.find_items(items, store, " ".join(args.words))
            print("\n".join(f"{i}: {(store.effective(i) or {}).get('title', '')}" for i in found) or "No match.")
            return 0 if found else 2
        item = resolve(items, store, args.listing)
        if args.cmd == "show":
            print(show(store, item))
            return 0
        ctx = brand.load(args.storefront, brand_root)
        if args.cmd == "set":
            field = editing.field_name(args.field)
            if args.file:
                text = (stdin or sys.stdin).read() if args.file == "-" else Path(args.file).read_text()
            elif args.text is not None:
                text = args.text
            else:
                raise ValueError("give the new text, or --file")
            value = [x.strip() for x in text.split(",") if x.strip()] if field in LIST_FIELDS else text.strip()
            print(report(editing.save(store, item, {field: value}, ctx)))
        elif args.cmd == "choose":
            options = store.draft(item)["draft"]["product"]["attributes"].get("title_options", {}).get("value") or []
            if not 1 <= args.number <= len(options):
                raise ValueError(f"there are {len(options)} title options")
            print(report(editing.save(store, item, {"title": options[args.number - 1]["title"]}, ctx)))
        elif args.cmd == "revert":
            fields = list(editing.FIELDS) if args.field == "all" else [editing.field_name(args.field)]
            editing.save(store, item, {k: None for k in fields}, ctx)
            print(f"Back to the draft for {', '.join(editing.LABELS[k].lower() for k in fields)}.")
        return 0
    except LookupError as e:
        print(e, file=sys.stderr)
        return 2
    except LockedError as e:
        print(f"{e}. Unlock it on the dashboard first: {DASHBOARD}{item}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Not saved: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
