from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from tests.support import passed_qa_report, valid_manifest


ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def load_schema(name: str) -> Dict[str, Any]:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


class Draft202012RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas = {
            name: load_schema(name)
            for name in (
                "build-request-v1.schema.json",
                "character-spec-v1.schema.json",
                "qa-v1.schema.json",
                "manifest-v1.schema.json",
            )
        }
        resources = [
            (schema["$id"], Resource.from_contents(schema))
            for schema in cls.schemas.values()
        ]
        cls.registry = Registry().with_resources(resources)
        cls.validators = {}
        for name, schema in cls.schemas.items():
            Draft202012Validator.check_schema(schema)
            cls.validators[name] = Draft202012Validator(
                schema,
                registry=cls.registry,
            )

    def test_examples_resolve_local_character_spec_ref_and_validate(self) -> None:
        validator = self.validators["build-request-v1.schema.json"]
        examples = sorted((ROOT / "examples" / "requests").glob("*.json"))
        self.assertEqual(
            [path.name for path in examples],
            ["facet-bot-tidepool.json", "facet-bot.json", "moss-hopper.json"],
        )
        for path in examples:
            with self.subTest(path=path.name):
                validator.validate(json.loads(path.read_text(encoding="utf-8")))

    def test_valid_quality_report_and_manifest_validate(self) -> None:
        self.validators["qa-v1.schema.json"].validate(passed_qa_report())
        self.validators["manifest-v1.schema.json"].validate(valid_manifest())

    def test_schema_rejects_hostile_extra_fields_and_policy_violations(self) -> None:
        build_validator = self.validators["build-request-v1.schema.json"]
        for name in (
            "outer-extra-property.json",
            "path-field.json",
            "url-field.json",
            "code-field.json",
            "blender-flags.json",
            "nested-extra-property.json",
            "duplicate-items.json",
            "mutually-exclusive-tails.json",
            "unsafe-slug.json",
        ):
            instance = json.loads(
                (ROOT / "tests" / "fixtures" / "rejected" / name).read_text(
                    encoding="utf-8"
                )
            )
            with self.subTest(name=name), self.assertRaises(ValidationError):
                build_validator.validate(instance)

        out_of_range = json.loads(
            (ROOT / "examples" / "requests" / "facet-bot.json").read_text(
                encoding="utf-8"
            )
        )
        out_of_range["spec"]["height_mm"] = 251
        with self.assertRaises(ValidationError):
            build_validator.validate(out_of_range)

    def test_passed_quality_report_requires_measurable_passing_evidence(self) -> None:
        validator = self.validators["qa-v1.schema.json"]
        mutations = []

        null_wall = passed_qa_report()
        null_wall["measurements"]["minimum_wall_mm"] = None
        mutations.append(null_wall)

        false_manifold = passed_qa_report()
        false_manifold["checks"]["manifold"] = False
        mutations.append(false_manifold)

        too_many_triangles = passed_qa_report()
        too_many_triangles["measurements"]["triangle_count"] = 500_001
        mutations.append(too_many_triangles)

        impossible_shell = passed_qa_report()
        impossible_shell["measurements"]["triangle_count"] = 3
        mutations.append(impossible_shell)

        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                validator.validate(mutation)

    def test_native_and_container_manifest_conditionals_validate(self) -> None:
        validator = self.validators["manifest-v1.schema.json"]
        native = valid_manifest()
        validator.validate(native)

        container = copy.deepcopy(native)
        container["execution"].update(
            {
                "mode": "container",
                "worker_image_reference": "headless-blender-character-builder:dev",
                "worker_image_digest": "sha256:" + "1" * 64,
                "worker_image_id": None,
            }
        )
        validator.validate(container)

        invalid_native = copy.deepcopy(native)
        invalid_native["execution"]["worker_image_reference"] = "image:tag"
        with self.assertRaises(ValidationError):
            validator.validate(invalid_native)

    def test_bounded_string_patterns_reject_trailing_line_terminators(self) -> None:
        build_validator = self.validators["build-request-v1.schema.json"]
        request = json.loads(
            (ROOT / "examples" / "requests" / "facet-bot.json").read_text(
                encoding="utf-8"
            )
        )
        request["spec"]["name"] += "\n"
        with self.assertRaises(ValidationError):
            build_validator.validate(request)

        qa = passed_qa_report()
        qa["notes"] = ["unexpected newline\n"]
        with self.assertRaises(ValidationError):
            self.validators["qa-v1.schema.json"].validate(qa)

        manifest = valid_manifest()
        manifest["request_sha256"] += "\n"
        with self.assertRaises(ValidationError):
            self.validators["manifest-v1.schema.json"].validate(manifest)


if __name__ == "__main__":
    unittest.main()
