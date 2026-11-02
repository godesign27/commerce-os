"""Plain-code checks on listing copy: unsupported claims and repetition across the catalog.

The model scores its own copy against the rubric, but it can't see the rest of the catalog and it
grades itself generously. These checks can't be argued with. Each finding becomes a review issue on
the draft (rubric.md in the listing-copy skill lists them).
"""
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# Claims copy may not make without supplied or human-confirmed evidence (evidence policy rules 2 and 4).
UNSUPPORTED_CLAIMS = {
    "authenticity or edition": ["original", "one of a kind", "one-of-a-kind", "unique piece", "limited edition",
                                "signed", "certified", "authentic", "museum quality", "museum-quality"],
    "making": ["handmade", "hand-made", "hand painted", "hand-painted", "handcrafted", "hand-crafted",
               "hand-pulled", "handpulled"],
    "quality": ["premium", "luxury", "high quality", "high-quality", "archival", "heirloom"],
    "medium or material": ["acrylic", "oil", "oils", "watercolor", "watercolour", "gouache", "ink", "pastel",
                           "charcoal", "canvas", "linen", "cotton", "wood panel", "monoprint", "gelli",
                           "linocut", "woodcut", "screenprint", "screen print", "giclee", "giclée",
                           "lithograph", "etching", "mixed media", "mixed-media", "collage", "paper"],
    "size": [r"\d+\s*(x|×|by)\s*\d+", r"\d+\s*(in|inch|inches|cm|mm|\")\b"],
    # a photo can't tell paint from leaf or foil (B-060)
    "surface or finish": ["metallic", "gold leaf", "silver leaf", "copper leaf", "gilded", "gilt", "foil",
                          "shimmer", "shimmers", "shimmering", "glint", "glints", "glinting", "iridescent",
                          "glitter", "lustrous", "pearlescent"],
}
# Supplied medium words that allow the "surface or finish" claims.
FINISH_FACT = re.compile(r"metal|leaf|foil|gild|gilt|glitter|iridesc|pearl|mica|interference", re.I)

# The collector-description voice (B-060): warnings a reviewer can override, never blocks.
STOCK_PHRASES = ["timeless beauty", "timeless", "captivating", "masterpiece", "elevate your space",
                 "elevate any space", "a testament to", "testament to", "statement piece", "breathtaking",
                 "mesmerizing", "mesmerising", "speaks to the soul", "a feast for the eyes", "must-have",
                 "invites you to", "invites viewers", "a celebration of", "evokes a sense of"]
HEDGES = ["perhaps", "maybe", "as if", "as though", "could represent", "might be", "may be", "could be",
          "seems", "seem", "possibly", "suggests", "one might", "you might"]
HEDGE_LIMIT = 3
# The worked examples in the writing standards: drafts must not borrow their sentences. Read from the file,
# so the check and the standards can't drift apart.
STANDARDS = Path(__file__).resolve().parents[2] / "plugins/commerce-os/skills/listing-copy/references/writing-standards.md"


def example_texts() -> List[str]:
    """Each blockquote in the writing standards, joined into one paragraph."""
    out, cur = [], []
    for line in (STANDARDS.read_text(encoding="utf-8").splitlines() if STANDARDS.exists() else []):
        if line.startswith(">"):
            cur.append(line[1:].strip())
        elif cur:
            out.append(" ".join(cur)); cur = []
    if cur:
        out.append(" ".join(cur))
    return out
STOPWORDS = set("""a an and the of in on at to for from with by over under into onto as is are was be it its
this that these those or nor but not no so than then very just all any each every some one two three our your
their his her my me we you they he she them us""".split())


def claim_violations(text: str, facts: Optional[dict] = None) -> List[str]:
    """Unsupported claims in copy, as 'kind: phrase' strings. Supplied facts make their own words allowed:
    edition 'original' allows "original"; a supplied medium allows its words; supplied dimensions allow sizes."""
    facts = facts or {}
    allowed_text = " ".join(str(facts.get(k) or "") for k in ("medium",)).lower()
    found = []
    for kind, phrases in UNSUPPORTED_CLAIMS.items():
        if kind == "size" and facts.get("dimensions"):
            continue
        for phrase in phrases:
            if kind == "authenticity or edition" and phrase == "original" and facts.get("edition") in ("original", "both"):
                continue
            if kind == "medium or material" and allowed_text and re.search(r"\b" + re.escape(phrase) + r"\b", allowed_text):
                continue
            if kind == "surface or finish" and FINISH_FACT.search(allowed_text):
                continue
            pattern = phrase if kind == "size" else r"\b" + re.escape(phrase) + r"\b"
            m = re.search(pattern, text, re.I)
            if m:
                found.append(f"{kind}: '{m.group(0)}'")
    return found


