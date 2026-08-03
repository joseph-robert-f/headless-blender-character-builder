"""Schema, policy, and request-resolution tests.

None of these need Blender, so they are the fast feedback loop and the part of
CI that runs on every push.
"""

import glob
import json
import os
import unittest

from hbcb import layout, presets, print_profiles, spec
from hbcb.exit_codes import INVALID_REQUEST, BuildError
from hbcb.validate import SchemaError

REPO_ROOT = spec.REPO_ROOT
EXAMPLES = os.path.join(REPO_ROOT, "examples", "requests")
REJECTED = os.path.join(REPO_ROOT, "examples", "rejected")


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class ExampleRequestTests(unittest.TestCase):
    def test_every_example_resolves(self):
        paths = sorted(glob.glob(os.path.join(EXAMPLES, "*.json")))
        self.assertTrue(paths, "no example requests found")
        for path in paths:
            with self.subTest(example=os.path.basename(path)):
                request = spec.resolve_file(path)
                self.assertTrue(request.slug)
                self.assertEqual(request.resolved["request_version"], "build/v1")

    def test_examples_match_presets(self):
        """The shipped examples and the built-in presets must not drift apart."""
        for name in presets.names():
            path = os.path.join(EXAMPLES, "%s.json" % name)
            self.assertTrue(os.path.isfile(path), "no example file for preset %r" % name)
            self.assertEqual(load(path)["spec"], presets.get(name)["spec"])

    def test_every_preset_resolves(self):
        for name in presets.names():
            with self.subTest(preset=name):
                request = spec.resolve_preset(name)
                self.assertEqual(request.generator, "geometric-character@1.0.0")


