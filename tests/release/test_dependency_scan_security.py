from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.release.support import load_script


scan_tool = load_script("dependency_scan_security_under_test", "dependency-scan")


class DependencyScanSecurityTests(unittest.TestCase):
    def test_policy_image_identifiers_are_safe_unique_and_complete(self) -> None:
        expected = scan_tool.expected_external_image_ids()
        self.assertEqual(
            set(expected), {"caddy", "docker-base", "postgres", "redis-server"}
        )
        self.assertTrue(all(scan_tool.SAFE_ID.fullmatch(item) for item in expected))

    def test_external_inventory_rejects_unsafe_duplicate_mutable_or_partial_items(self) -> None:
        expected = ("docker-base", "postgres")
        digest = "a" * 64
        valid = [
            {"id": "postgres", "reference": "postgres:16@sha256:" + digest},
            {"id": "docker-base", "reference": "debian:12@sha256:" + digest},
        ]
        self.assertEqual(
            [item["id"] for item in scan_tool.validate_external_images(valid, expected)],
            ["docker-base", "postgres"],
        )
        invalid_inventories = (
            valid + [valid[0]],
            [{"id": "../escape", "reference": "postgres:16@sha256:" + digest}],
            [{"id": "postgres", "reference": "postgres:16"}],
            [valid[0]],
        )
        for inventory in invalid_inventories:
            with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                scan_tool.validate_external_images(inventory, expected)

    def test_osv_report_requires_results_and_obeys_aggregate_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing_schema = root / "missing.json"
            missing_schema.write_text("{}", encoding="utf-8")
            self.assertEqual(
                scan_tool.validate_scan_report(missing_schema, 0), (127, None)
            )
            self.assertFalse(missing_schema.exists())

            valid = root / "valid.json"
            valid.write_text(json.dumps({"results": []}), encoding="utf-8")
            with mock.patch.object(scan_tool, "MAX_OUTPUT_BYTES", 16), mock.patch.object(
                scan_tool, "REPORT_RESERVE_BYTES", 8
            ):
                self.assertEqual(scan_tool.validate_scan_report(valid, 0), (127, None))
            self.assertFalse(valid.exists())

            oversized = root / "oversized.json"
            oversized.write_text(
                json.dumps({"results": [{"detail": "x" * 64}]}), encoding="utf-8"
            )
            with mock.patch.object(scan_tool, "MAX_OSV_REPORT_BYTES", 32):
                self.assertEqual(
                    scan_tool.validate_scan_report(oversized, 1), (127, None)
                )
            self.assertFalse(oversized.exists())

    def test_five_mib_osv_report_is_retained_within_bounded_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "postgres.json"
            report.write_text(
                json.dumps({"results": [{"detail": "x" * (5 * 1024 * 1024)}]}),
                encoding="utf-8",
            )
            self.assertEqual(
                scan_tool.validate_scan_report(report, 1),
                (1, "postgres.json"),
            )
            self.assertLessEqual(report.stat().st_size, scan_tool.MAX_OSV_REPORT_BYTES)

    def test_every_requested_scan_target_is_recorded_when_not_run(self) -> None:
        records: list[dict[str, object]] = []
        scan_tool.record_unrun_scans(records, True, ("postgres",))
        identifiers = {str(item["id"]) for item in records}
        self.assertEqual(
            identifiers,
            {
                "osv-source",
                "osv-image-api",
                "osv-image-builder",
                "osv-image-minio",
                "osv-image-postgres",
                "osv-image-worker",
            },
        )
        self.assertTrue(all(item["status"] == "incomplete" for item in records))
        self.assertEqual(scan_tool.final_status(records, []), "incomplete")


if __name__ == "__main__":
    unittest.main()
