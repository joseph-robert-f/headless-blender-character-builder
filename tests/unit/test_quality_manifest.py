from __future__ import annotations

import copy
import unittest

from shared.build_manifest import BuildManifest, MAX_PUBLISHED_ARTIFACT_BYTES, validate_manifest
from shared.json_contract import ContractValidationError
from shared.quality_report import (
    QA_STATUS_BUILD_MAPPING,
    QualityReport,
    derive_qa_status,
    validate_quality_report,
)
from tests.support import passed_qa_report, valid_manifest


class QualityReportTests(unittest.TestCase):
    def test_passed_report_and_terminal_mapping(self) -> None:
        report = QualityReport.from_mapping(passed_qa_report())
        self.assertEqual(report.qa_version, "qa/v1")
        self.assertEqual(report.status, "passed")
        self.assertEqual(report.build_mapping["build_status"], "succeeded")
        self.assertEqual(report.build_mapping["exit_code"], 0)
        self.assertTrue(report.build_mapping["publish_success_manifest"])
        with self.assertRaises(TypeError):
            report.measurements["triangle_count"] = 1
        with self.assertRaises(TypeError):
            report.build_mapping["exit_code"] = 99
        self.assertIsNot(report, validate_quality_report(report))

    def test_unmeasurable_mandatory_evidence_requires_needs_review(self) -> None:
        raw = passed_qa_report()
        raw["measurements"]["minimum_wall_mm"] = None
        raw["status"] = "needs_review"
        raw["notes"] = ["Wall thickness could not be established by the bounded QA pass."]
        report = QualityReport.from_mapping(raw)
        self.assertEqual(report.status, "needs_review")
        self.assertEqual(report.build_mapping["build_status"], "needs_review")
        self.assertEqual(report.build_mapping["exit_code"], 11)
        self.assertFalse(report.build_mapping["publish_success_manifest"])

    def test_unmeasurable_takes_precedence_over_a_measurable_failure(self) -> None:
        raw = passed_qa_report()
        raw["measurements"]["minimum_wall_mm"] = None
        raw["checks"]["manifold"] = False
        self.assertEqual(derive_qa_status(raw["measurements"], raw["checks"]), "needs_review")

    def test_missing_review_note_and_status_mismatch_are_rejected(self) -> None:
        raw = passed_qa_report()
        raw["measurements"]["minimum_feature_mm"] = None
        raw["status"] = "needs_review"
        with self.assertRaisesRegex(ContractValidationError, "review_note_required"):
            QualityReport.from_mapping(raw)
        raw["status"] = "passed"
        with self.assertRaisesRegex(ContractValidationError, "qa_status_mismatch"):
            QualityReport.from_mapping(raw)

    def test_measurable_threshold_failure_maps_to_failed(self) -> None:
        raw = passed_qa_report()
        raw["measurements"]["minimum_feature_mm"] = 1.99
        raw["status"] = "failed"
        report = QualityReport.from_mapping(raw)
        self.assertEqual(report.build_mapping, QA_STATUS_BUILD_MAPPING["failed"])
        self.assertEqual(report.build_mapping["exit_code"], 11)
        self.assertFalse(report.build_mapping["publish_success_manifest"])

    def test_reimport_bounds_outside_per_axis_tolerance_fail(self) -> None:
        raw = passed_qa_report()
        # X tolerance at 64 mm is max(0.2, 0.32); 0.33 mm must fail.
        raw["measurements"]["glb_dimensions_mm"][0] = 64.33
        raw["status"] = "failed"
        report = QualityReport.from_mapping(raw)
        self.assertEqual(report.status, "failed")

        boundary = passed_qa_report()
        boundary["measurements"]["glb_dimensions_mm"][0] = 64.32
        QualityReport.from_mapping(boundary)

    def test_evaluated_height_must_match_requested_height(self) -> None:
        raw = passed_qa_report()
        raw["measurements"]["requested_height_mm"] = 96
        raw["status"] = "failed"
        self.assertEqual(QualityReport.from_mapping(raw).status, "failed")

    def test_zero_geometry_counts_cannot_pass(self) -> None:
        for field in ("triangle_count", "object_count", "material_count"):
            raw = passed_qa_report()
            raw["measurements"][field] = 0
            raw["status"] = "failed"
            with self.subTest(field=field):
                self.assertEqual(QualityReport.from_mapping(raw).status, "failed")

    def test_fewer_than_four_triangles_cannot_form_a_passing_closed_shell(self) -> None:
        for triangle_count in (1, 2, 3):
            raw = passed_qa_report()
            raw["measurements"]["triangle_count"] = triangle_count
            raw["status"] = "failed"
            with self.subTest(triangle_count=triangle_count):
                self.assertEqual(QualityReport.from_mapping(raw).status, "failed")

    def test_integral_float_counts_match_json_schema_integer_semantics(self) -> None:
        raw = passed_qa_report()
        raw["measurements"]["triangle_count"] = 24000.0
        raw["measurements"]["object_count"] = 18.0
        raw["measurements"]["material_count"] = 3.0
        report = QualityReport.from_mapping(raw)
        self.assertEqual(report.measurements["triangle_count"], 24000)

    def test_dimensions_are_wholly_null_or_three_nonnull_positive_numbers(self) -> None:
        raw = passed_qa_report()
        raw["measurements"]["dimensions_mm"] = [None, 51, 95]
        raw["status"] = "needs_review"
        raw["notes"] = ["Bounds unavailable."]
        with self.assertRaisesRegex(ContractValidationError, "invalid_dimensions"):
            QualityReport.from_mapping(raw)

        raw = passed_qa_report()
        raw["measurements"]["dimensions_mm"] = None
        raw["status"] = "needs_review"
        raw["notes"] = ["Evaluated bounds unavailable."]
        QualityReport.from_mapping(raw)

    def test_qa_extra_fields_and_wrong_version_are_rejected(self) -> None:
        raw = passed_qa_report()
        raw["checks"]["renderer_flag"] = True
        with self.assertRaisesRegex(ContractValidationError, "extra_property"):
            QualityReport.from_mapping(raw)
        raw = passed_qa_report()
        raw["qa_version"] = "qa/v2"
        with self.assertRaisesRegex(ContractValidationError, "unsupported_version"):
            QualityReport.from_mapping(raw)


