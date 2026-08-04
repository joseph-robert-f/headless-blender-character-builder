from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.release.support import ROOT, load_script, spdx_document, write


sbom_tool = load_script("service_sbom_under_test", "service-sbom")


class ServiceSbomTests(unittest.TestCase):
    def test_generates_deterministic_api_worker_builder_sboms_and_notices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = root / "builder-input.spdx.json"
            write(builder, spdx_document("headless-blender-character-builder"))
            first = root / "first"
            second = root / "second"
            first_hashes = sbom_tool.generate(ROOT, builder, first, 0)
            second_hashes = sbom_tool.generate(ROOT, builder, second, 0)
            first_files = sorted(path.name for path in first.iterdir())
            second_files = sorted(path.name for path in second.iterdir())
            first_payloads = {name: (first / name).read_bytes() for name in first_files}
            second_payloads = {name: (second / name).read_bytes() for name in second_files}

        self.assertEqual(first_files, second_files)
        self.assertEqual(first_hashes, second_hashes)
        self.assertEqual(
            first_files,
            [
                "SERVICE_THIRD_PARTY_NOTICES.txt",
                "api.spdx.json",
                "builder.spdx.json",
                "worker.spdx.json",
            ],
        )
        for name in first_files:
            self.assertEqual(first_payloads[name], second_payloads[name])
        api = json.loads(first_payloads["api.spdx.json"])
        worker = json.loads(first_payloads["worker.spdx.json"])
        dependency_count = len(sbom_tool.parse_lock((ROOT / "docker/service-requirements.lock").read_bytes()))
        self.assertEqual(len(api["packages"]), dependency_count + 1)
        self.assertIn("externalDocumentRefs", worker)
        self.assertTrue(
            any(
                relationship["relatedSpdxElement"]
                == "DocumentRef-Builder:SPDXRef-Package-HBCB"
                for relationship in worker["relationships"]
            )
        )
        notices = first_payloads["SERVICE_THIRD_PARTY_NOTICES.txt"].decode("utf-8")
        self.assertIn("Lock SHA-256:", notices)
        self.assertEqual(notices.count("  License: "), dependency_count)

    def test_inventory_is_exact_and_bound_to_reviewed_lock_hash(self) -> None:
        lock = (ROOT / "docker/service-requirements.lock").read_bytes()
        inventory_payload = (ROOT / "release/service-dependency-licenses.json").read_bytes()
        packages = sbom_tool.parse_lock(lock)
        inventory = sbom_tool.load_inventory(inventory_payload, lock)
        self.assertEqual(set(packages), set(inventory))
        self.assertTrue(all(item["license"] != "NOASSERTION" for item in inventory.values()))

        changed = lock + b"# reviewed hash changed\n"
        with self.assertRaises(sbom_tool.SbomFailure) as raised:
            sbom_tool.load_inventory(inventory_payload, changed)
        self.assertEqual(raised.exception.code, "license_inventory_stale")

    def test_builder_sbom_must_contain_reviewed_project_and_blender_packages(self) -> None:
        valid = json.loads(spdx_document("headless-blender-character-builder"))
        valid["packages"] = [valid["packages"][0]]
        payload = (json.dumps(valid, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        with self.assertRaises(sbom_tool.SbomFailure) as raised:
            sbom_tool.validate_builder_sbom(payload)
        self.assertEqual(raised.exception.code, "builder_sbom_incomplete")

    def test_lock_parser_rejects_unhashed_or_duplicate_dependencies(self) -> None:
        for payload in (
            b"example==1.0.0 \\\n",
            b"example==1.0.0 \\\n    --hash=sha256:" + b"a" * 64 + b"\nexample==2.0.0 \\\n    --hash=sha256:" + b"b" * 64 + b"\n",
        ):
            with self.subTest(payload=payload), self.assertRaises(sbom_tool.SbomFailure) as raised:
                sbom_tool.parse_lock(payload)
            self.assertEqual(raised.exception.code, "invalid_service_lock")

    def test_output_directory_is_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = root / "builder.spdx.json"
            write(builder, spdx_document("headless-blender-character-builder"))
            output = root / "output"
            sbom_tool.generate(ROOT, builder, output, 0)
            with self.assertRaises(sbom_tool.SbomFailure) as raised:
                sbom_tool.generate(ROOT, builder, output, 0)
            self.assertEqual(raised.exception.code, "output_exists")


if __name__ == "__main__":
    unittest.main()
