from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "compose" / "minio-maintenance-policy.json"
INIT_SCRIPT = ROOT / "compose" / "minio-init.sh"
COMPOSE = ROOT / "compose.yaml"


class MaintenanceStoragePolicyTests(unittest.TestCase):
    def test_policy_allows_exact_version_maintenance_without_admin_or_broad_delete(self) -> None:
        document = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(document["Version"], "2012-10-17")
        statements = document["Statement"]
        self.assertEqual(len(statements), 4)
        actions = {
            action
            for statement in statements
            for action in statement["Action"]
        }
        self.assertIn("s3:GetObjectVersion", actions)
        self.assertIn("s3:PutObject", actions)
        self.assertIn("s3:DeleteObjectVersion", actions)
        self.assertIn("s3:ListBucketVersions", actions)
        self.assertIn("s3:DeleteObject", actions)
        self.assertFalse(any(action.startswith("admin:") for action in actions))
        self.assertFalse(any(action == "s3:*" for action in actions))

        object_statements = [
            statement
            for statement in statements
            if "s3:DeleteObjectVersion" in statement["Action"]
        ]
        self.assertEqual(len(object_statements), 1)
        self.assertEqual(
            object_statements[0]["Resource"],
            ["arn:aws:s3:::hbcb-artifacts/local/v1/builds/*"],
        )

        compatibility_statements = [
            statement
            for statement in statements
            if statement["Effect"] == "Allow"
            and "s3:DeleteObject" in statement["Action"]
        ]
        self.assertEqual(len(compatibility_statements), 1)
        self.assertEqual(compatibility_statements[0]["Action"], ["s3:DeleteObject"])
        self.assertEqual(
            compatibility_statements[0]["Condition"],
            {
                "StringLike": {
                    "s3:versionid": "????????-????-????-????-????????????"
                }
            },
        )
        self.assertEqual(
            compatibility_statements[0]["Resource"],
            ["arn:aws:s3:::hbcb-artifacts/local/v1/builds/*"],
        )

        list_statements = [
            statement
            for statement in statements
            if "s3:ListBucketVersions" in statement["Action"]
        ]
        self.assertEqual(len(list_statements), 1)
        self.assertEqual(
            list_statements[0]["Condition"],
            {"StringLike": {"s3:prefix": ["local/v1/builds/*"]}},
        )

    def test_local_initializer_wires_a_distinct_maintenance_identity(self) -> None:
        script = INIT_SCRIPT.read_text(encoding="utf-8")
        compose = COMPOSE.read_text(encoding="utf-8")
        for marker in (
            "HBCB_STORAGE_MAINTENANCE_ACCESS_KEY",
            "HBCB_STORAGE_MAINTENANCE_SECRET_KEY",
            "/policies/minio-maintenance-policy.json",
        ):
            self.assertIn(marker, script)
            self.assertIn(marker, compose)
        self.assertIn("hbcb-maintenance-v1", script)
        self.assertIn("hbcb_maintenance|hbcb_maintenance_*", script)
        self.assertIn("storage identities must be distinct", script)
        self.assertIn("storage secrets must be distinct", script)


if __name__ == "__main__":
    unittest.main()
