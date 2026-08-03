"""Cross-check the bundled validator against a reference implementation.

`hbcb.validate` is a hand-written subset validator, which exists so the same
code can run inside Blender's bundled Python. That is a real risk: a subset
validator can quietly disagree with the JSON Schema the repository publishes.

When the `jsonschema` package is installed -- it is in the `dev` extra and in
CI -- these tests hold the two implementations against each other. Without it
they skip rather than giving false assurance.
"""

import glob
import json
import os
import unittest

from hbcb import spec
from hbcb.validate import SchemaError

try:
    import jsonschema
except ImportError:
    jsonschema = None

EXAMPLES = os.path.join(spec.REPO_ROOT, "examples", "requests")
REJECTED = os.path.join(spec.REPO_ROOT, "examples", "rejected")


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


@unittest.skipIf(jsonschema is None, "jsonschema is not installed")
class ReferenceComparisonTests(unittest.TestCase):
    def setUp(self):
        self.request_schema = _load(os.path.join(spec.SCHEMA_DIR, spec.REQUEST_SCHEMA))
        self.character_schema = _load(os.path.join(spec.SCHEMA_DIR, spec.SPEC_SCHEMA))
        # The request schema points at the character schema with a sibling-file
        # $ref. Splicing it in beats configuring a resolver: the reference
        # library's resolver API has changed twice, and this test should be
        # about the schemas, not about jsonschema's plumbing.
        self.combined = dict(self.request_schema)
        self.combined["properties"] = dict(self.request_schema["properties"])
        self.combined["properties"]["spec"] = self.character_schema

    def _reference_validate(self, document):
        jsonschema.validate(
            instance=document,
            schema=self.combined,
            cls=jsonschema.Draft202012Validator,
        )

    def test_schemas_are_themselves_valid(self):
        for name in os.listdir(spec.SCHEMA_DIR):
            if name.endswith(".json"):
                with self.subTest(schema=name):
                    jsonschema.Draft202012Validator.check_schema(
                        _load(os.path.join(spec.SCHEMA_DIR, name))
                    )

    def test_both_validators_accept_every_example(self):
        paths = sorted(glob.glob(os.path.join(EXAMPLES, "*.json")))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(example=os.path.basename(path)):
                document = _load(path)
                self._reference_validate(document)
                spec.store().validate(spec.REQUEST_SCHEMA, document)

    def test_both_validators_reject_the_same_fixtures(self):
        """A fixture the reference rejects must not slip past the bundled one."""
        for path in sorted(glob.glob(os.path.join(REJECTED, "*.json"))):
            name = os.path.basename(path)
            document = _load(path)

            reference_rejected = False
            try:
                self._reference_validate(document)
            except jsonschema.ValidationError:
                reference_rejected = True

            bundled_rejected = False
            try:
                spec.store().validate(spec.REQUEST_SCHEMA, document)
            except SchemaError:
                bundled_rejected = True

            with self.subTest(fixture=name):
                if reference_rejected:
                    self.assertTrue(
                        bundled_rejected,
                        "%s is rejected by jsonschema but accepted by hbcb.validate" % name,
                    )
                # The converse is allowed: some fixtures (a contradictory print
                # profile, for instance) are schema-valid and rejected later by
                # policy, which JSON Schema cannot express.


if __name__ == "__main__":
    unittest.main()
