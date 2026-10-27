"""Contract rules no JSON Schema keyword can express (packages/contracts/README.md, "Rules the schemas can't
express"). Each returns a list of Violations; an empty list means the document passes.
"""
import json
from pathlib import Path
from typing import Iterable, List, Optional

from packages.policy.approvals import binding_violations, self_approval
from packages.policy.violations import Violation

REPO = Path(__file__).resolve().parents[2]
PRODUCT_TYPES_DIR = REPO / "resources" / "product-types"

# Option rules (resources/product-types/README.md) under which a product may define that option.
OPTION_PERMITTED = {
    "color": {"allowed"},
    "size": {"from_tiers", "supplied_only"},
}


def load_product_types(directory: Path = PRODUCT_TYPES_DIR) -> dict:
    return {p.stem: json.loads(p.read_text()) for p in Path(directory).glob("*.json")}


def _products(doc: dict) -> list:
    """Both product-bearing contracts as a list of {option_definitions, variants}."""
    if doc["contract"] == "product-proposal":
        return doc["products"]
    return [{"option_definitions": doc["product"]["option_definitions"], "variants": doc["variants"]}]


def option_violations(doc: dict, product_types: dict) -> List[Violation]:
    out = []
    type_id = doc["product_type"]["id"]
    ptype = product_types.get(type_id)
    if ptype is None:
        return [Violation("unknown_product_type", "product_type.id", f"unknown product type '{type_id}'")]
    for i, product in enumerate(_products(doc)):
        where = f"products[{i}]"
        defs = {}
        for d in product["option_definitions"]:
            key = d["key"]
            rule = ptype["options"].get(key)
            if rule not in OPTION_PERMITTED.get(key, set()):
                out.append(Violation("option_not_allowed", f"{where}.option_definitions.{key}",
                                     f"{key} option not allowed for product type '{type_id}' ({rule or 'undeclared'})"))
            if key in defs:
                out.append(Violation("duplicate_option", f"{where}.option_definitions.{key}",
                                     f"option {key} is defined twice"))
            defs[key] = set(d["values"])
        seen = set()
        for j, variant in enumerate(product["variants"]):
            values = variant["option_values"]
            combo = json.dumps(values, sort_keys=True)
            if combo in seen:
                out.append(Violation("duplicate_option_values", f"{where}.variants[{j}]",
                                     f"duplicate option values {combo}"))
            seen.add(combo)
            for key, value in values.items():
                if key not in defs or value not in defs[key]:
                    out.append(Violation("value_not_defined", f"{where}.variants[{j}].{key}",
                                         f"{key}={value} not in option definition"))
            for key in sorted(set(defs) - set(values)):
                out.append(Violation("option_value_missing", f"{where}.variants[{j}]",
                                     f"variant has no value for option {key}"))
    return out


def grouping_violations(doc: dict) -> List[Violation]:
    ids = [g["file_id"] for g in doc["grouping"]]
    dupes = sorted({f for f in ids if ids.count(f) > 1})
    if dupes:
        return [Violation("grouped_twice", "grouping", f"files grouped more than once: {dupes}")]
    return []


def approval_violations(doc: dict, related: Iterable[dict]) -> List[Violation]:
    out = self_approval(doc)
    for cs in related:
        if cs.get("contract") == "change-set" and cs.get("change_set_id") == doc["change_set_id"]:
            out += binding_violations(doc, cs)
    return out


def semantic_violations(doc: dict, related: Iterable[dict] = (), product_types: Optional[dict] = None) -> List[Violation]:
    """All semantic rules for one document. `related` supplies other documents a rule needs to see
    (an approval's change set). Product types default to resources/product-types/."""
    kind = doc.get("contract")
    related = list(related)
    if kind in ("canonical-draft", "product-proposal"):
        out = option_violations(doc, product_types if product_types is not None else load_product_types())
        if kind == "product-proposal":
            out += grouping_violations(doc)
        return out
    if kind == "approval":
        return approval_violations(doc, related)
    return []
