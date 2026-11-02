"""The learning loop: what the owner changed in the model's copy, and what that says about the voice.

1. **Record.** When copy is approved (or edits are replaced by a redraft), every field the owner changed
   becomes an edit record in `.commerce-os/learning/edits.jsonl`: the proposed text, the final text, a
   word-level diff, and the brand-context and prompt versions that produced the draft.
2. **Use directly.** The most instructive recent pairs go into the next drafts' prompt as examples of
   "the draft said this; the owner changed it to that".
3. **Distil.** On request, Claude reads the edit records and proposes general lessons ("prefer one
   strong verb to two adjectives"), each citing the edits it came from. Lessons are added to the brand
   context as `proposed`. Only the owner approves them, and only approved lessons reach the prompt.
4. **Measure.** How much of each draft survives approval, over time, so it is visible whether the
   drafts are getting closer to the owner's voice.

Nothing here changes the brand context without a human: distillation writes proposals only.
"""
import difflib
import json
from pathlib import Path
from typing import List, Optional

from packages.drafting import brand
from packages.drafting.checks import words

REPO = Path(__file__).resolve().parents[2]
LEARNING = REPO / ".commerce-os" / "learning"
TRACKED = ("title", "short_description", "collector_description", "store_tags", "search_keywords")
LESSON_PROMPT = "learning-lessons@1"
PAIRS_IN_PROMPT = 3


def _text(v) -> str:
    return ", ".join(v) if isinstance(v, list) else (v or "")


def diff(proposed: str, final: str) -> dict:
    """Word-level diff: similarity, words removed, words added, change in length."""
    a, b = words(proposed), words(final)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    removed, added = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("replace", "delete"):
            removed.append(" ".join(a[i1:i2]))
        if op in ("replace", "insert"):
            added.append(" ".join(b[j1:j2]))
    return {"similarity": round(sm.ratio(), 3), "removed": removed[:20], "added": added[:20],
            "length_change": len(b) - len(a)}