def words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def content_words(text: str) -> List[str]:
    return [w for w in words(text) if w not in STOPWORDS and len(w) >= 4]


def shingles(text: str, n: int = 5) -> set:
    w = words(text)
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def contains_phrase(text: str, phrase: str) -> bool:
    return re.search(r"\b" + re.escape(phrase.lower()) + r"\b", (text or "").lower()) is not None


def _all_text(c: dict) -> str:
    return " ".join(c.get(k) or "" for k in ("title", "short_description", "collector_description"))


def name_in_title(title: str, name: str) -> bool:
    """The subject's searchable name is in the title: the whole name, or its last word ("snow leopard" ->
    "Leopard"), singular or plural, ignoring case and hyphens."""
    title = (title or "").lower().replace("-", " ")
    name = " ".join((name or "").lower().replace("-", " ").split())
    if not name:
        return True
    head = name.split()[-1]
    return any(re.search(r"\b" + re.escape(n) + r"(s|es)?\b", title) for n in {name, head})


def check_copy(copy: dict, others: Iterable[dict], ctx: Optional[dict], self_review: Optional[Dict[str, int]] = None,
               title_options: Optional[List[str]] = None, subject_name: str = "") -> List[dict]:
    """Findings for one piece of copy against the rest of the catalog. `subject_name` is the animal or
    character the title must name ("" for none); its words never count as a reused or shared title word.

    `copy` and each of `others`: {"item", "title", "short_description", "collector_description"}.
    Returns [{"severity", "target", "check", "message"}].
    """
    others = [o for o in others if o.get("item") != copy.get("item")]
    out = []

    def add(severity, target, check, message):
        out.append({"severity": severity, "target": target, "check": check, "message": message})

    title = (copy.get("title") or "").strip()
    taken = {(o.get("title") or "").strip().lower(): o["item"] for o in others if o.get("title")}
    if title.lower() in taken:
        add("blocking", "product.title", "duplicate_title", f"The title '{title}' is already used by {taken[title.lower()]}.")

    name_words = set(content_words(subject_name)) | {w + "s" for w in content_words(subject_name)}
    if subject_name and title and not name_in_title(title, subject_name):
        add("warning", "product.title", "subject_missing_from_title",
            f"The title doesn't name the {subject_name}. Put '{subject_name.title()}' in it so a buyer "
            "searching for it finds this piece.")

    # distinctive title words already in two or more other titles (the subject's name doesn't count)
    counts = {}
    for o in others:
        for w in set(content_words(o.get("title", ""))):
            counts[w] = counts.get(w, 0) + 1
    reused = sorted(w for w in set(content_words(title)) - name_words if counts.get(w, 0) >= 2)
    if reused:
        add("warning", "product.title", "title_word_reused",
            f"Title word{'s' if len(reused) > 1 else ''} {', '.join(repr(w) for w in reused)} already in "
            f"{max(counts[w] for w in reused)} other titles.")
    if title_options and len(title_options) >= 2:
        main = [set(content_words(t)) - name_words for t in title_options]
        shared = sorted(set.intersection(*main)) if all(main) else []
        if shared:
            add("warning", "product.attributes.title_options", "options_share_word",
                f"All title options share {', '.join(repr(w) for w in shared)}: they should take different angles.")

    # watch phrases, by share of the catalog's copy that already uses them. A limit above 0% always
    # allows at least one listing, so a small catalog isn't flagged on a phrase's first use.
    text = _all_text(copy)
    n = len(others)
    for wp in (ctx or {}).get("watch_phrases", []):
        if contains_phrase(text, wp["phrase"]):
            used = sum(1 for o in others if contains_phrase(_all_text(o), wp["phrase"]))
            share = (used + 1) / (n + 1)
            allowed = 0 if wp["max_share"] == 0 else max(1, int(wp["max_share"] * (n + 1)))
            if used + 1 > allowed:
                add("warning", "product.description", "watch_phrase",
                    f"'{wp['phrase']}' would be in {used + 1} of {n + 1} listings ({share:.0%}; limit "
                    f"{wp['max_share']:.0%}).")

    # five words in a row shared with another listing's description
    mine = shingles(copy.get("collector_description", "")) | shingles(copy.get("short_description", ""))
    for o in others:
        theirs = shingles(o.get("collector_description", "")) | shingles(o.get("short_description", ""))
        common = sorted(mine & theirs)
        if common:
            add("warning", "product.description", "shared_phrasing",
                f"Shares the phrase '{common[0]}' with {o['item']}" + (f" (+{len(common) - 1} more)" if len(common) > 1 else "") + ".")

    opening = " ".join(words(copy.get("collector_description", ""))[:3])
    if opening:
        same = [o["item"] for o in others if " ".join(words(o.get("collector_description", ""))[:3]) == opening]
        if same:
            add("warning", "product.description", "same_opening",
                f"Opens with '{opening}', like {', '.join(same[:3])}.")

    if ctx:
        lim = ctx["length"]
        sw, cw = len(words(copy.get("short_description", ""))), len(words(copy.get("collector_description", "")))
        if not lim["short_words"]["min"] <= sw <= lim["short_words"]["max"] or \
                len(copy.get("short_description", "")) > lim["short_chars_max"]:
            add("warning", "product.attributes.short_description", "length",
                f"Short description is {sw} words / {len(copy.get('short_description', ''))} characters "
                f"(target {lim['short_words']['min']}–{lim['short_words']['max']} words, ≤{lim['short_chars_max']} characters).")
        if not lim["collector_words"]["min"] <= cw <= lim["collector_words"]["max"]:
            add("warning", "product.description", "length",
                f"Collector description is {cw} words (target {lim['collector_words']['min']}–{lim['collector_words']['max']}).")
        for w in ctx["style_words"]["reject"]:
            if contains_phrase(text, w):
                add("warning", "product.description", "rejected_style_word", f"Uses '{w}', a style word the owner rejects.")

    for v in voice_findings(copy.get("collector_description", ""), ctx):
        add("warning", "product.description", v["check"], v["message"])

    if self_review:
        total, best = sum(self_review.values()), 2 * len(self_review)
        if total < best - 2:
            low = ", ".join(k for k, v in self_review.items() if v < 2)
            add("warning", "product.description", "self_review", f"Self-review {total}/{best} (below 2: {low}).")
    return out


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s]


