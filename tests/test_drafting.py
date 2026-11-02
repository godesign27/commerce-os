"""packages/drafting (B-055, B-056): the listing request, the claim check, and the canonical-draft mapping.

No network: `call_model` is exercised with a stand-in client. Image tests need Pillow.
"""
import copy
import importlib.util
import json
import unittest
from types import SimpleNamespace

from packages.drafting import listing
from packages.policy import load_product_types
from tests._helpers import REPO, load_json

TYPES = load_product_types()
TAGS = ["Abstract", "Animals", "Landscape"]
HAS_PIL = importlib.util.find_spec("PIL") is not None
CTX = load_json(REPO / "tests" / "fixtures" / "contracts" / "valid" / "brand-context.generic-artist.json")
MEANINGS = [m for m in CTX["meanings"] if m["scope"]["kind"] == "catalog"]

CLEAN = {
    "product_type": {"id": "artwork", "confidence": 0.94, "runner_up": "none", "reason": "a framed picture"},
    "category": {"id": "birds", "confidence": 0.9},
    "moment": {"text": "A heron holds still before the strike.", "basis": "proposed", "meaning_ids": []},
    "title_options": [{"title": "Low Tide Watch", "angle": "the moment", "rationale": "the pause"},
                      {"title": "Grey Patience", "angle": "the quality", "rationale": "stillness"},
                      {"title": "One Leg Down", "angle": "a detail", "rationale": "the stance"}],
    "recommended_title": "Low Tide Watch",
    "recommendation_reason": "It names the pause without explaining it.",
    "short_description": "A grey heron stands on one leg at the water's edge, neck folded, waiting for the moment to "
                         "come to it.",
    "collector_description": " ".join(["The heron has stopped mid-step and everything waits with it."] * 9),
    "store_tags": {"existing": ["Animals", "Not a store tag"], "proposed": ["Heron", " water birds "]},
    "search_keywords": ["heron painting", "Heron Painting", "bird art", "coastal wall art"],
    "subject": "heron, side view", "subject_name": "", "dominant_colors": ["grey", "ochre", "blue"],
    "observations": ["a grey heron on one leg", "a pale ochre ground"],
    "interpretations": [{"statement": "the pause reads as patience", "basis": "proposed", "meaning_id": ""}],
    "ask_artist": ["What does the heron stand for here?"],
    "orientation": {"signature_corner": "bottom_right", "rotate_clockwise": "0", "confidence": 0.7},
    "self_review": {"brand_alignment": 2, "visual_specificity": 2, "interpretive_restraint": 2,
                    "distinctiveness": 2, "collector_appeal": 2, "human_story": 2, "catalog_readiness": 2},
    "uncertain": ["the medium"],
}


def draft(output=None, **kw):
    kw.setdefault("brand_ctx", CTX)
    kw.setdefault("meanings", MEANINGS)
    return listing.to_canonical_draft(output or CLEAN, item_id="img-1-abc", file_id="file-img-1",
                                      product_types=TYPES, model=listing.MODEL, store_tags=TAGS, **kw)


def codes(d, severity=None):
    return [i["question"] for i in d["review_issues"] if severity in (None, i["severity"])]