class Learning:
    def __init__(self, root: Path = LEARNING):
        self.root = Path(root)
        self.path = self.root / "edits.jsonl"

    def edits(self) -> List[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def record(self, *, item: str, proposed: dict, final: dict, revision: int, versions: dict, event: str,
               category: Optional[str] = None) -> List[dict]:
        """Append one record per changed field. Unchanged fields are recorded too, as acceptances, so the
        acceptance rate is honest. Returns the new records."""
        self.root.mkdir(parents=True, exist_ok=True)
        start = len(self.edits())
        new = []
        for field in TRACKED:
            p, f = _text(proposed.get(field)), _text(final.get(field))
            if not p and not f:
                continue
            rec = {"id": f"edit-{start + len(new) + 1}", "at": brand.now(), "item": item, "field": field,
                   "event": event, "revision": revision, "category": category,
                   "brand_context": versions.get("brand_context"), "prompt": versions.get("prompt"),
                   "changed": p.strip() != f.strip(), "proposed": p, "final": f, "diff": diff(p, f)}
            new.append(rec)
        with self.path.open("a") as fh:
            for rec in new:
                fh.write(json.dumps(rec) + "\n")
        return new

    def changed(self) -> List[dict]:
        return [e for e in self.edits() if e["changed"]]

    def prompt_pairs(self, category: Optional[str] = None, n: int = PAIRS_IN_PROMPT) -> List[dict]:
        """The most instructive recent edits of prose: largest change first among the latest 20, same
        category preferred. Titles are left out: a past title must never be suggested again."""
        prose = [e for e in self.changed() if e["field"] in ("short_description", "collector_description")]
        recent = prose[-20:]
        recent.sort(key=lambda e: (e.get("category") != category, e["diff"]["similarity"]))
        return recent[:n]

    def stats(self) -> dict:
        """How much of each draft survives approval, by field, overall and in the latest 10 approvals."""
        recs = [e for e in self.edits() if e["event"] == "approved"]
        out = {"approvals": len({(e["item"], e["revision"]) for e in recs}), "by_field": {}}
        for field in TRACKED:
            rs = [e for e in recs if e["field"] == field]
            if not rs:
                continue
            latest = rs[-10:]
            out["by_field"][field] = {
                "records": len(rs),
                "accepted_unchanged": round(sum(not e["changed"] for e in rs) / len(rs), 3),
                "similarity": round(sum(e["diff"]["similarity"] for e in rs) / len(rs), 3),
                "similarity_latest_10": round(sum(e["diff"]["similarity"] for e in latest) / len(latest), 3),
            }
        return out

    def repeated_removals(self, min_count: int = 2) -> List[dict]:
        """Words and short phrases the owner removed in at least `min_count` different listings."""
        seen = {}
        for e in self.changed():
            if e["field"] not in ("short_description", "collector_description", "title"):
                continue
            for chunk in e["diff"]["removed"]:
                for w in set(chunk.split()):
                    if len(w) >= 5:
                        seen.setdefault(w, set()).add(e["item"])
        return sorted(({"phrase": w, "items": sorted(items)} for w, items in seen.items() if len(items) >= min_count),
                      key=lambda x: -len(x["items"]))


def pairs_text(pairs: List[dict]) -> str:
    if not pairs:
        return ""
    lines = ["How the owner has edited earlier drafts (learn the direction; never reuse their wording):"]
    for e in pairs:
        lines += [f"- {e['field'].replace('_', ' ')}, draft: {e['proposed']}", f"  owner's version: {e['final']}"]
    return "\n".join(lines)


# ---------------------------------------------------------------- distilling lessons with Claude

LESSON_SYSTEM = """You help an independent storefront's owner teach a copywriting assistant their voice. \
You are given pairs of (draft, owner's final version) and the lessons already on record. Propose general \
writing preferences the owner's edits show, which would improve future drafts for other pieces.

Rules:
- A lesson is about voice, structure, word choice or length. Never a fact about one artwork, and never a \
meaning or a personal or spiritual claim: meanings come only from the owner directly.
- Each lesson cites the edit IDs it is based on. Prefer lessons supported by two or more edits; a lesson \
from a single edit must be strongly evident.
- Do not repeat or rephrase a lesson already on record.
- At most five lessons, each one sentence, written as an instruction to the writer.
- If the edits show nothing general, return no lessons."""


def lesson_schema() -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["lessons"], "properties": {
        "lessons": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["text", "evidence"],
            "properties": {"text": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}}}}}}


def lesson_request(edits: List[dict], ctx: dict, model: str) -> dict:
    existing = [x["text"] for x in ctx.get("lessons", []) if x["status"] != "rejected"]
    body = ["Lessons already on record:"] + ([f"- {t}" for t in existing] or ["(none)"]) + ["", "Edits:"]
    for e in edits[-60:]:
        body.append(json.dumps({"id": e["id"], "field": e["field"], "draft": e["proposed"], "final": e["final"]}))
    return {
        "model": model, "max_tokens": 8000,
        "system": [{"type": "text", "text": LESSON_SYSTEM}],
        "messages": [{"role": "user", "content": "\n".join(body)}],
        "output_config": {"effort": "high", "format": {"type": "json_schema", "schema": lesson_schema()}},
        "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default",
    }


def add_proposed_lessons(ctx: dict, lessons: List[dict], valid_edit_ids: set) -> dict:
    """Return a copy of the brand context with new `proposed` lessons. Lessons citing no real edit are
    dropped; the caller saves it (a new version), and the owner decides each one."""
    import copy as _copy
    new = _copy.deepcopy(ctx)
    taken = {x["text"].strip().lower() for x in new["lessons"]}
    n = len(new["lessons"])
    for les in lessons:
        evidence = [i for i in les["evidence"] if i in valid_edit_ids]
        text = les["text"].strip()
        if not evidence or not text or text.lower() in taken:
            continue
        n += 1
        new["lessons"].append({"id": f"lesson-{n}", "text": text, "status": "proposed", "source": "edits",
                               "evidence": evidence, "created_at": brand.now()})
        taken.add(text.lower())
    return new
