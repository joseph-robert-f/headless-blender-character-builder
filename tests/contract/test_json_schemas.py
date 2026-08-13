from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict, Iterable

from shared.build_manifest import MANIFEST_VERSION, REQUIRED_ARTIFACTS
from shared.character_spec import (
    COMPONENT_PRESETS,
    EYE_PRESETS,
    MATERIAL_PRESETS,
    POSES,
    STYLES,
    BuildRequest,
)
from shared.quality_report import QA_VERSION


ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def load_schema(name: str) -> Dict[str, Any]:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def walk_dicts(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


class JsonSchemaContractTests(unittest.TestCase):
    schema_names = (
        "build-request-v1.schema.json",
        "character-spec-v1.schema.json",
        "qa-v1.schema.json",
        "manifest-v1.schema.json",
    )

    def test_all_four_schemas_are_valid_json_and_declare_draft_2020_12(self) -> None:
        for name in self.schema_names:
            with self.subTest(name=name):
                schema = load_schema(name)
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertTrue(schema["$id"].endswith(name))

    def test_every_declared_object_schema_rejects_extra_properties(self) -> None:
        for name in self.schema_names:
            schema = load_schema(name)
            for node in walk_dicts(schema):
                if node.get("type") == "object":
                    with self.subTest(name=name, title=node.get("title"), keys=list(node.get("properties", {}))):
                        self.assertIs(node.get("additionalProperties"), False)

    def test_build_and_character_schema_match_runtime_versions_limits_and_enums(self) -> None:
        build = load_schema("build-request-v1.schema.json")
        character = load_schema("character-spec-v1.schema.json")
        self.assertEqual(build["properties"]["request_version"]["const"], "build/v1")
        self.assertEqual(build["properties"]["spec"]["$ref"], "character-spec-v1.schema.json")
        self.assertEqual(character["properties"]["spec_version"]["const"], "character/v1")
        self.assertEqual(character["properties"]["name"]["maxLength"], 64)
        self.assertEqual(character["properties"]["slug"]["maxLength"], 48)
        self.assertEqual(character["properties"]["height_mm"]["minimum"], 25)
        self.assertEqual(character["properties"]["height_mm"]["maximum"], 250)
        self.assertEqual(character["properties"]["palette"]["maxItems"], 8)
        self.assertEqual(character["properties"]["components"]["maxItems"], 16)
        self.assertEqual(tuple(character["properties"]["style"]["enum"]), STYLES)
        self.assertEqual(tuple(character["properties"]["pose"]["enum"]), POSES)
        self.assertEqual(tuple(character["properties"]["material_preset"]["enum"]), MATERIAL_PRESETS)
        self.assertEqual(tuple(character["properties"]["eye_preset"]["enum"]), EYE_PRESETS)
        self.assertEqual(tuple(character["properties"]["components"]["items"]["enum"]), COMPONENT_PRESETS)

    def test_base_schema_records_none_and_non_none_conditional_limits(self) -> None:
        base = load_schema("character-spec-v1.schema.json")["properties"]["base"]
        conditional = base["allOf"][0]
        self.assertEqual(conditional["if"]["properties"]["preset"]["const"], "none")
        self.assertEqual(conditional["then"]["properties"]["width_mm"]["const"], 0)
        self.assertEqual(conditional["then"]["properties"]["height_mm"]["const"], 0)
        self.assertEqual(conditional["else"]["properties"]["width_mm"]["minimum"], 20)
        self.assertEqual(conditional["else"]["properties"]["height_mm"]["minimum"], 2)
        self.assertEqual(base["default"], {"preset": "round", "width_mm": 48, "depth_mm": 48, "height_mm": 5})

    def test_examples_validate_and_only_use_schema_declared_fields(self) -> None:
        build = load_schema("build-request-v1.schema.json")
        character = load_schema("character-spec-v1.schema.json")
        outer_fields = set(build["properties"])
        spec_fields = set(character["properties"])
        examples = sorted((ROOT / "examples" / "requests").glob("*.json"))
        self.assertEqual(
            [path.name for path in examples],
            ["facet-bot-tidepool.json", "facet-bot.json", "moss-hopper.json"],
        )
        for path in examples:
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertLessEqual(set(raw), outer_fields)
            self.assertLessEqual(set(raw["spec"]), spec_fields)
            BuildRequest.from_json(path.read_bytes())

    def test_qa_schema_has_explicit_version_nullable_evidence_and_mapping_note(self) -> None:
        qa = load_schema("qa-v1.schema.json")
        self.assertEqual(qa["properties"]["qa_version"]["const"], QA_VERSION)
        self.assertIn("needs_review", qa["properties"]["status"]["enum"])
        self.assertIn("exit 11", qa["$comment"])
        self.assertIn("no success manifest", qa["$comment"])
        self.assertIn("max(0.2 mm, 0.5%)", qa["$comment"])
        nullable_dimensions = qa["$defs"]["nullableDimensions"]
        vector = nullable_dimensions["oneOf"][1]
        self.assertEqual(vector["minItems"], 3)
        self.assertEqual(vector["maxItems"], 3)
        self.assertEqual(vector["items"]["type"], "number")
        self.assertEqual(vector["items"]["minimum"], 0.001)
        passed_rule = qa["allOf"][0]
        passed_measurements = passed_rule["then"]["properties"]["measurements"]["properties"]
        self.assertEqual(passed_measurements["triangle_count"]["minimum"], 4)
        self.assertEqual(passed_measurements["triangle_count"]["maximum"], 500000)

    def test_manifest_schema_has_explicit_version_and_exact_artifacts(self) -> None:
        manifest = load_schema("manifest-v1.schema.json")
        self.assertEqual(manifest["properties"]["manifest_version"]["const"], MANIFEST_VERSION)
        artifacts = manifest["properties"]["artifacts"]
        self.assertEqual(tuple(artifacts["required"]), REQUIRED_ARTIFACTS)
        self.assertEqual(set(artifacts["properties"]), set(REQUIRED_ARTIFACTS))
        self.assertNotIn("manifest.json", artifacts["properties"])
        self.assertEqual(manifest["properties"]["qa"]["properties"]["status"]["const"], "passed")
        self.assertEqual(manifest["$defs"]["dimensions"]["items"]["minimum"], 0.001)
        self.assertIn(" ", manifest["properties"]["execution"]["properties"]["blender_version"]["pattern"])


if __name__ == "__main__":
    unittest.main()
