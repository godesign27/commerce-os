"""A strict JSON Schema (draft 2020-12) validator for exactly the keywords the contracts use. Stdlib only.

Used by packages/policy at runtime and by the test suite. It is strict by construction: `SUPPORTED`
lists the keywords it implements, and tests/test_contracts.py fails if any schema uses another, so a
keyword is never silently ignored. The TypeScript dashboard validates the same schemas with Ajv. If the
Python backend later takes on dependencies, the `jsonschema` library can replace this without changing
any schema (B-043).
"""
import json
import re
from pathlib import Path

SUPPORTED = {
    "$schema", "$id", "$ref", "$defs", "title", "description",
    "type", "enum", "const", "properties", "required", "additionalProperties",
    "items", "minItems", "uniqueItems", "contains", "minProperties",
    "minimum", "maximum", "minLength", "pattern",
    "allOf", "anyOf", "if", "then", "not",
}
TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _equal(a, b):
    # JSON equality: 1 == True must not hold.
    return type(a) is type(b) and a == b if isinstance(a, bool) or isinstance(b, bool) else a == b


class Registry:
    def __init__(self, schema_dir: Path):
        self.schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in Path(schema_dir).glob("*.schema.json")}

    def resolve(self, ref: str, base: str):
        file, _, pointer = ref.partition("#")
        doc_name = file or base
        node = self.schemas[doc_name]
        for part in [p for p in pointer.split("/") if p]:
            node = node[part]
        return node, doc_name

    def validate(self, instance, schema_name: str) -> list:
        errors = []
        self._check(instance, self.schemas[schema_name], schema_name, "$", errors)
        return errors

    def is_valid(self, instance, schema, base) -> bool:
        errs = []
        self._check(instance, schema, base, "$", errs)
        return not errs

    def _check(self, v, s, base, path, errors):
        if s is True or s == {}:
            return
        if s is False:
            errors.append(f"{path}: not allowed")
            return
        if "$ref" in s:
            target, doc = self.resolve(s["$ref"], base)
            self._check(v, target, doc, path, errors)
        if "type" in s:
            types = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(TYPES[t](v) for t in types):
                errors.append(f"{path}: expected {'/'.join(types)}")
                return
        if "const" in s and not _equal(v, s["const"]):
            errors.append(f"{path}: must equal {s['const']!r}")
        if "enum" in s and not any(_equal(v, e) for e in s["enum"]):
            errors.append(f"{path}: {v!r} not one of {s['enum']}")
        if isinstance(v, str):
            if len(v) < s.get("minLength", 0):
                errors.append(f"{path}: shorter than {s['minLength']}")
            if "pattern" in s and not re.search(s["pattern"], v):
                errors.append(f"{path}: does not match {s['pattern']}")
        if TYPES["number"](v):
            if "minimum" in s and v < s["minimum"]:
                errors.append(f"{path}: below minimum {s['minimum']}")
            if "maximum" in s and v > s["maximum"]:
                errors.append(f"{path}: above maximum {s['maximum']}")
        if isinstance(v, dict):
            for key in s.get("required", []):
                if key not in v:
                    errors.append(f"{path}: missing required '{key}'")
            if len(v) < s.get("minProperties", 0):
                errors.append(f"{path}: fewer than {s['minProperties']} properties")
            props = s.get("properties", {})
            for key, value in v.items():
                if key in props:
                    self._check(value, props[key], base, f"{path}.{key}", errors)
                elif "additionalProperties" in s:
                    self._check(value, s["additionalProperties"], base, f"{path}.{key}", errors)
        if isinstance(v, list):
            if len(v) < s.get("minItems", 0):
                errors.append(f"{path}: fewer than {s['minItems']} items")
            if s.get("uniqueItems"):
                seen = [json.dumps(x, sort_keys=True) for x in v]
                if len(seen) != len(set(seen)):
                    errors.append(f"{path}: items are not unique")
            if "items" in s:
                for i, item in enumerate(v):
                    self._check(item, s["items"], base, f"{path}[{i}]", errors)
            if "contains" in s and not any(self.is_valid(x, s["contains"], base) for x in v):
                errors.append(f"{path}: no item matches 'contains'")
        for sub in s.get("allOf", []):
            self._check(v, sub, base, path, errors)
        if "anyOf" in s and not any(self.is_valid(v, sub, base) for sub in s["anyOf"]):
            errors.append(f"{path}: matches none of anyOf")
        if "not" in s and self.is_valid(v, s["not"], base):
            errors.append(f"{path}: must not match 'not' schema")
        if "if" in s and "then" in s and self.is_valid(v, s["if"], base):
            self._check(v, s["then"], base, path, errors)


def keywords_used(schema, found=None):
    """Every keyword used anywhere in a schema (property names under `properties`/`$defs` excluded)."""
    found = set() if found is None else found
    if isinstance(schema, dict):
        for k, v in schema.items():
            found.add(k)
            if k in ("properties", "$defs"):
                for sub in v.values():
                    keywords_used(sub, found)
            elif k in ("items", "additionalProperties", "not", "if", "then", "contains"):
                keywords_used(v, found)
            elif k in ("allOf", "anyOf"):
                for sub in v:
                    keywords_used(sub, found)
    return found