class RejectionTests(unittest.TestCase):
    """Hostile and malformed documents must be refused before Blender starts."""

    def test_every_rejection_fixture_is_rejected(self):
        paths = sorted(glob.glob(os.path.join(REJECTED, "*.json")))
        self.assertTrue(paths, "no rejection fixtures found")
        for path in paths:
            with self.subTest(fixture=os.path.basename(path)):
                with self.assertRaises(BuildError) as caught:
                    spec.resolve_file(path)
                self.assertEqual(caught.exception.code, INVALID_REQUEST)

    def test_unknown_properties_are_named_in_the_error(self):
        with self.assertRaises(BuildError) as caught:
            spec.resolve_file(os.path.join(REJECTED, "unknown-property.json"))
        self.assertIn("blender_args", caught.exception.message)

    def test_request_must_be_an_object(self):
        for value in ([], "string", 42, None):
            with self.subTest(value=value):
                with self.assertRaises(BuildError):
                    spec.resolve(value)

    def test_oversized_request_is_rejected(self):
        import tempfile

        raw = presets.get("facet-bot")
        raw["spec"]["name"] = "x"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            # Pad past the 64 KiB limit with valid JSON.
            handle.write(json.dumps(raw) + " " * (spec.MAX_REQUEST_BYTES + 10))
            path = handle.name
        try:
            with self.assertRaises(BuildError) as caught:
                spec.resolve_file(path)
            self.assertEqual(caught.exception.code, INVALID_REQUEST)
        finally:
            os.unlink(path)

    def test_malformed_json_reports_position(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write('{"request_version": "build/v1",,}')
            path = handle.name
        try:
            with self.assertRaises(BuildError) as caught:
                spec.resolve_file(path)
            self.assertIn("line", caught.exception.message)
        finally:
            os.unlink(path)


class SlugTests(unittest.TestCase):
    def test_slug_cannot_escape_a_directory(self):
        for hostile in ("../../etc/passwd", "..", "/absolute/path", "a/b/c", "C:\\windows"):
            with self.subTest(name=hostile):
                slug = spec.slugify(hostile)
                self.assertNotIn("/", slug)
                self.assertNotIn("\\", slug)
                self.assertNotIn("..", slug)
                self.assertTrue(slug)

    def test_slug_is_bounded(self):
        self.assertLessEqual(len(spec.slugify("x" * 500)), spec.MAX_SLUG_LENGTH)

    def test_slug_never_empty(self):
        self.assertEqual(spec.slugify("!!!"), "character")


class DefaultsTests(unittest.TestCase):
    def test_defaults_are_filled(self):
        request = spec.resolve(
            {
                "request_version": "build/v1",
                "generator": "geometric-character@1.0.0",
                "spec": {
                    "spec_version": "character/v1",
                    "name": "minimal",
                    "style": "geometric",
                    "height_mm": 60,
                },
            }
        )
        self.assertEqual(request.spec["pose"], "standing")
        self.assertEqual(request.spec["features"]["eyes"], "dot")
        self.assertTrue(request.spec["base"]["enabled"])
        self.assertEqual(request.output_profile, "complete-v1")
        self.assertEqual(request.spec["proportions"]["head_scale"], 1.0)

    def test_writing_a_default_explicitly_does_not_change_the_result(self):
        """Two requests that mean the same thing must resolve identically."""
        terse = {
            "request_version": "build/v1",
            "generator": "geometric-character@1.0.0",
            "spec": {
                "spec_version": "character/v1",
                "name": "same",
                "style": "geometric",
                "height_mm": 60,
            },
        }
        verbose = json.loads(json.dumps(terse))
        verbose["spec"]["pose"] = "standing"
        verbose["output_profile"] = "complete-v1"

        first = spec.resolve(terse)
        second = spec.resolve(verbose)
        self.assertEqual(first.resolved_sha256, second.resolved_sha256)
        # The submitted bytes differ, so the raw request hash must differ too.
        self.assertNotEqual(first.request_sha256, second.request_sha256)


class PrintProfileTests(unittest.TestCase):
    def test_all_presets_are_coherent(self):
        for name in print_profiles.PRESETS:
            with self.subTest(profile=name):
                resolved = print_profiles.resolve({"preset": name})
                self.assertGreaterEqual(resolved["min_feature_mm"], resolved["min_wall_mm"])
                self.assertTrue(print_profiles.describe(resolved))

    def test_explicit_fields_override_the_preset(self):
        resolved = print_profiles.resolve({"preset": "fdm-0.6-draft", "min_wall_mm": 2.4})
        self.assertEqual(resolved["min_wall_mm"], 2.4)
        self.assertEqual(resolved["nozzle_mm"], 0.6)

    def test_wall_thinner_than_two_extrusions_is_rejected(self):
        with self.assertRaises(BuildError) as caught:
            print_profiles.resolve(
                {"preset": "custom", "technology": "fdm", "nozzle_mm": 0.8, "min_wall_mm": 0.5}
            )
        self.assertEqual(caught.exception.code, INVALID_REQUEST)

    def test_feature_thinner_than_wall_is_rejected(self):
        with self.assertRaises(BuildError):
            print_profiles.resolve({"preset": "custom", "min_wall_mm": 2.0, "min_feature_mm": 1.0})

    def test_layer_taller_than_nozzle_is_rejected(self):
        with self.assertRaises(BuildError):
            print_profiles.resolve(
                {
                    "preset": "custom",
                    "technology": "fdm",
                    "nozzle_mm": 0.4,
                    "layer_height_mm": 0.5,
                    "min_wall_mm": 1.2,
                }
            )

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(BuildError):
            print_profiles.resolve({"preset": "no-such-profile"})

    def test_resin_profile_needs_no_nozzle(self):
        resolved = print_profiles.resolve({"preset": "resin-standard"})
        self.assertIsNone(resolved["nozzle_mm"])
        self.assertIn("resin", print_profiles.describe(resolved))


class LayoutTests(unittest.TestCase):
    def test_complete_profile_lists_every_artifact(self):
        paths = layout.expected("complete-v1", "diagnostic-v1")
        for required in (
            layout.MODEL_BLEND,
            layout.MODEL_STL,
            layout.MODEL_GLB,
            layout.PREVIEW,
            layout.QA,
            layout.MANIFEST,
        ):
            self.assertIn(required, paths)
        for view in layout.DIAGNOSTIC_VIEWS:
            self.assertIn(layout.diagnostic(view), paths)

    def test_print_only_profile_skips_renders(self):
        paths = layout.expected("print-only-v1", "diagnostic-v1")
        self.assertIn(layout.MODEL_STL, paths)
        self.assertNotIn(layout.PREVIEW, paths)
        self.assertNotIn(layout.MODEL_GLB, paths)

    def test_render_profile_none_skips_renders(self):
        paths = layout.expected("complete-v1", "none")
        self.assertNotIn(layout.PREVIEW, paths)
        self.assertIn(layout.MODEL_GLB, paths)


class SchemaFileTests(unittest.TestCase):
    def test_schemas_reject_extra_properties(self):
        """Every object in the contract must be closed, not just the top level."""
        store = spec.store()
        for filename in (spec.REQUEST_SCHEMA, spec.SPEC_SCHEMA):
            document = store.load(filename)
            self._assert_closed(document, filename, store)

    def _assert_closed(self, schema, where, store):
        schema = store.resolve(schema)
        if schema.get("type") == "object":
            self.assertIs(
                schema.get("additionalProperties"),
                False,
                "%s allows undeclared properties" % where,
            )
            for name, sub in schema.get("properties", {}).items():
                self._assert_closed(sub, "%s.%s" % (where, name), store)

    def test_unsupported_ref_is_refused(self):
        store = spec.store()
        with self.assertRaises(ValueError):
            store.resolve({"$ref": "#/$defs/somewhere"})

    def test_validator_collects_every_error(self):
        store = spec.store()
        with self.assertRaises(SchemaError) as caught:
            store.validate(
                spec.SPEC_SCHEMA,
                {"spec_version": "character/v1", "name": "x", "style": "nope", "height_mm": 9000},
            )
        self.assertGreaterEqual(len(caught.exception.errors), 2)


if __name__ == "__main__":
    unittest.main()