class Request(unittest.TestCase):
    def setUp(self):
        self.req = listing.build_request(b"\xff\xd8jpeg", "image/jpeg", TYPES, TAGS, brand_ctx=CTX, meanings=MEANINGS,
                                         others=[{"item": "x", "title": "Harbour Light", "collector_description": "Light falls."}])

    def test_uses_the_default_model_with_fallbacks(self):
        self.assertEqual(self.req["model"], "claude-opus-5-5")
        self.assertEqual(self.req["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", self.req["betas"])

    def test_structured_output_and_effort(self):
        oc = self.req["output_config"]
        self.assertEqual(oc["format"]["type"], "json_schema")
        self.assertIn(oc["effort"], ("low", "medium", "high"))
        for banned in ("temperature", "top_p", "top_k", "thinking"):
            self.assertNotIn(banned, self.req)

    def test_system_prompt_is_cached_and_stable(self):
        self.assertEqual(self.req["system"][-1]["cache_control"], {"type": "ephemeral"})
        again = listing.build_request(b"other", "image/jpeg", TYPES, TAGS, brand_ctx=CTX, meanings=[], note="different")
        self.assertEqual(again["system"], self.req["system"], "per-piece inputs must stay out of the cached prefix")

    def test_system_carries_the_skill_standards_and_the_brand_context(self):
        system = "\n".join(b["text"] for b in self.req["system"])
        standards = (REPO / "plugins/commerce-os/skills/listing-copy/references/writing-standards.md").read_text()
        self.assertIn(standards, system, "the service reads the skill's own writing standards")
        self.assertIn("Sample Artist", system)
        self.assertIn("Prefer one strong verb", system, "approved lessons reach the prompt")

    def test_unapproved_lessons_and_examples_stay_out(self):
        ctx = copy.deepcopy(CTX)
        ctx["lessons"][0]["status"] = "proposed"
        ctx["examples"][0]["status"] = "proposed"
        system = "\n".join(b["text"] for b in listing.build_request(b"x", "image/jpeg", TYPES, TAGS, brand_ctx=ctx)["system"])
        self.assertNotIn("Prefer one strong verb", system)
        self.assertNotIn("Low Tide Watch", system)

    def test_image_comes_before_the_piece_context_and_memory(self):
        content = self.req["messages"][0]["content"]
        self.assertEqual([c["type"] for c in content], ["image", "text"])
        self.assertIn("Abstract", content[1]["text"])
        self.assertIn("Harbour Light", content[1]["text"], "titles already taken are in the catalog memory")
        self.assertIn("mean-2", content[1]["text"], "meanings in scope are listed with their IDs")

    def test_prompt_forbids_unsupported_claims(self):
        for phrase in ("Never state the medium", "Never claim it is handmade, original", "Describe only what is visible"):
            self.assertIn(phrase, listing.SYSTEM)

    def test_schema_is_strict(self):
        def walk(node, path="$"):
            if isinstance(node, dict) and node.get("type") == "object":
                self.assertIs(node.get("additionalProperties"), False, path)
                self.assertEqual(set(node["required"]), set(node["properties"]), path)
                for k, v in node["properties"].items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, dict) and node.get("type") == "array":
                walk(node["items"], path + "[]")
        schema = self.req["output_config"]["format"]["schema"]
        walk(schema)
        self.assertEqual(set(schema["properties"]["product_type"]["properties"]["id"]["enum"]), set(TYPES))
        self.assertEqual(schema["properties"]["store_tags"]["properties"]["existing"]["items"]["enum"], TAGS)
        self.assertEqual(schema["properties"]["category"]["properties"]["id"]["enum"], ["still-life", "birds", "other"])


class ClaimCheck(unittest.TestCase):
    def test_clean_copy_passes(self):
        for k in ("recommended_title", "short_description", "collector_description"):
            self.assertEqual(listing.claim_violations(CLEAN[k]), [], k)

    def test_catches_unsupported_claims(self):
        for text, kind in (("A handmade lion", "making"), ("An original painting", "authenticity"),
                           ("Acrylic on canvas", "medium"), ("Limited edition of 20", "authenticity"),
                           ("Measures 16 x 20", "size"), ("12 in wide", "size"), ("Premium print", "quality")):
            with self.subTest(text=text):
                self.assertTrue(any(v.startswith(kind) for v in listing.claim_violations(text)), text)

    def test_whole_words_only(self):
        self.assertEqual(listing.claim_violations("Originally a sketch of an inky sky"), [])

    def test_supplied_facts_allow_their_own_words(self):
        self.assertEqual(listing.claim_violations("An original acrylic on canvas, 16 x 20 in",
                                                  {"edition": "original", "medium": "acrylic on canvas",
                                                   "dimensions": "16 x 20 in"}), [])
        self.assertTrue(listing.claim_violations("An original", {"edition": "print"}), "a print isn't an original")
        self.assertTrue(listing.claim_violations("watercolor", {"medium": "acrylic"}), "only the supplied medium")


