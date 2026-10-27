"""Commerce OS policy (B-043): one place that decides whether a contract document is acceptable.

    from packages.policy import validate
    violations = validate(doc, related=[change_set])

`validate` runs the document's JSON Schema (packages/contracts/schemas) and then the semantic rules the
schemas can't express (semantics.py). The workflow service calls it at every stage boundary. Agents
never decide acceptance themselves.
"""
from pathlib import Path
from typing import Iterable, List, Optional

from packages.contracts.validator import Registry
from packages.policy.approvals import APPROVAL_BINDINGS, binding_violations, self_approval  # noqa: F401
from packages.policy.semantics import load_product_types, semantic_violations  # noqa: F401
from packages.policy.violations import Violation

SCHEMAS = Path(__file__).resolve().parents[1] / "contracts" / "schemas"
_REGISTRY = None


def registry() -> Registry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = Registry(SCHEMAS)
    return _REGISTRY


def schema_violations(doc: dict) -> List[Violation]:
    kind = doc.get("contract") if isinstance(doc, dict) else None
    name = f"{kind}.schema.json"
    if not kind or name not in registry().schemas or kind == "common":
        return [Violation("unknown_contract", "contract", f"not a known contract document: {kind!r}")]
    return [Violation("schema", "", e) for e in registry().validate(doc, name)]


def validate(doc: dict, related: Iterable[dict] = (), product_types: Optional[dict] = None,
             expected: Optional[str] = None) -> List[Violation]:
    """Schema first; semantic rules only run on a structurally valid document.

    `expected` is the contract the caller is waiting for at this stage (e.g. "change-set"). A document
    claiming to be something else is refused outright rather than validated as what it claims to be.
    """
    if expected is not None:
        kind = doc.get("contract") if isinstance(doc, dict) else None
        if kind != expected:
            return [Violation("wrong_contract", "contract", f"expected a {expected} document, got {kind!r}")]
    errors = schema_violations(doc)
    if errors:
        return errors
    return semantic_violations(doc, related, product_types)
