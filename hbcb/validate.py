"""A small JSON Schema validator covering the subset this project's schemas use.

Why not the `jsonschema` package? The same validation has to run inside Blender's
bundled Python, which has no third-party packages and which users must not be
asked to pip-install into. Shipping a dependency-free validator keeps the
"install nothing, run Blender" path honest.

The schema files under `schemas/` remain ordinary JSON Schema 2020-12 documents,
so editors, CI, and other languages can use them with a full implementation.
`tests/unit/test_schema_conformance.py` cross-checks this validator against the
reference `jsonschema` package whenever that package happens to be installed.

Supported keywords: $ref (sibling file), type, const, enum, required,
properties, additionalProperties (false only), minimum, maximum, minLength,
maxLength, pattern, minItems, maxItems, items, default.
"""

import json
import os
import re

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


class SchemaError(Exception):
    """Raised when a document does not satisfy its schema.

    `errors` holds every problem found, not just the first, so a user fixing a
    hand-written request sees the whole list in one run.
    """

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _type_matches(value, expected):
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return _is_number(value)
    py_type = _TYPES.get(expected)
    if py_type is None:
        raise ValueError("unsupported schema type: %r" % (expected,))
    if py_type is dict or py_type is list or py_type is str:
        return isinstance(value, py_type)
    if py_type is bool:
        return isinstance(value, bool)
    return isinstance(value, py_type)


def _describe(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    return type(value).__name__


class SchemaStore:
    """Loads schema documents from a directory and resolves sibling `$ref`s."""

    def __init__(self, directory):
        self.directory = directory
        self._cache = {}

    def load(self, filename):
        if filename not in self._cache:
            path = os.path.join(self.directory, filename)
            with open(path, encoding="utf-8") as handle:
                self._cache[filename] = json.load(handle)
        return self._cache[filename]

    def resolve(self, schema):
        """Follow a `$ref` to a sibling schema file, if present."""
        seen = set()
        while isinstance(schema, dict) and "$ref" in schema:
            ref = schema["$ref"]
            if ref in seen:
                raise ValueError("circular $ref: %s" % ref)
            seen.add(ref)
            if "/" in ref or ref.startswith("#"):
                raise ValueError("only sibling-file $ref is supported, got %r" % ref)
            schema = self.load(ref)
        return schema

    def validate(self, filename, document):
        """Validate `document`, raising SchemaError with every problem found."""
        errors = []
        self._check(self.load(filename), document, "", errors)
        if errors:
            raise SchemaError(errors)
        return document

    def fill_defaults(self, filename, document):
        """Return a deep copy of `document` with schema defaults applied.

        Defaults are only filled for absent keys, and only inside objects that
        the schema describes. Validate before calling this: filling defaults
        into a malformed document produces confusing results.
        """
        return self._fill(self.load(filename), document)

    # -- internals ---------------------------------------------------------

    def _check(self, schema, value, path, errors):
        schema = self.resolve(schema)
        where = path or "<root>"

        if "const" in schema and value != schema["const"]:
            errors.append("%s: expected %r, got %r" % (where, schema["const"], value))
            return
        if "enum" in schema and value not in schema["enum"]:
            errors.append(
                "%s: %r is not one of %s"
                % (where, value, ", ".join(repr(v) for v in schema["enum"]))
            )
            return
        if "type" in schema:
            expected = schema["type"]
            options = expected if isinstance(expected, list) else [expected]
            if not any(_type_matches(value, option) for option in options):
                errors.append(
                    "%s: expected %s, got %s" % (where, " or ".join(options), _describe(value))
                )
                return

        if _is_number(value):
            self._check_number(schema, value, where, errors)
        elif isinstance(value, str):
            self._check_string(schema, value, where, errors)
        elif isinstance(value, list):
            self._check_array(schema, value, path, where, errors)
        elif isinstance(value, dict):
            self._check_object(schema, value, path, where, errors)

    def _check_number(self, schema, value, where, errors):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append("%s: %s is below the minimum of %s" % (where, value, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append("%s: %s is above the maximum of %s" % (where, value, schema["maximum"]))

    def _check_string(self, schema, value, where, errors):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append("%s: string is shorter than %s characters" % (where, schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append("%s: string is longer than %s characters" % (where, schema["maxLength"]))
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append("%s: %r does not match %s" % (where, value, schema["pattern"]))

    def _check_array(self, schema, value, path, where, errors):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append("%s: needs at least %s items" % (where, schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append("%s: allows at most %s items" % (where, schema["maxItems"]))
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                self._check(item_schema, item, "%s[%d]" % (path, index), errors)

    def _check_object(self, schema, value, path, where, errors):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append("%s: missing required property %r" % (where, key))
        if schema.get("additionalProperties") is False:
            for key in sorted(value):
                if key not in properties:
                    known = ", ".join(sorted(properties)) or "none"
                    errors.append(
                        "%s: unknown property %r is not allowed (known properties: %s)"
                        % (where, key, known)
                    )
        for key, sub_schema in properties.items():
            if key in value:
                self._check(sub_schema, value[key], "%s.%s" % (path, key), errors)

    def _fill(self, schema, value):
        schema = self.resolve(schema)
        if isinstance(value, dict):
            filled = {}
            properties = schema.get("properties", {})
            for key, item in value.items():
                sub = properties.get(key)
                filled[key] = self._fill(sub, item) if sub is not None else item
            for key, sub_schema in properties.items():
                if key in filled:
                    continue
                sub_schema = self.resolve(sub_schema)
                if "default" in sub_schema:
                    # Recurse so an object default like {} still gains its own
                    # nested defaults.
                    filled[key] = self._fill(sub_schema, sub_schema["default"])
            return filled
        if isinstance(value, list):
            item_schema = schema.get("items")
            if item_schema is None:
                return list(value)
            return [self._fill(item_schema, item) for item in value]
        return value
