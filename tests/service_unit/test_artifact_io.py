from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

from shared.build_manifest import BuildManifest, MAX_PUBLISHED_ARTIFACT_BYTES
from shared.character_spec import BuildRequest
from shared.json_contract import ContractValidationError

from hbcb_service.artifact_io import records_from_output
from hbcb_service.errors import WorkerError
from hbcb_service.models import MAX_PUBLISHED_BYTES

try:
    from .g6_support import facet_request_bytes, write_valid_builder_output
except ImportError:
    from g6_support import facet_request_bytes, write_valid_builder_output


class PublishedArtifactBudgetTests(unittest.TestCase):
    def test_service_and_manifest_use_the_same_limit(self) -> None:
        self.assertEqual(MAX_PUBLISHED_BYTES, MAX_PUBLISHED_ARTIFACT_BYTES)

    def test_local_manifest_and_upload_records_count_all_nine_files(self) -> None:
        request_payload = facet_request_bytes()
        request = BuildRequest.from_json(request_payload)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "output"
            write_valid_builder_output(root, request_payload)
            manifest_payload = (root / "manifest.json").read_bytes()
            total_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
            arguments = {
                "build_id": uuid4(), "attempt_id": uuid4(),
                "request_sha256": request.request_sha256,
                "spec_sha256": request.spec_sha256,
                "namespace": "local", "bucket": "hbcb-artifacts",
            }
            # Scale the limit to real small files instead of allocating 2 GiB.
            for limit in (total_bytes, total_bytes - 1):
                with self.subTest(limit=limit), mock.patch(
                    "shared.build_manifest.MAX_PUBLISHED_ARTIFACT_BYTES", limit
                ), mock.patch("hbcb_service.artifact_io.MAX_PUBLISHED_BYTES", limit):
                    if limit == total_bytes:
                        BuildManifest.from_json(manifest_payload)
                        records = records_from_output(root, **arguments)
                        self.assertEqual(len(records), 9)
                        self.assertEqual(sum(record.bytes for record in records), total_bytes)
                    else:
                        with self.assertRaisesRegex(ContractValidationError, "artifact_budget_exceeded"):
                            BuildManifest.from_json(manifest_payload)
                        with self.assertRaises(WorkerError) as captured:
                            records_from_output(root, **arguments)
                        self.assertEqual(captured.exception.code, "manifest_invalid")


if __name__ == "__main__":
    unittest.main()