def voice_findings(text: str, ctx: Optional[dict] = None) -> List[dict]:
    """The collector-description voice checks (B-060): a routine closing question, stock art-marketing
    phrases, stacked hedges, a catalog-wide meaning restated, and sentences borrowed from the worked
    example. Each is a warning: the reviewer decides."""
    out = []
    if not (text or "").strip():
        return out
    sents = _sentences(text)
    if sents and sents[-1].rstrip().endswith("?"):
        out.append({"check": "closing_question", "message": "The collector description ends on a question. Close "
                    "on a thought or an image unless this question really earns its place."})
    stock = [p for p in STOCK_PHRASES if contains_phrase(text, p)]
    stock = [p for p in stock if not any(p != q and p in q for q in stock)]     # report the longest form only
    if stock:
        out.append({"check": "stock_phrase", "message": "Stock art-marketing phrasing: " +
                    ", ".join(repr(p) for p in stock) + ". Say what this piece does instead."})
    low = (text or "").lower()
    hedges = sum(len(re.findall(r"\b" + re.escape(h) + r"\b", low)) for h in HEDGES)
    if hedges > HEDGE_LIMIT:
        out.append({"check": "hedge_stack", "message": f"{hedges} hedges (perhaps, as if, seems, could be…). One "
                    "or two are enough: trust the reader."})
    for m in (ctx or {}).get("meanings", []):
        if m["scope"]["kind"] != "catalog":
            continue
        # ordinary words ("back", "keeps") overlap by chance; a restatement also names what the meaning is about
        subject = set(content_words(m["subject"]))
        key = set(content_words(m["meaning"])) | subject
        for s in sents:
            hit = key & set(content_words(s))
            if len(hit) >= 3 and hit & subject:
                out.append({"check": "catalog_meaning_restated", "message": "Restates the catalog-wide meaning "
                            f"{m['id']} ({', '.join(sorted(hit))}). It is background for the writer; most listings "
                            "shouldn't mention it."})
                break
    common = sorted(shingles(text) & set().union(*[shingles(e) for e in example_texts()] or [set()]))
    if common:
        out.append({"check": "copies_example", "message": f"Borrows '{common[0]}' from the example in the writing "
                    "standards. The example is for tone, not wording."})
    return out