class Mapping(unittest.TestCase):
    def test_clean_draft_passes_the_policy(self):
        self.assertEqual([str(v) for v in listing.check_draft(draft())], [])

    def test_copy_is_inferred_and_cites_the_image(self):
        title = draft()["product"]["title"]
        self.assertEqual(title["value"], "Low Tide Watch")
        self.assertEqual(title["status"], "inferred")
        self.assertEqual(title["evidence"], [{"kind": "asset", "ref": "file-img-1"}])
        self.assertIn("claude-opus-5-5", title["method"])

    def test_commercial_facts_are_never_drafted(self):
        d = draft()
        for k in ("material", "dimensions"):
            self.assertEqual(d["product"][k], {"value": None, "status": "unknown", "evidence": []})
        self.assertTrue(all(v["sku"]["status"] == "unknown" for v in d["variants"]))
        blocking = " ".join(codes(d, "blocking"))
        self.assertIn("medium", blocking)
        self.assertIn("dimensions", blocking)

    def test_supplied_facts_are_supplied_and_clear_their_blockers(self):
        d = draft(facts={"medium": "acrylic on canvas", "dimensions": "16x20", "edition": "original"})
        self.assertEqual(d["product"]["material"]["status"], "supplied")
        self.assertEqual(d["product"]["dimensions"]["value"], {"width": 16.0, "height": 20.0, "unit": "in"})
        self.assertEqual(d["product"]["attributes"]["edition"]["value"], "original")
        self.assertEqual(codes(d, "blocking"), [])
        self.assertEqual([str(v) for v in listing.check_draft(d)], [])

    def test_unreadable_dimensions_stay_blocking(self):
        self.assertIn("16 x 20 in", " ".join(codes(draft(facts={"dimensions": "about a metre"}), "blocking")))

    def test_unsupported_claims_become_blocking_issues(self):
        bad = copy.deepcopy(CLEAN)
        bad["collector_description"] = "A hand-painted original on canvas."
        blocking = " ".join(codes(draft(bad), "blocking"))
        for word in ("hand-painted", "original", "canvas"):
            self.assertIn(word, blocking)

    def test_a_confirmed_reading_must_cite_a_meaning_in_scope(self):
        o = copy.deepcopy(CLEAN)
        o["interpretations"] = [{"statement": "the heron is patience", "basis": "confirmed", "meaning_id": "mean-1"},
                                {"statement": "the ground is weather", "basis": "confirmed", "meaning_id": "mean-2"}]
        attrs = draft(o)["product"]["attributes"]["interpretations"]["value"]
        self.assertEqual(attrs[0]["basis"], "proposed", "mean-1 is a series meaning, not in scope here")
        self.assertEqual(attrs[1], {"statement": "the ground is weather", "basis": "confirmed", "meaning_id": "mean-2"})
        self.assertIn("Treated as proposed", " ".join(codes(draft(o), "warning")))

    def test_proposed_readings_and_questions_reach_the_reviewer(self):
        notes = " ".join(codes(draft(), "note"))
        self.assertIn("Proposed reading", notes)
        self.assertIn("What does the heron stand for here?", notes)

    def test_three_options_and_the_recommendation_is_one_of_them(self):
        o = copy.deepcopy(CLEAN)
        o["recommended_title"] = "Something Else"
        self.assertIn("not one of the three options", " ".join(codes(draft(o), "warning")))
        o["title_options"] = o["title_options"][:2]
        self.assertIn("Expected three title options", " ".join(codes(draft(o), "warning")))

    def test_only_store_tags_are_suggested_and_keywords_deduplicated(self):
        attrs = draft()["product"]["attributes"]
        self.assertEqual(attrs["suggested_tags"]["value"], ["Animals"])
        self.assertEqual(attrs["proposed_new_tags"]["value"], ["heron", "water birds"])
        self.assertEqual(attrs["search_keywords"]["value"], ["heron painting", "bird art", "coastal wall art"])

    def test_repetition_checks_run_against_the_catalog(self):
        others = [{"item": "b", "title": "Low Tide Watch", "short_description": "", "collector_description": ""}]
        self.assertIn("already used", " ".join(codes(draft(others=others), "blocking")))

    def test_unknown_category_becomes_other(self):
        o = copy.deepcopy(CLEAN)
        o["category"]["id"] = "dragons"
        self.assertEqual(draft(o)["product"]["attributes"]["category"]["value"], "other")

    def test_low_confidence_and_rotation_are_flagged(self):
        o = copy.deepcopy(CLEAN)
        o["product_type"]["confidence"] = 0.4
        o["orientation"] = {"signature_corner": "top_left", "rotate_clockwise": "180", "confidence": 0.8}
        d = draft(o)
        warnings = " ".join(codes(d, "warning"))
        self.assertIn("40%", warnings)
        self.assertIn("rotate 180", warnings)
        self.assertEqual(d["product"]["attributes"]["upright_rotation"]["value"], 180)

    def test_drafts_are_simulated_and_record_versions(self):
        d = draft()
        self.assertIs(d["simulated"], True)
        self.assertEqual(d["policy_versions"]["prompt"], listing.PROMPT_VERSION)
        self.assertEqual(d["policy_versions"]["evidence_policy"], listing.EVIDENCE_POLICY)
        self.assertEqual(d["policy_versions"]["brand_context"], "storefront-a@3")

    def test_no_brand_context_is_a_warning_not_a_failure(self):
        d = draft(brand_ctx=None, meanings=[])
        self.assertIn("No brand context", " ".join(codes(d, "warning")))
        self.assertNotIn("brand_context", d["policy_versions"])

    def test_no_signature_is_unknown_not_guessed(self):
        o = copy.deepcopy(CLEAN)
        o["orientation"]["signature_corner"] = "none"
        self.assertEqual(draft(o)["product"]["attributes"]["signature_corner"]["status"], "unknown")


