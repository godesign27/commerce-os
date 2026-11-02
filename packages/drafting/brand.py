"""A storefront's brand context (contract `brand-context`): load, scope, render for the prompt, version.

The brand context is the storefront's voice: for an artist site the artist's philosophy, kinds of work
and confirmed meanings; for a product site the brand story and product lines. It holds the owner's own
words, so it lives in gitignored `config/brand/<storefront>.local.json`; every save writes a new
version and archives the previous one in `config/brand/history/`.

Only humans change it. The model never writes a meaning or approves a lesson: lessons proposed by the
learning loop arrive with status `proposed`, and only `approved` ones reach the prompt.
"""
import copy
import datetime
import json
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[2]
BRAND_DIR = REPO / "config" / "brand"
SKILL_REFS = REPO / "plugins" / "commerce-os" / "skills" / "listing-copy" / "references"


class BrandContextError(Exception):
    """The brand context is missing or does not validate."""


def now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def path_for(storefront: str, root: Path = BRAND_DIR) -> Path:
    return Path(root) / f"{storefront}.local.json"


def violations(ctx: dict) -> List[str]:
    from packages.policy import registry
    errors = registry().validate(ctx, "brand-context.schema.json")
    if not errors:
        ids = [m["id"] for m in ctx["meanings"]] + [x["id"] for x in ctx["lessons"]] + [e["id"] for e in ctx["examples"]]
        if len(ids) != len(set(ids)):
            errors.append("$: meaning, lesson and example IDs must be unique")
        for k in ("short_words", "collector_words"):
            r = ctx["length"][k]
            if r["min"] > r["max"]:
                errors.append(f"$.length.{k}: min is above max")
    return errors


def load(storefront: str, root: Path = BRAND_DIR) -> Optional[dict]:
    """The current brand context, or None when the storefront has none yet."""
    p = path_for(storefront, root)
    if not p.exists():
        return None
    ctx = json.loads(p.read_text(encoding="utf-8"))
    errors = violations(ctx)
    if errors:
        raise BrandContextError(f"{p.name} does not validate: {errors[:3]}")
    return ctx


def save(ctx: dict, actor: dict, root: Path = BRAND_DIR) -> dict:
    """Write a new version: archive the current one, bump `version`, validate, write. Returns the new doc."""
    root = Path(root)
    current = load(ctx["storefront_id"], root)
    new = copy.deepcopy(ctx)
    new["version"] = (current["version"] + 1) if current else max(1, int(ctx.get("version", 1)))
    new["updated_at"], new["updated_by"] = now(), actor
    errors = violations(new)
    if errors:
        raise BrandContextError(f"not saved: {errors[:3]}")
    if current:
        hist = root / "history"
        hist.mkdir(parents=True, exist_ok=True)
        archived = hist / f"{current['storefront_id']}.v{current['version']}.json"
        if not archived.exists():                 # history is never rewritten
            archived.write_text(json.dumps(current, indent=1), encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    path_for(new["storefront_id"], root).write_text(json.dumps(new, indent=1), encoding="utf-8")
    return new


def history(storefront: str, root: Path = BRAND_DIR) -> List[dict]:
    hist = Path(root) / "history"
    out = []
    for p in sorted(hist.glob(f"{storefront}.v*.json"), key=lambda p: int(p.stem.rsplit(".v", 1)[1])):
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({"version": d["version"], "updated_at": d["updated_at"], "updated_by": d["updated_by"]["id"]})
    return out


def meanings_in_scope(ctx: dict, item_id: str, series: Optional[str] = None) -> List[dict]:
    """Meanings that apply to this item: its own, its series' (exact name, case-insensitive), catalog-wide."""
    out = []
    for m in ctx.get("meanings", []):
        kind, ref = m["scope"]["kind"], m["scope"]["ref"]
        if kind == "catalog" or (kind == "artwork" and ref == item_id) or \
                (kind == "series" and series and ref and ref.strip().lower() == series.strip().lower()):
            out.append(m)
    return out


def standards_text() -> str:
    """The storefront-neutral craft, read from the listing-copy skill (one source for skill and service)."""
    return (SKILL_REFS / "writing-standards.md").read_text(encoding="utf-8")


def render(ctx: Optional[dict]) -> str:
    """The stable part of the brand context for the system prompt. Scoped meanings go in the user turn."""
    if ctx is None:
        return ("BRAND CONTEXT: none recorded for this storefront. Write in a warm, plain, specific voice and "
                "add an 'ask_artist' question asking for the brand's voice.")
    kind = ctx["site_kind"]
    who = "artist" if kind == "artist" else "brand"
    lines = [f"BRAND CONTEXT (version {ctx['version']}; site kind: {kind})", "",
             f"Name: {ctx['identity']['name']}. Name usage: {ctx['identity']['name_usage']}"]
    if ctx["identity"].get("audience"):
        lines.append(f"Audience: {ctx['identity']['audience']}")
    lines += ["", f"The {who}'s own words (background for you; do not quote or echo its vocabulary):",
              ctx["philosophy"], "", "Categories:"]
    for c in ctx["categories"]:
        lines.append(f"- {c['id']} ({c['name']}): {c['description']} How to write it: {c['writing_approach']}")
    v = ctx["voice"]
    lines += ["", f"Tone: {v['tone']}"]
    lines += [f"Do: {d}" for d in v["do"]] + [f"Avoid: {a}" for a in v["avoid"]]
    sw = ctx["style_words"]
    if sw["accept"]:
        lines.append("Style words the " + who + " accepts: " + ", ".join(sw["accept"]))
    if sw["reject"]:
        lines.append("Style words the " + who + " rejects (never use): " + ", ".join(sw["reject"]))
    lessons = [x for x in ctx["lessons"] if x["status"] == "approved"]
    if lessons:
        lines += ["", f"Lessons from the {who}'s own edits (follow these):"] + [f"- {x['text']}" for x in lessons]
    lim = ctx["length"]
    lines += ["", f"Length: short description {lim['short_words']['min']} to {lim['short_words']['max']} words "
                  f"and at most {lim['short_chars_max']} characters; collector description "
                  f"{lim['collector_words']['min']} to {lim['collector_words']['max']} words."]
    examples = [e for e in ctx["examples"] if e["status"] == "approved"]
    if examples:
        lines += ["", "Approved examples (for voice only: never reuse their titles, openings or phrases):"]
        for e in examples:
            lines += [f"- [{e['category']}] {e['title']}: {e['short_description']}",
                      f"  {e['collector_description']}", f"  Why it works: {e['why']}"]
    return "\n".join(lines)


def render_scoped(meanings: List[dict]) -> str:
    if not meanings:
        return "Confirmed meanings for this piece: none. Any meaning you offer is a proposal."
    lines = ["Confirmed meanings that apply to this piece (cite the ID when you use one). Catalog-wide ones are "
             "background: let them shape your reading, but do not restate them in the copy."]
    for m in sorted(meanings, key=lambda m: m["scope"]["kind"] == "catalog"):
        scope = m["scope"]["kind"] + (f" '{m['scope']['ref']}'" if m["scope"]["ref"] else "")
        lines.append(f"- {m['id']} [{scope}] {m['subject']}: {m['meaning']}")
    return "\n".join(lines)