class ManifestTests(unittest.TestCase):
    def test_native_success_manifest_validates_with_explicit_version(self) -> None:
        manifest = BuildManifest.from_mapping(valid_manifest())
        self.assertEqual(manifest.manifest_version, "manifest/v1")
        self.assertNotIn("manifest.json", manifest.artifacts)
        self.assertEqual(len(manifest.artifacts), 8)
        self.assertEqual(manifest.execution["blender_version"], "4.5.12 LTS")
        with self.assertRaises(TypeError):
            manifest.execution["mode"] = "container"
        with self.assertRaises(TypeError):
            manifest.artifacts["model.stl"]["bytes"] = 0
        self.assertIsNot(manifest, validate_manifest(manifest))

    def test_container_provenance_is_bounded_and_validates(self) -> None:
        raw = valid_manifest()
        raw["execution"].update(
            {
                "mode": "container",
                "worker_image_reference": "headless-blender-character-builder:dev",
                "worker_image_digest": "sha256:" + "1" * 64,
                "worker_image_id": None,
            }
        )
        BuildManifest.from_mapping(raw)

    def test_native_mode_rejects_image_fields(self) -> None:
        raw = valid_manifest()
        raw["execution"]["worker_image_reference"] = "image:tag"
        with self.assertRaisesRegex(ContractValidationError, "native_image_metadata"):
            BuildManifest.from_mapping(raw)

    def test_manifest_rejects_arbitrary_artifact_paths_and_self_hash(self) -> None:
        for name in ("../escape.stl", "manifest.json"):
            raw = valid_manifest()
            raw["artifacts"][name] = {"sha256": "f" * 64, "bytes": 1}
            with self.subTest(name=name):
                with self.assertRaisesRegex(ContractValidationError, "extra_property"):
                    BuildManifest.from_mapping(raw)

    def test_manifest_requires_exact_artifact_set(self) -> None:
        raw = valid_manifest()
        del raw["artifacts"]["diagnostics/back.png"]
        with self.assertRaisesRegex(ContractValidationError, "missing_property"):
            BuildManifest.from_mapping(raw)

    def test_manifest_rejects_external_inputs_and_failed_qa(self) -> None:
        raw = valid_manifest()
        raw["input_sha256"]["https://attacker.invalid/model"] = "a" * 64
        with self.assertRaisesRegex(ContractValidationError, "remote_input_forbidden"):
            BuildManifest.from_mapping(raw)
        raw = valid_manifest()
        raw["qa"]["status"] = "needs_review"
        with self.assertRaisesRegex(ContractValidationError, "success_manifest_requires_pass"):
            BuildManifest.from_mapping(raw)

    def test_manifest_enforces_aggregate_two_gib_budget(self) -> None:
        raw = valid_manifest()
        exact_share = MAX_PUBLISHED_ARTIFACT_BYTES // len(raw["artifacts"])
        for artifact in raw["artifacts"].values():
            artifact["bytes"] = exact_share
        BuildManifest.from_mapping(raw)
        raw["artifacts"]["qa.json"]["bytes"] += 1
        with self.assertRaisesRegex(ContractValidationError, "artifact_budget_exceeded"):
            BuildManifest.from_mapping(raw)

    def test_manifest_rejects_extra_nested_fields(self) -> None:
        mutations = []
        raw = valid_manifest()
        raw["execution"]["blender_flags"] = ["--python"]
        mutations.append(raw)
        raw = valid_manifest()
        raw["artifacts"]["model.stl"]["path"] = "/tmp/model.stl"
        mutations.append(raw)
        raw = valid_manifest()
        raw["qa"]["notes"] = "unexpected"
        mutations.append(raw)
        for mutation in mutations:
            with self.assertRaisesRegex(ContractValidationError, "extra_property"):
                BuildManifest.from_mapping(mutation)


if __name__ == "__main__":
    unittest.main()