def fake_response(stop="end_turn", text=None, **extra):
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(stop_reason=stop, content=content, model="claude-opus-5-5", _request_id="req_1",
                           usage=SimpleNamespace(input_tokens=1800, output_tokens=600, cache_read_input_tokens=0,
                                                 cache_creation_input_tokens=0), **extra)


class FakeClient:
    def __init__(self, response):
        self.response, self.calls = response, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        return self.response


@unittest.skipUnless(importlib.util.find_spec("anthropic"), "anthropic SDK not installed (use the project .venv)")
class CallModel(unittest.TestCase):
    def test_parses_the_json_and_usage(self):
        client = FakeClient(fake_response(text=json.dumps(CLEAN)))
        result = listing.call_model(client, {"model": listing.MODEL})
        self.assertEqual(result["output"]["recommended_title"], CLEAN["recommended_title"])
        self.assertEqual(result["usage"]["input_tokens"], 1800)
        self.assertGreater(listing.estimate_cost(result["usage"]), 0)

    def test_refusal_truncation_and_bad_json_are_errors(self):
        # a refusal can still carry text; it must never be read as a draft
        for resp in (fake_response("refusal", text=json.dumps(CLEAN), stop_details=SimpleNamespace(category="bio")),
                     fake_response("max_tokens", text="{"), fake_response(text="not json"), fake_response()):
            with self.subTest(stop=resp.stop_reason):
                with self.assertRaises(listing.ModelError):
                    listing.call_model(FakeClient(resp), {})


@unittest.skipUnless(HAS_PIL, "Pillow not installed (use the project .venv)")
class Images(unittest.TestCase):
    def test_images_are_downscaled_jpeg(self):
        import io
        import tempfile
        from pathlib import Path
        from PIL import Image
        path = Path(tempfile.mkdtemp()) / "big.png"
        Image.new("RGB", (4000, 3000), (10, 20, 30)).save(path)
        data, media = listing.encode_image(path)
        self.assertEqual(media, "image/jpeg")
        self.assertEqual(max(Image.open(io.BytesIO(data)).size), listing.IMAGE_LONG_EDGE)


class Script(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("draft_listings", REPO / "scripts" / "draft_listings.py")
        self.dl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.dl)

    def test_candidates_skip_rejected_and_imageless_items(self):
        items = [{"id": "a", "art_file": "x"}, {"id": "b", "art_file": "x"}, {"id": "c"}]
        picked = self.dl.candidates(items, {"b": {"decision": "reject"}}, redo=True)
        self.assertEqual([i["id"] for i in picked], ["a"])

    def test_key_is_never_hardcoded(self):
        text = (REPO / "scripts" / "draft_listings.py").read_text()
        self.assertNotIn("sk-ant-a", text)


if __name__ == "__main__":
    unittest.main()
