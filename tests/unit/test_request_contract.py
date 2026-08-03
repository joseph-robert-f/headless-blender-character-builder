from __future__ import annotations

import copy
import json
import math
import unittest
from decimal import Decimal
from pathlib import Path

from shared.character_spec import BuildRequest, validate_build_request
from shared.json_contract import (
    MAX_BUILD_REQUEST_BYTES,
    ContractValidationError,
    canonical_json_bytes,
    canonical_sha256,
    decode_json_document,
)


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "requests"
REJECTED = ROOT / "tests" / "fixtures" / "rejected"


class BuildRequestContractTests(unittest.TestCase):
    def test_both_named_original_examples_validate(self) -> None:
        facet = BuildRequest.from_json((EXAMPLES / "facet-bot.json").read_bytes())
        moss = BuildRequest.from_json((EXAMPLES / "moss-hopper.json").read_bytes())

        self.assertEqual(facet.spec.slug, "facet-bot")
        self.assertEqual(moss.spec.slug, "moss-hopper")
        self.assertNotEqual(facet.request_sha256, moss.request_sha256)

        # The second fixture is intentionally not a palette-only variant.
        self.assertNotEqual(facet.spec.style, moss.spec.style)
        self.assertNotEqual(facet.spec.height_mm, moss.spec.height_mm)
        self.assertNotEqual(facet.spec.pose, moss.spec.pose)
        self.assertNotEqual(facet.spec.palette, moss.spec.palette)
        self.assertNotEqual(facet.spec.proportions, moss.spec.proportions)
        self.assertNotEqual(facet.spec.components, moss.spec.components)
        self.assertNotEqual(facet.spec.base, moss.spec.base)

    def test_plan_shaped_minimal_request_gets_normalized_defaults(self) -> None:
        raw = {
            "request_version": "build/v1",
            "generator": "geometric-character@1.0.0",
            "spec": {
                "spec_version": "character/v1",
                "name": "Facet Bot",
                "style": "geometric",
                "height_mm": 95,
                "pose": "standing",
                "palette": ["#E87532", "#FFF3D6"],
                "proportions": {"head_scale": 1.2, "limb_scale": 0.95},
            },
            "output_profile": "complete-v1",
            "render_profile": "diagnostic-v1",
            "quality_profile": "geometry-v1",
        }
        request = BuildRequest.from_mapping(raw)
        self.assertEqual(request.spec.slug, "facet-bot")
        self.assertEqual(request.spec.proportions.body_scale, Decimal("1"))
        self.assertEqual(request.spec.material_preset, "matte")
        self.assertEqual(request.spec.eye_preset, "round")
        self.assertEqual(request.spec.components, ())
        self.assertEqual(request.spec.base.preset, "round")
        self.assertEqual(request.spec.base.width_mm, Decimal("48"))
        self.assertIsNot(request, validate_build_request(request))

        explicit = copy.deepcopy(raw)
        explicit["spec"].update(
            {
                "slug": "facet-bot",
                "material_preset": "matte",
                "eye_preset": "round",
                "components": [],
                "base": {
                    "preset": "round",
                    "width_mm": 48,
                    "depth_mm": 48,
                    "height_mm": 5,
                },
            }
        )
        explicit["spec"]["proportions"]["body_scale"] = 1
        self.assertEqual(request.request_sha256, BuildRequest.from_mapping(explicit).request_sha256)

    def test_numerically_equivalent_json_has_identical_hashes(self) -> None:
        original = (EXAMPLES / "facet-bot.json").read_text(encoding="utf-8")
        equivalent = original.replace('"height_mm": 95', '"height_mm": 9.5e1')
        equivalent = equivalent.replace('"head_scale": 1.2', '"head_scale": 1.2000')
        equivalent = equivalent.replace('"body_scale": 0.95', '"body_scale": 9.5e-1')
        equivalent = equivalent.replace('"limb_scale": 0.95', '"limb_scale": 0.95000')
        first = BuildRequest.from_json(original)
        second = BuildRequest.from_json(equivalent)
        self.assertEqual(first.canonical_bytes, second.canonical_bytes)
        self.assertEqual(first.request_sha256, second.request_sha256)
        self.assertEqual(first.spec_sha256, second.spec_sha256)
        self.assertIn(b'"head_scale":1.2', first.canonical_bytes)
        self.assertNotIn(b"1.2000", first.canonical_bytes)

    def test_canonical_json_sorts_keys_normalizes_numbers_and_rejects_nonfinite(self) -> None:
        left = {"z": Decimal("1.00"), "a": [Decimal("-0.0"), Decimal("1e-2")]}
        right = {"a": [0, Decimal("0.0100")], "z": 1}
        self.assertEqual(canonical_json_bytes(left), b'{"a":[0,0.01],"z":1}')
        self.assertEqual(canonical_sha256(left), canonical_sha256(right))
        with self.assertRaisesRegex(ContractValidationError, "nonfinite_number"):
            canonical_json_bytes({"bad": math.inf})

    def test_payload_limit_is_applied_to_utf8_bytes_before_parsing(self) -> None:
        raw = (EXAMPLES / "facet-bot.json").read_bytes()
        exactly_max = raw + b" " * (MAX_BUILD_REQUEST_BYTES - len(raw))
        self.assertEqual(len(exactly_max), MAX_BUILD_REQUEST_BYTES)
        BuildRequest.from_json(exactly_max)
        with self.assertRaisesRegex(ContractValidationError, "payload_too_large"):
            BuildRequest.from_json(exactly_max + b" ")

    def test_invalid_utf8_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "invalid_utf8"):
            BuildRequest.from_json(b"{\"request_version\":\xff}")

    def test_all_hostile_fixtures_are_rejected_with_expected_policy_code(self) -> None:
        expected = {
            "outer-extra-property.json": "extra_property",
            "path-field.json": "extra_property",
            "url-field.json": "extra_property",
            "code-field.json": "extra_property",
            "blender-flags.json": "extra_property",
            "nested-extra-property.json": "extra_property",
            "duplicate-key.json": "duplicate_key",
            "nonfinite-number.json": "nonfinite_number",
            "duplicate-items.json": "duplicate_item",
            "unsafe-slug.json": "invalid_slug",
            "extreme-exponent.json": "invalid_number",
        }
        self.assertEqual({path.name for path in REJECTED.glob("*.json")}, set(expected))
        for name, code in expected.items():
            with self.subTest(name=name):
                with self.assertRaises(ContractValidationError) as caught:
                    BuildRequest.from_json((REJECTED / name).read_bytes())
                self.assertEqual(caught.exception.code, code)

    def test_extra_fields_are_rejected_at_every_object_level(self) -> None:
        request = json.loads((EXAMPLES / "facet-bot.json").read_text(encoding="utf-8"))
        mutations = []
        outer = copy.deepcopy(request)
        outer["environment"] = {"HOME": "/tmp"}
        mutations.append(outer)
        spec = copy.deepcopy(request)
        spec["spec"]["shader"] = "arbitrary"
        mutations.append(spec)
        proportions = copy.deepcopy(request)
        proportions["spec"]["proportions"]["driver"] = "expression"
        mutations.append(proportions)
        base = copy.deepcopy(request)
        base["spec"]["base"]["output_path"] = "/tmp/model.stl"
        mutations.append(base)
        for mutation in mutations:
            with self.subTest(keys=mutation.keys()):
                with self.assertRaisesRegex(ContractValidationError, "extra_property"):
                    BuildRequest.from_mapping(mutation)

    def test_component_order_is_canonical_but_duplicates_are_rejected(self) -> None:
        request = json.loads((EXAMPLES / "moss-hopper.json").read_text(encoding="utf-8"))
        reversed_request = copy.deepcopy(request)
        reversed_request["spec"]["components"].reverse()
        self.assertEqual(
            BuildRequest.from_mapping(request).request_sha256,
            BuildRequest.from_mapping(reversed_request).request_sha256,
        )
        request["spec"]["components"].append("backpack")
        with self.assertRaisesRegex(ContractValidationError, "duplicate_item"):
            BuildRequest.from_mapping(request)

    def test_base_conditional_limits_and_normalized_defaults(self) -> None:
        request = json.loads((EXAMPLES / "facet-bot.json").read_text(encoding="utf-8"))
        no_base = copy.deepcopy(request)
        no_base["spec"]["base"] = {
            "preset": "none",
            "width_mm": 0.0,
            "depth_mm": 0e0,
            "height_mm": -0.0,
        }
        model = BuildRequest.from_mapping(no_base)
        self.assertEqual(model.spec.base.to_dict()["width_mm"], Decimal("0.0"))
        self.assertIn(b'"base":{"depth_mm":0,"height_mm":0,"preset":"none","width_mm":0}', model.canonical_bytes)

        nonzero_none = copy.deepcopy(no_base)
        nonzero_none["spec"]["base"]["width_mm"] = 20
        with self.assertRaisesRegex(ContractValidationError, "number_out_of_range"):
            BuildRequest.from_mapping(nonzero_none)

        undersized = copy.deepcopy(request)
        undersized["spec"]["base"]["width_mm"] = 19.99
        with self.assertRaisesRegex(ContractValidationError, "number_out_of_range"):
            BuildRequest.from_mapping(undersized)

    def test_direct_mapping_nonfinite_number_is_rejected(self) -> None:
        request = json.loads((EXAMPLES / "facet-bot.json").read_text(encoding="utf-8"))
        request["spec"]["height_mm"] = float("nan")
        with self.assertRaisesRegex(ContractValidationError, "nonfinite_number"):
            BuildRequest.from_mapping(request)

    def test_pathological_numbers_and_mixed_mapping_keys_have_bounded_errors(self) -> None:
        with self.assertRaises(ContractValidationError) as caught:
            canonical_json_bytes({"small": Decimal("1e-100000")})
        self.assertEqual(caught.exception.code, "numeric_limit")
        with self.assertRaises(ContractValidationError) as caught:
            canonical_json_bytes({"safe": 1, 2: "not-a-json-key"})
        self.assertEqual(caught.exception.code, "invalid_object_key")

        request = json.loads((EXAMPLES / "facet-bot.json").read_text(encoding="utf-8"))
        request["spec"]["proportions"]["head_scale"] = Decimal("1." + "0" * 300)
        with self.assertRaises(ContractValidationError) as caught:
            BuildRequest.from_mapping(request)
        self.assertEqual(caught.exception.code, "numeric_limit")

        request = json.loads((EXAMPLES / "facet-bot.json").read_text(encoding="utf-8"))
        request[7] = "non-string key"
        with self.assertRaises(ContractValidationError) as caught:
            BuildRequest.from_mapping(request)
        self.assertEqual(caught.exception.code, "extra_property")

    def test_extreme_exponent_fixture_returns_a_stable_contract_error(self) -> None:
        with self.assertRaises(ContractValidationError) as caught:
            BuildRequest.from_json((REJECTED / "extreme-exponent.json").read_bytes())
        self.assertIn(caught.exception.code, {"invalid_number", "numeric_limit"})

    def test_attacker_controlled_keys_are_escaped_and_bounded_in_errors(self) -> None:
        request = json.loads((EXAMPLES / "facet-bot.json").read_text(encoding="utf-8"))
        hostile_key = "line-break\n" + "x" * 5000
        request[hostile_key] = True
        with self.assertRaises(ContractValidationError) as caught:
            BuildRequest.from_mapping(request)
        rendered = str(caught.exception)
        self.assertNotIn("\n", rendered)
        self.assertLess(len(rendered), 256)
        self.assertIn("\\n", rendered)

        encoded_key = json.dumps(hostile_key)
        duplicate_payload = "{" + encoded_key + ":1," + encoded_key + ":2}"
        with self.assertRaises(ContractValidationError) as caught:
            decode_json_document(duplicate_payload)
        rendered = str(caught.exception)
        self.assertNotIn("\n", rendered)
        self.assertLess(len(rendered), 256)
        self.assertIn("\\n", rendered)


if __name__ == "__main__":
    unittest.main()
