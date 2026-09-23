from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from tests.release.support import load_script


scan_tool = load_script("dependency_scan_security_under_test", "dependency-scan")
IMAGE_IDENTITY = "sha256:" + "9" * 64


def advisory_report(score: str = "8.1") -> dict[str, object]:
    return {
        "results": [
            {
                "packages": [
                    {
                        "groups": [
                            {
                                "aliases": [
                                    "CVE-2026-1234",
                                    "GHSA-AAAA-BBBB-CCCC",
                                    "GO-2026-1234",
                                ],
                                "ids": ["GO-2026-1234", "GHSA-aaaa-bbbb-cccc"],
                                "max_severity": score,
                            }
                        ],
                        "package": {
                            "commit": "abc123",
                            "ecosystem": "Go",
                            "name": "example.invalid/module",
                            "version": "1.2.3",
                        },
                        "vulnerabilities": [
                            {
                                "affected": [
                                    {
                                        "package": {
                                            "ecosystem": "Go",
                                            "name": "example.invalid/module",
                                        },
                                        "ranges": [
                                            {
                                                "events": [
                                                    {"introduced": "0"},
                                                    {"fixed": "1.2.4"},
                                                ],
                                                "type": "SEMVER",
                                            }
                                        ],
                                    },
                                    {
                                        "package": {
                                            "ecosystem": "Go:other",
                                            "name": "example.invalid/module",
                                        },
                                        "ranges": [
                                            {
                                                "events": [{"fixed": "99.0.0"}],
                                                "type": "SEMVER",
                                            }
                                        ],
                                    },
                                ],
                                "aliases": ["GHSA-aaaa-bbbb-cccc"],
                                "database_specific": {"review_status": "REVIEWED"},
                                "id": "GO-2026-1234",
                                "related": ["CGA-MUST-NOT-JOIN-FAMILY"],
                                "upstream": ["CVE-2026-1234"],
                            },
                            {
                                "aliases": ["CVE-2026-1234", "GO-2026-1234"],
                                "database_specific": {"severity": "HIGH"},
                                "id": "GHSA-aaaa-bbbb-cccc",
                                "severity": [
                                    {
                                        "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
                                        "type": "CVSS_V3",
                                    }
                                ],
                            },
                        ],
                    }
                ],
                "source": {"path": "image"},
            }
        ]
    }


def exact_disposition(evidence_sha256: str) -> dict[str, object]:
    return {
        "advisory_family": [
            "CVE-2026-1234",
            "GHSA-AAAA-BBBB-CCCC",
            "GO-2026-1234",
        ],
        "disposition": "mitigated",
        "evidence": [{"path": "docs/review.md", "sha256": evidence_sha256}],
        "expires_on": "2026-09-10",
        "fixed_versions": ["1.2.4"],
        "image_identity": IMAGE_IDENTITY,
        "package": {
            "ecosystem": "Go",
            "name": "example.invalid/module",
            "source_revision": "abc123",
            "version": "1.2.3",
        },
        "rationale": "Static deployment evidence demonstrates the reviewed mitigation.",
        "reviewed_on": "2026-08-12",
        "score": "8.1",
        "severity": "HIGH",
        "target": "osv-image-minio",
    }


def write_policy(root: Path, dispositions: list[dict[str, object]]) -> None:
    path = root / "release" / "vulnerability-policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "default_action": "deny",
                "dispositions": dispositions,
                "format": scan_tool.VULNERABILITY_POLICY_FORMAT,
            }
        ),
        encoding="utf-8",
    )


class DependencyScanSecurityTests(unittest.TestCase):
    def _wait_for_path(self, path: Path, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file() and path.stat().st_size > 0:
                return
            time.sleep(0.02)
        self.fail("subprocess readiness marker was not created")

    def _wait_for_group_exit(self, process_group: int, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not scan_tool._process_group_exists(process_group):
                return True
            time.sleep(0.02)
        return not scan_tool._process_group_exists(process_group)

    @staticmethod
    def _docker_archive(
        path: Path,
        *,
        architecture: str = "amd64",
        image_os: str = "linux",
        labels=None,
    ) -> str:
        config_document = {"architecture": architecture, "os": image_os}
        if labels is not None:
            config_document["config"] = {"Labels": dict(labels)}
        config = json.dumps(
            config_document,
            separators=(",", ":"),
        ).encode("utf-8")
        config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
        config_name = config_digest.removeprefix("sha256:") + ".json"
        manifest = json.dumps(
            [{"Config": config_name, "Layers": [], "RepoTags": None}],
            separators=(",", ":"),
        ).encode("utf-8")
        with tarfile.open(path, "w") as archive:
            for name, payload in ((config_name, config), ("manifest.json", manifest)):
                member = tarfile.TarInfo(name)
                member.mode = 0o600
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
        return config_digest

    def test_lock_recipe_uses_only_the_pip_enabled_test_image(self) -> None:
        documentation = (
            scan_tool.ROOT / "docs" / "dependency-maintenance.md"
        ).read_text(encoding="utf-8")
        recipe = documentation.split("download_wheels()", 1)[1].split("```", 1)[0]
        self.assertIn("make test-image", documentation)
        self.assertIn("headless-blender-character-builder:dev-test", recipe)
        self.assertNotIn("make image\n", documentation)
        self.assertNotIn("headless-blender-character-builder:dev \\", recipe)

    def test_checked_in_vulnerability_policy_has_release_contract(self) -> None:
        # PR checks do not require the release decisions to be current. The
        # enforced deployment scan validates dates, evidence, and identities.
        policy = scan_tool.strict_json_loads(
            (scan_tool.ROOT / scan_tool.VULNERABILITY_POLICY_PATH).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            set(policy), {"default_action", "dispositions", "format"}
        )
        self.assertEqual(policy["format"], "hbcb-vulnerability-policy/v1")
        self.assertEqual(policy["default_action"], "deny")
        self.assertIsInstance(policy["dispositions"], list)

    def test_report_only_scan_skips_release_decisions_but_keeps_other_gates(self) -> None:
        audit_status = "pass"
        seen_policies = []

        def fake_audit(command, **_kwargs):
            report = Path(command[command.index("--json") + 1])
            markdown = Path(command[command.index("--markdown") + 1])
            report.write_text(
                json.dumps(
                    {
                        "format": "hbcb-dependency-audit/v1",
                        "images": [],
                        "mode": "online",
                        "status": audit_status,
                    }
                ),
                encoding="utf-8",
            )
            markdown.write_text("# Dependency audit\n", encoding="utf-8")
            return {"pass": 0, "findings": 1, "incomplete": 2}[audit_status]

        def fake_source(_scanner, output, records, policy):
            seen_policies.append(policy)
            (output / "osv-source.json").write_text("{}\n", encoding="utf-8")
            records.append(
                {
                    "exit_code": 1,
                    "id": "osv-source",
                    "report": "osv-source.json",
                    "status": "findings",
                    "type": "vulnerability-scan",
                    "vulnerabilities": {
                        "blocking": 1,
                        "dispositioned": 0,
                        "families": 1,
                        "severity": {name: 0 for name in scan_tool.SEVERITY_ORDER},
                    },
                }
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                mock.patch.object(
                    scan_tool,
                    "load_vulnerability_policy",
                    side_effect=scan_tool.ScanError("expired release decisions"),
                ) as load_policy,
                mock.patch.object(scan_tool, "run", side_effect=fake_audit),
                mock.patch.object(scan_tool, "expected_external_image_ids", return_value=()),
                mock.patch.object(scan_tool, "validate_external_images", return_value=[]),
                mock.patch.object(scan_tool, "scanner_asset", return_value=("test", "0" * 64)),
                mock.patch.object(scan_tool, "download_scanner"),
                mock.patch.object(scan_tool, "verify_scanner"),
                mock.patch.object(scan_tool, "scan_source", side_effect=fake_source),
            ):
                advisory = root / "advisory"
                self.assertEqual(
                    scan_tool.execute(advisory, False, None, report_only=True), 0
                )
                load_policy.assert_not_called()
                summary = json.loads(
                    (advisory / "scan-summary.json").read_text(encoding="utf-8")
                )
                self.assertEqual(summary["mode"], "report-only")
                self.assertEqual(summary["status"], "findings")
                self.assertEqual(summary["vulnerability_policy"]["status"], "not-applied")
                self.assertTrue((advisory / "osv-source.json").is_file())
                self.assertEqual(seen_policies[-1]["dispositions"], [])
                self.assertIn(
                    "Vulnerability findings are advisory",
                    (advisory / "scan-summary.md").read_text(encoding="utf-8"),
                )

                audit_status = "findings"
                self.assertEqual(
                    scan_tool.execute(root / "maintenance-findings", False, None, report_only=True),
                    1,
                )
                load_policy.assert_not_called()

                audit_status = "incomplete"
                self.assertEqual(
                    scan_tool.execute(root / "incomplete", False, None, report_only=True),
                    2,
                )
                load_policy.assert_not_called()

                audit_status = "pass"
                self.assertEqual(scan_tool.execute(root / "enforced", False, None), 2)
                load_policy.assert_called_once()

    def test_vulnerability_policy_rejects_symlink_oversize_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = root / "release"
            release.mkdir()
            target = root / "outside-policy.json"
            target.write_text(
                '{"dispositions":[],"format":"hbcb-vulnerability-policy/v1"}',
                encoding="utf-8",
            )
            policy_path = release / "vulnerability-policy.json"
            policy_path.symlink_to(target)
            with self.assertRaises(scan_tool.ScanError):
                scan_tool.load_vulnerability_policy(root)
            policy_path.unlink()
            write_policy(root, [])
            with mock.patch.object(scan_tool, "MAX_POLICY_BYTES", 1):
                with self.assertRaises(scan_tool.ScanError):
                    scan_tool.load_vulnerability_policy(root)

            evidence = root / "docs" / "review.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("Reviewed runtime mitigation evidence.\n", encoding="utf-8")
            disposition = exact_disposition(
                hashlib.sha256(evidence.read_bytes()).hexdigest()
            )
            write_policy(root, [disposition, disposition])
            with self.assertRaisesRegex(scan_tool.ScanError, "duplicated"):
                scan_tool.load_vulnerability_policy(
                    root,
                    today=date(2026, 8, 12),
                )

    def test_policy_image_identifiers_are_safe_unique_and_complete(self) -> None:
        expected = scan_tool.expected_external_image_ids()
        self.assertEqual(
            set(expected), {"docker-base", "redis-server"}
        )
        self.assertTrue(all(scan_tool.SAFE_ID.fullmatch(item) for item in expected))

    def test_disposition_context_identity_binds_every_reviewed_runtime_control(self) -> None:
        expected = {
            "api": (
                "compose.yaml",
                "deploy/vps/Caddyfile",
                "deploy/vps/compose.yaml",
            ),
            "caddy": (
                "deploy/vps/Caddyfile",
                "deploy/vps/compose.yaml",
                "docker/caddy.Dockerfile",
            ),
            "minio": (
                "compose.yaml",
                "deploy/vps/compose.yaml",
                "tests/deployment/g8_recovery_compose.yaml",
                "tests/security/minio_fixture_gate.py",
                "tests/service_integration/g8_orphan_minio_compose.yaml",
            ),
            "postgres": (
                "compose.yaml",
                "deploy/vps/compose.yaml",
                "docker/postgres.Dockerfile",
                "tests/deployment/g8_recovery_compose.yaml",
                "tests/security/postgres_fixture_gate.py",
                "tests/service_integration/g8_orphan_minio_compose.yaml",
            ),
            "worker": (
                "compose.yaml",
                "deploy/vps/Caddyfile",
                "deploy/vps/compose.yaml",
            ),
        }
        self.assertEqual(scan_tool.DISPOSITION_CONTEXT_FILES, expected)
        image_identity = {"policy_digest": "sha256:" + "a" * 64}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in sorted(
                {path for paths in expected.values() for path in paths}
            ):
                candidate = root / relative
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("reviewed " + relative + "\n", encoding="utf-8")

            for identifier, paths in expected.items():
                with self.subTest(identifier=identifier):
                    baseline = scan_tool._bind_disposition_context(
                        identifier,
                        image_identity,
                        root,
                    )
                    self.assertEqual(
                        baseline["image_policy_digest"],
                        image_identity["policy_digest"],
                    )
                    self.assertEqual(
                        baseline["disposition_context_files"],
                        list(paths),
                    )
                    self.assertRegex(
                        baseline["disposition_context_digest"],
                        r"^sha256:[0-9a-f]{64}$",
                    )
                    self.assertRegex(
                        baseline["policy_digest"],
                        r"^sha256:[0-9a-f]{64}$",
                    )
                    for relative in paths:
                        candidate = root / relative
                        original = candidate.read_bytes()
                        candidate.write_bytes(original + b"changed\n")
                        changed = scan_tool._bind_disposition_context(
                            identifier,
                            image_identity,
                            root,
                        )
                        self.assertNotEqual(
                            changed["disposition_context_digest"],
                            baseline["disposition_context_digest"],
                        )
                        self.assertNotEqual(
                            changed["policy_digest"],
                            baseline["policy_digest"],
                        )
                        candidate.write_bytes(original)

            self.assertEqual(
                scan_tool._bind_disposition_context(
                    "builder",
                    image_identity,
                    root,
                ),
                image_identity,
            )
            linked = root / "deploy" / "vps" / "Caddyfile"
            linked.unlink()
            linked.symlink_to(root / "compose.yaml")
            with self.assertRaises(scan_tool.ScanError):
                scan_tool._bind_disposition_context(
                    "caddy",
                    image_identity,
                    root,
                )

    def test_disposition_context_rejects_same_size_in_place_rewrite(self) -> None:
        image_identity = {"policy_digest": "sha256:" + "a" * 64}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in scan_tool.DISPOSITION_CONTEXT_FILES["caddy"]:
                candidate = root / relative
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("reviewed control\n", encoding="utf-8")

            candidate = root / "deploy" / "vps" / "Caddyfile"
            replacement = b"rewritten control"
            self.assertEqual(len(replacement), candidate.stat().st_size)
            real_fstat = os.fstat
            first_call = True

            def rewrite_after_open(descriptor: int):
                nonlocal first_call
                metadata = real_fstat(descriptor)
                if first_call:
                    first_call = False
                    candidate.write_bytes(replacement)
                    os.utime(
                        candidate,
                        ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000),
                    )
                return metadata

            with mock.patch.object(
                scan_tool.os,
                "fstat",
                side_effect=rewrite_after_open,
            ), self.assertRaisesRegex(scan_tool.ScanError, "changed while being read"):
                scan_tool._bind_disposition_context(
                    "caddy",
                    image_identity,
                    root,
                )

    def test_disposition_context_rejects_missing_empty_and_oversized_inputs(self) -> None:
        image_identity = {"policy_digest": "sha256:" + "a" * 64}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = scan_tool.DISPOSITION_CONTEXT_FILES["caddy"]
            for relative in paths:
                candidate = root / relative
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("reviewed control\n", encoding="utf-8")

            caddyfile = root / paths[0]
            caddyfile.unlink()
            with self.assertRaisesRegex(scan_tool.ScanError, "unavailable"):
                scan_tool._bind_disposition_context("caddy", image_identity, root)
            caddyfile.write_bytes(b"")
            with self.assertRaisesRegex(scan_tool.ScanError, "unsafe"):
                scan_tool._bind_disposition_context("caddy", image_identity, root)
            caddyfile.write_text("reviewed control\n", encoding="utf-8")
            with mock.patch.object(
                scan_tool,
                "MAX_DISPOSITION_CONTEXT_BYTES",
                caddyfile.stat().st_size - 1,
            ), self.assertRaisesRegex(scan_tool.ScanError, "unsafe"):
                scan_tool._bind_disposition_context("caddy", image_identity, root)
            with mock.patch.object(
                scan_tool,
                "MAX_DISPOSITION_CONTEXT_BYTES",
                caddyfile.stat().st_size + 1,
            ), self.assertRaisesRegex(scan_tool.ScanError, "exceeded its size limit"):
                scan_tool._bind_disposition_context("caddy", image_identity, root)

    def test_external_inventory_rejects_unsafe_duplicate_mutable_or_partial_items(self) -> None:
        expected = ("docker-base",)
        digest = "a" * 64
        valid = [
            {
                "id": "postgres",
                "reference": "postgres:16@sha256:" + digest,
                "scan_mode": "local-build",
            },
            {
                "id": "caddy",
                "reference": "caddy:2.11.4-alpine@sha256:" + digest,
                "scan_mode": "local-build",
            },
            {"id": "docker-base", "reference": "debian:12@sha256:" + digest},
        ]
        self.assertEqual(
            [item["id"] for item in scan_tool.validate_external_images(valid, expected)],
            ["docker-base"],
        )
        invalid_inventories = (
            valid + [valid[0]],
            valid + [{"id": "../escape", "reference": "postgres:16@sha256:" + digest}],
            [valid[0], {"id": "docker-base", "reference": "debian:12"}],
            [dict(valid[0], scan_mode="external"), valid[1], valid[2]],
            [valid[0]],
        )
        for inventory in invalid_inventories:
            with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                scan_tool.validate_external_images(inventory, expected)

    def test_external_resolution_selects_one_linux_amd64_child_and_pulls_pinned_index(self) -> None:
        config_payload = b'{"architecture":"amd64","os":"linux"}'
        config_digest = "sha256:" + hashlib.sha256(config_payload).hexdigest()
        child_payload = json.dumps(
            {
                "config": {
                    "digest": config_digest,
                    "mediaType": "application/vnd.oci.image.config.v1+json",
                    "size": len(config_payload),
                },
                "layers": [],
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "schemaVersion": 2,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        child_digest = "sha256:" + hashlib.sha256(child_payload).hexdigest()
        index_payload = json.dumps(
            {
                "manifests": [
                    {
                        "digest": child_digest,
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "platform": {"architecture": "amd64", "os": "linux"},
                        "size": len(child_payload),
                    },
                    {
                        "digest": "sha256:" + "a" * 64,
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "platform": {"architecture": "arm64", "os": "linux"},
                        "size": 100,
                    },
                ],
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "schemaVersion": 2,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        requested_digest = "sha256:" + hashlib.sha256(index_payload).hexdigest()
        reference = "example.invalid/release:1@" + requested_digest
        child_reference = "example.invalid/release:1@" + child_digest
        observed: list[list[str]] = []

        def capture(command, **_kwargs):
            rendered = list(command)
            observed.append(rendered)
            if rendered[1:5] == ["buildx", "imagetools", "inspect", "--raw"]:
                return index_payload if rendered[-1] == reference else child_payload
            if rendered[1:3] == ["image", "inspect"]:
                return json.dumps(
                    [
                        {
                            "Architecture": "amd64",
                            "Id": config_digest,
                            "Os": "linux",
                            "RepoDigests": ["example.invalid/release@" + requested_digest],
                        }
                    ]
                ).encode("utf-8")
            if rendered[1] == "pull":
                return b"pulled\n"
            self.fail("unexpected command: " + repr(rendered))

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            scan_tool,
            "run_bounded_capture",
            side_effect=capture,
        ), mock.patch.object(
            scan_tool,
            "_save_external_image_archive",
            return_value=(1234, "b" * 64),
        ), mock.patch.object(
            scan_tool,
            "_validate_external_image_archive",
        ):
            identity = scan_tool.prepare_external_image_archive(
                reference,
                Path(temporary) / "image.tar",
            )
        self.assertEqual(identity["requested_reference"], reference)
        self.assertEqual(identity["requested_digest"], requested_digest)
        self.assertEqual(identity["selected_manifest_digest"], child_digest)
        self.assertEqual(identity["config_digest"], config_digest)
        pulls = [command for command in observed if command[1] == "pull"]
        self.assertEqual(
            pulls,
            [
                [
                    "docker",
                    "pull",
                    "--quiet",
                    "--platform",
                    "linux/amd64",
                    child_reference,
                ]
            ],
        )

    def test_external_scan_uses_private_archive_not_direct_multiarch_reference(self) -> None:
        digest = "sha256:" + "a" * 64
        reference = "example.invalid/release:1@" + digest
        identity = {
            "archive_sha256": "b" * 64,
            "archive_size_bytes": 1024,
            "config_digest": "sha256:" + "c" * 64,
            "platform": "linux/amd64",
            "policy_digest": IMAGE_IDENTITY,
            "requested_digest": digest,
            "requested_reference": reference,
            "selected_manifest_digest": "sha256:" + "d" * 64,
        }
        commands: list[list[str]] = []

        def prepare(_reference, archive):
            archive.write_bytes(b"private archive")
            return identity

        def scan(command, **_kwargs):
            commands.append(list(command))
            output_argument = next(item for item in command if item.startswith("--output-file="))
            Path(output_argument.split("=", 1)[1]).write_text(
                json.dumps({"results": []}),
                encoding="utf-8",
            )
            return 0

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            scan_tool,
            "prepare_external_image_archive",
            side_effect=prepare,
        ), mock.patch.object(scan_tool, "run", side_effect=scan), mock.patch.object(
            scan_tool,
            "run_postgres_runtime_gate",
        ) as runtime_gate:
            root = Path(temporary)
            records: list[dict[str, object]] = []
            scan_tool.scan_external_image(
                Path("/scanner"),
                root,
                root,
                "caddy",
                reference,
                records,
                {
                    "default_action": "deny",
                    "dispositions": [],
                    "format": scan_tool.VULNERABILITY_POLICY_FORMAT,
                },
            )
            self.assertFalse((root / "external-image-caddy.tar").exists())
            runtime_gate.assert_not_called()
        self.assertEqual(len(commands), 1)
        self.assertIn("--archive", commands[0])
        self.assertNotIn(reference, commands[0])
        self.assertEqual(
            records[0]["image_identity"],
            scan_tool._bind_disposition_context("caddy", identity),
        )
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            scan_tool.ScanError,
            "archive is invalid",
        ):
            scan_tool.scan_image(
                Path("/scanner"),
                Path(temporary),
                "postgres",
                reference,
                [],
                None,
                image_identity={"policy_digest": IMAGE_IDENTITY},
            )

    def test_external_archive_rejects_wrong_architecture_and_config_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong_arch = root / "wrong-arch.tar"
            wrong_arch_digest = self._docker_archive(
                wrong_arch,
                architecture="arm64",
            )
            with self.assertRaisesRegex(scan_tool.ScanError, "not linux/amd64"):
                scan_tool._validate_external_image_archive(
                    wrong_arch,
                    wrong_arch_digest,
                )

            valid = root / "valid.tar"
            config_digest = self._docker_archive(valid)
            scan_tool._validate_external_image_archive(valid, config_digest)
            with self.assertRaisesRegex(scan_tool.ScanError, "config identity"):
                scan_tool._validate_external_image_archive(
                    valid,
                    "sha256:" + "f" * 64,
                )

    def test_external_index_ambiguity_and_wrong_runtime_architecture_fail_closed(self) -> None:
        descriptor = {
            "digest": "sha256:" + "a" * 64,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "platform": {"architecture": "amd64", "os": "linux"},
            "size": 100,
        }
        payload = json.dumps(
            {
                "manifests": [descriptor, dict(descriptor, digest="sha256:" + "b" * 64)],
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "schemaVersion": 2,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        with self.assertRaisesRegex(scan_tool.ScanError, "exactly one"):
            scan_tool._select_linux_amd64_manifest(payload, digest)

        inspected = json.dumps(
            [
                {
                    "Architecture": "arm64",
                    "Id": "sha256:" + "c" * 64,
                    "Os": "linux",
                    "RepoDigests": ["example.invalid/release@" + digest],
                }
            ]
        ).encode("utf-8")
        with mock.patch.object(
            scan_tool,
            "run_bounded_capture",
            return_value=inspected,
        ), self.assertRaisesRegex(scan_tool.ScanError, "not linux/amd64"):
            scan_tool._inspect_external_image(
                "example.invalid/release:1@" + digest,
                digest,
                "sha256:" + "d" * 64,
                "sha256:" + "c" * 64,
            )

    def test_external_archive_export_is_no_clobber_and_output_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "image.tar"
            archive.write_bytes(b"operator-owned")
            with self.assertRaises(FileExistsError), mock.patch.object(
                scan_tool,
                "_run_bounded_process",
            ) as runner:
                scan_tool._save_external_image_archive(
                    "example.invalid/release@sha256:" + "a" * 64,
                    archive,
                )
            runner.assert_not_called()
            self.assertEqual(archive.read_bytes(), b"operator-owned")

        with mock.patch.object(
            scan_tool.subprocess,
            "Popen",
            side_effect=OSError,
        ), self.assertRaisesRegex(scan_tool.ScanError, "could not start"):
            scan_tool.run_bounded_capture(
                ["docker", "pull", "image"],
                label="bounded command",
                maximum=1,
                timeout=1,
            )

        with self.assertRaisesRegex(scan_tool.ScanError, "size limit"):
            scan_tool.run_bounded_capture(
                [sys.executable, "-c", "import sys;sys.stdout.write('x'*1024)"],
                label="bounded command",
                maximum=8,
                timeout=5,
            )

    def test_scanner_version_check_uses_the_bounded_group_runner(self) -> None:
        scanner = Path("/reviewed/osv-scanner")
        with mock.patch.object(
            scan_tool,
            "run_bounded_capture",
            return_value=("osv-scanner version " + scan_tool.SCANNER_VERSION).encode(
                "ascii"
            ),
        ) as bounded_runner:
            scan_tool.verify_scanner(scanner)
        bounded_runner.assert_called_once_with(
            [str(scanner), "--version"],
            label="OSV-Scanner version check",
            maximum=4096,
            timeout=30,
        )
        with mock.patch.object(
            scan_tool,
            "run_bounded_capture",
            side_effect=scan_tool.ScanError("secret child failure"),
        ), self.assertRaisesRegex(
            scan_tool.ScanError,
            "version check failed",
        ) as raised:
            scan_tool.verify_scanner(scanner)
        self.assertNotIn("secret", str(raised.exception))

    @unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
    def test_selector_construction_failure_terminates_owned_child(self) -> None:
        real_teardown = scan_tool._terminate_process
        terminated_groups = []

        def teardown(process):
            terminated_groups.append(process.pid)
            return real_teardown(process)

        with mock.patch.object(
            scan_tool.selectors,
            "DefaultSelector",
            side_effect=OSError("file descriptor exhaustion"),
        ), mock.patch.object(
            scan_tool,
            "_terminate_process",
            side_effect=teardown,
        ), self.assertRaisesRegex(OSError, "descriptor exhaustion"):
            scan_tool.run_bounded_capture(
                [sys.executable, "-c", "import time;time.sleep(30)"],
                label="selector construction",
                maximum=1024,
                timeout=5,
            )
        self.assertEqual(len(terminated_groups), 1)
        self.assertTrue(self._wait_for_group_exit(terminated_groups[0]))

    @unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
    def test_run_timeout_kills_sigterm_resistant_descendant_and_reaps_leader(self) -> None:
        descendant = (
            "import os,signal,sys,time;"
            "from pathlib import Path;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "Path(sys.argv[1]).write_text("
            "str(os.getpid())+' '+str(os.getpgrp()),encoding='ascii');"
            "time.sleep(30)"
        )
        leader = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-c',%r,sys.argv[1]]);"
            "time.sleep(30)"
        ) % descendant
        process_group = None
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "descendant.pid"
            try:
                with mock.patch.object(
                    scan_tool,
                    "PROCESS_TERM_GRACE_SECONDS",
                    0.2,
                ), mock.patch.object(
                    scan_tool,
                    "PROCESS_KILL_GRACE_SECONDS",
                    0.5,
                ):
                    code = scan_tool.run(
                        [sys.executable, "-c", leader, str(marker)],
                        timeout=1,
                    )
                self.assertEqual(code, 124)
                self._wait_for_path(marker)
                _descendant_pid, rendered_group = marker.read_text(
                    encoding="ascii"
                ).split()
                process_group = int(rendered_group)
                self.assertGreater(process_group, 1)
                self.assertNotEqual(process_group, os.getpgrp())
                self.assertTrue(self._wait_for_group_exit(process_group))
            finally:
                if (
                    process_group is not None
                    and process_group != os.getpgrp()
                    and scan_tool._process_group_exists(process_group)
                ):
                    os.killpg(process_group, signal.SIGKILL)

    @unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
    def test_sigint_during_popen_publication_cleans_both_runner_shapes(self) -> None:
        child = (
            "import signal,time;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "time.sleep(30)"
        )
        real_popen = subprocess.Popen
        for shape in ("run", "bounded"):
            with self.subTest(shape=shape):
                process_groups: list[int] = []

                def inject_sigint(command, *args, **kwargs):
                    process = real_popen(command, *args, **kwargs)
                    process_groups.append(process.pid)
                    os.kill(os.getpid(), signal.SIGINT)
                    return process

                try:
                    with mock.patch.object(
                        scan_tool.subprocess,
                        "Popen",
                        side_effect=inject_sigint,
                    ), mock.patch.object(
                        scan_tool,
                        "PROCESS_TERM_GRACE_SECONDS",
                        0.1,
                    ), mock.patch.object(
                        scan_tool,
                        "PROCESS_KILL_GRACE_SECONDS",
                        0.5,
                    ), self.assertRaises(KeyboardInterrupt):
                        if shape == "run":
                            scan_tool.run(
                                [sys.executable, "-c", child],
                                timeout=30,
                            )
                        else:
                            scan_tool.run_bounded_capture(
                                [sys.executable, "-c", child],
                                label="publication race",
                                maximum=1024,
                                timeout=30,
                            )
                    self.assertEqual(len(process_groups), 1)
                    self.assertTrue(
                        self._wait_for_group_exit(process_groups[0])
                    )
                    self.assertEqual(
                        signal.getsignal(signal.SIGINT),
                        signal.default_int_handler,
                    )
                finally:
                    for process_group in process_groups:
                        if (
                            process_group != os.getpgrp()
                            and scan_tool._process_group_exists(process_group)
                        ):
                            os.killpg(process_group, signal.SIGKILL)

    @unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
    def test_live_sigint_tears_down_child_before_keyboard_interrupt_exits(self) -> None:
        child = (
            "import os,signal,sys,time;"
            "from pathlib import Path;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "Path(sys.argv[1]).write_text("
            "str(os.getpid())+' '+str(os.getpgrp()),encoding='ascii');"
            "time.sleep(30)"
        )
        controller = None
        child_group = None
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "child.pid"
            controller_code = (
                "import sys;"
                "from tests.release.support import load_script;"
                "m=load_script('dependency_scan_sigint_controller','dependency-scan');"
                "m.PROCESS_TERM_GRACE_SECONDS=0.2;"
                "m.PROCESS_KILL_GRACE_SECONDS=0.5;"
                "m.run([sys.executable,'-c',%r,%r],timeout=30)"
            ) % (child, str(marker))
            try:
                controller = subprocess.Popen(
                    [sys.executable, "-c", controller_code],
                    cwd=str(scan_tool.ROOT),
                    env=dict(
                        os.environ,
                        LC_ALL="C",
                        PYTHONDONTWRITEBYTECODE="1",
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                self._wait_for_path(marker)
                _child_pid, rendered_group = marker.read_text(
                    encoding="ascii"
                ).split()
                child_group = int(rendered_group)
                self.assertNotEqual(child_group, os.getpgrp())
                controller.send_signal(signal.SIGINT)
                controller.wait(timeout=5)
                self.assertNotEqual(controller.returncode, 0)
                self.assertTrue(self._wait_for_group_exit(child_group))
            finally:
                if controller is not None and controller.poll() is None:
                    os.killpg(controller.pid, signal.SIGKILL)
                    controller.wait(timeout=2)
                if (
                    child_group is not None
                    and child_group != os.getpgrp()
                    and scan_tool._process_group_exists(child_group)
                ):
                    os.killpg(child_group, signal.SIGKILL)

    @unittest.skipUnless(
        hasattr(os, "killpg") and hasattr(signal, "SIGHUP"),
        "requires POSIX process groups and SIGHUP",
    )
    def test_live_term_and_hup_exit_only_after_child_group_cleanup(self) -> None:
        child = (
            "import os,signal,sys,time;"
            "from pathlib import Path;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "signal.signal(signal.SIGHUP,signal.SIG_IGN);"
            "Path(sys.argv[1]).write_text("
            "str(os.getpid())+' '+str(os.getpgrp()),encoding='ascii');"
            "time.sleep(30)"
        )
        for selected_signal in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=selected_signal), tempfile.TemporaryDirectory() as temporary:
                controller = None
                child_group = None
                marker = Path(temporary) / "child.pid"
                controller_code = (
                    "import sys;"
                    "from tests.release.support import load_script;"
                    "m=load_script('dependency_scan_term_controller','dependency-scan');"
                    "m.PROCESS_TERM_GRACE_SECONDS=0.2;"
                    "m.PROCESS_KILL_GRACE_SECONDS=0.5;"
                    "m.run([sys.executable,'-c',%r,%r],timeout=30)"
                ) % (child, str(marker))
                try:
                    controller = subprocess.Popen(
                        [sys.executable, "-c", controller_code],
                        cwd=str(scan_tool.ROOT),
                        env=dict(
                            os.environ,
                            LC_ALL="C",
                            PYTHONDONTWRITEBYTECODE="1",
                        ),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    self._wait_for_path(marker)
                    _child_pid, rendered_group = marker.read_text(
                        encoding="ascii"
                    ).split()
                    child_group = int(rendered_group)
                    self.assertNotEqual(child_group, os.getpgrp())
                    controller.send_signal(selected_signal)
                    controller.wait(timeout=5)
                    self.assertEqual(
                        controller.returncode,
                        128 + int(selected_signal),
                    )
                    self.assertTrue(self._wait_for_group_exit(child_group))
                finally:
                    if controller is not None and controller.poll() is None:
                        os.killpg(controller.pid, signal.SIGKILL)
                        controller.wait(timeout=2)
                    if (
                        child_group is not None
                        and child_group != os.getpgrp()
                        and scan_tool._process_group_exists(child_group)
                    ):
                        os.killpg(child_group, signal.SIGKILL)

    def test_local_archive_identity_binds_config_labels_revision_and_recipe(self) -> None:
        recipe = "sha256:" + "b" * 64
        revision = "c" * 40
        labels = {
            "io.hbcb.recipe-id": recipe,
            "org.opencontainers.image.revision": revision,
        }
        image_id = "sha256:" + "a" * 64
        reference = scan_tool.local_image_references("1" * 24)[1][1]
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "minio.tar"
            config_digest = self._docker_archive(archive, labels=labels)
            inspect_payload = json.dumps(
                [
                    {
                        "Architecture": "amd64",
                        "Config": {"Labels": labels},
                        "Descriptor": {"digest": image_id},
                        "Id": image_id,
                        "Os": "linux",
                    }
                ]
            ).encode("utf-8")
            with mock.patch.object(
                scan_tool,
                "run_bounded_capture",
                return_value=inspect_payload,
            ), mock.patch.object(
                scan_tool,
                "_save_external_image_archive",
                return_value=(archive.stat().st_size, "d" * 64),
            ) as exporter:
                identity = scan_tool.prepare_local_image_archive(
                    reference,
                    "minio",
                    archive,
                    recipe,
                )
            exporter.assert_called_once_with(image_id, archive)
        self.assertEqual(identity["build_reference"], reference)
        self.assertEqual(identity["image_id"], image_id)
        self.assertEqual(identity["descriptor_digest"], image_id)
        self.assertEqual(identity["config_digest"], config_digest)
        self.assertEqual(identity["oci_revision"], revision)
        self.assertEqual(identity["recipe_id"], recipe)
        self.assertRegex(identity["policy_digest"], r"^sha256:[0-9a-f]{64}$")

        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "minio.tar"
            self._docker_archive(archive, labels=labels)
            with mock.patch.object(
                scan_tool,
                "run_bounded_capture",
                return_value=inspect_payload,
            ), mock.patch.object(
                scan_tool,
                "_save_external_image_archive",
                return_value=(archive.stat().st_size, "e" * 64),
            ), self.assertRaisesRegex(scan_tool.ScanError, "recipe identity did not match"):
                scan_tool.prepare_local_image_archive(
                    reference,
                    "minio",
                    archive,
                    "sha256:" + "f" * 64,
                )

        mutated = dict(labels, **{"io.hbcb.recipe-id": "sha256:" + "e" * 64})
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "minio.tar"
            self._docker_archive(archive, labels=mutated)
            with mock.patch.object(
                scan_tool,
                "run_bounded_capture",
                return_value=inspect_payload,
            ), mock.patch.object(
                scan_tool,
                "_save_external_image_archive",
                return_value=(archive.stat().st_size, "f" * 64),
            ), self.assertRaisesRegex(scan_tool.ScanError, "labels did not match"):
                scan_tool.prepare_local_image_archive(
                    reference,
                    "minio",
                    archive,
                    recipe,
                )

    def test_all_local_scans_use_private_archives_not_mutable_tags(self) -> None:
        recipe = "sha256:" + "c" * 64
        identity = {
            "config_digest": "sha256:" + "a" * 64,
            "image_id": "sha256:" + "d" * 64,
            "oci_revision": "b" * 40,
            "platform": "linux/amd64",
            "policy_digest": IMAGE_IDENTITY,
        }
        commands: list[list[str]] = []
        prepared = []

        def prepare(reference, identifier, archive, expected_recipe):
            prepared.append((reference, identifier, expected_recipe))
            archive.write_bytes(("private " + identifier + " archive").encode("ascii"))
            return dict(identity, build_reference=reference)

        def scan(command, **_kwargs):
            commands.append(list(command))
            output_argument = next(item for item in command if item.startswith("--output-file="))
            Path(output_argument.split("=", 1)[1]).write_text(
                json.dumps({"results": []}),
                encoding="utf-8",
            )
            return 0

        local_images = scan_tool.local_image_references("2" * 24)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            scan_tool,
            "prepare_local_image_archive",
            side_effect=prepare,
        ), mock.patch.object(scan_tool, "run", side_effect=scan), mock.patch.object(
            scan_tool,
            "run_postgres_runtime_gate",
        ) as postgres_gate:
            root = Path(temporary)
            records: list[dict[str, object]] = []
            for identifier, reference in local_images:
                scan_tool.scan_local_image(
                    Path("/scanner"),
                    root,
                    root,
                    identifier,
                    reference,
                    records,
                    {
                        "default_action": "deny",
                        "dispositions": [],
                        "format": scan_tool.VULNERABILITY_POLICY_FORMAT,
                    },
                    recipe,
                )
                self.assertFalse((root / ("local-image-" + identifier + ".tar")).exists())
        self.assertEqual(len(commands), len(scan_tool.LOCAL_IMAGE_IDS))
        postgres_gate.assert_called_once_with(
            identity["image_id"], identity["config_digest"], mock.ANY
        )
        for command, (identifier, reference) in zip(commands, local_images):
            self.assertIn("--archive", command)
            self.assertNotIn(reference, command)
            archive_argument = command[command.index("--archive") + 1]
            self.assertTrue(archive_argument.endswith("local-image-" + identifier + ".tar"))
        self.assertEqual(
            prepared,
            [
                (reference, identifier, recipe if identifier == "minio" else None)
                for identifier, reference in local_images
            ],
        )
        self.assertEqual(len(records), len(scan_tool.LOCAL_IMAGE_IDS))

    def test_postgres_local_scan_requires_runnable_and_archive_config_ids(self) -> None:
        valid_identity = {
            "config_digest": "sha256:" + "a" * 64,
            "image_id": "sha256:" + "b" * 64,
            "policy_digest": IMAGE_IDENTITY,
        }
        for field, value in (("config_digest", None), ("image_id", "latest")):
            identity = dict(valid_identity)
            if value is None:
                identity.pop(field)
            else:
                identity[field] = value

            def prepare(_reference, _identifier, archive, _expected_recipe):
                archive.write_bytes(b"private postgres archive")
                return identity

            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with mock.patch.object(
                    scan_tool,
                    "prepare_local_image_archive",
                    side_effect=prepare,
                ), mock.patch.object(scan_tool, "scan_image"), mock.patch.object(
                    scan_tool, "run_postgres_runtime_gate"
                ) as gate, self.assertRaisesRegex(
                    scan_tool.ScanError, "immutable image identities are unavailable"
                ):
                    scan_tool.scan_local_image(
                        Path("/scanner"),
                        root,
                        root,
                        "postgres",
                        "hbcb-postgres-local:test",
                        [],
                        {
                            "default_action": "deny",
                            "dispositions": [],
                            "format": scan_tool.VULNERABILITY_POLICY_FORMAT,
                        },
                        "sha256:" + "c" * 64,
                    )
                gate.assert_not_called()
                self.assertFalse((root / "local-image-postgres.tar").exists())

    def test_local_archive_export_uses_inspected_id_after_simulated_retag(self) -> None:
        labels = {"org.opencontainers.image.revision": "uncommitted"}
        first_id = "sha256:" + "a" * 64
        retagged_id = "sha256:" + "b" * 64
        current_id = [first_id]
        saved = []

        def inspect(_command, **_kwargs):
            captured = current_id[0]
            current_id[0] = retagged_id
            return json.dumps(
                [
                    {
                        "Architecture": "amd64",
                        "Config": {"Labels": labels},
                        "Descriptor": {"digest": captured},
                        "Id": captured,
                        "Os": "linux",
                    }
                ]
            ).encode("utf-8")

        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "builder.tar"
            self._docker_archive(archive, labels=labels)

            def export(reference, _archive):
                saved.append(reference)
                return archive.stat().st_size, "d" * 64

            with mock.patch.object(
                scan_tool,
                "run_bounded_capture",
                side_effect=inspect,
            ), mock.patch.object(
                scan_tool,
                "_save_external_image_archive",
                side_effect=export,
            ):
                scan_tool.prepare_local_image_archive(
                    scan_tool.local_image_references("3" * 24)[0][1],
                    "builder",
                    archive,
                    None,
                )
        self.assertEqual(current_id[0], retagged_id)
        self.assertEqual(saved, [first_id])

    def test_local_archive_rejects_wrong_architecture(self) -> None:
        labels = {"org.opencontainers.image.revision": "uncommitted"}
        image_id = "sha256:" + "a" * 64
        inspect_payload = json.dumps(
            [
                {
                    "Architecture": "amd64",
                    "Config": {"Labels": labels},
                    "Descriptor": {"digest": image_id},
                    "Id": image_id,
                    "Os": "linux",
                }
            ]
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "builder.tar"
            self._docker_archive(
                archive,
                architecture="arm64",
                labels=labels,
            )
            with mock.patch.object(
                scan_tool,
                "run_bounded_capture",
                return_value=inspect_payload,
            ), mock.patch.object(
                scan_tool,
                "_save_external_image_archive",
                return_value=(archive.stat().st_size, "c" * 64),
            ), self.assertRaisesRegex(scan_tool.ScanError, "not linux/amd64"):
                scan_tool.prepare_local_image_archive(
                    scan_tool.local_image_references("4" * 24)[0][1],
                    "builder",
                    archive,
                    None,
                )

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
                json.dumps(
                    {
                        "results": [
                            {
                                "packages": [],
                                "source": {"detail": "x" * (5 * 1024 * 1024)},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                scan_tool.validate_scan_report(report, 1),
                (1, "postgres.json"),
            )
            self.assertLessEqual(report.stat().st_size, scan_tool.MAX_OSV_REPORT_BYTES)

    def test_every_requested_scan_target_is_recorded_when_not_run(self) -> None:
        records: list[dict[str, object]] = []
        scan_tool.record_unrun_scans(records, True, ())
        identifiers = {str(item["id"]) for item in records}
        self.assertEqual(
            identifiers,
            {
                "osv-source",
                "osv-image-api",
                "osv-image-builder",
                "osv-image-caddy",
                "osv-image-minio",
                "osv-image-postgres",
                "osv-image-worker",
                "postgres-runtime-security",
            },
        )
        self.assertTrue(all(item["status"] == "incomplete" for item in records))
        self.assertEqual(scan_tool.final_status(records, []), "incomplete")

    def test_postgres_runtime_gate_is_exact_and_fails_closed(self) -> None:
        runtime_image_id = "sha256:" + "a" * 64
        linux_amd64_config_id = "sha256:" + "b" * 64
        records: list[dict[str, object]] = []
        commands: list[tuple[list[str], int, float]] = []

        def passed(command, **kwargs):
            commands.append(
                (
                    list(command),
                    kwargs["timeout"],
                    kwargs["termination_grace_seconds"],
                )
            )
            return 0

        with mock.patch.object(scan_tool, "run", side_effect=passed):
            scan_tool.run_postgres_runtime_gate(
                runtime_image_id, linux_amd64_config_id, records
            )
        self.assertEqual(
            commands,
            [
                (
                    [
                        sys.executable,
                        str(
                            scan_tool.ROOT
                            / "tests/security/postgres_fixture_gate.py"
                        ),
                        "--docker",
                        "docker",
                        "--image",
                        runtime_image_id,
                        "--config-id",
                        linux_amd64_config_id,
                    ],
                    900,
                    scan_tool.POSTGRES_GATE_TERM_GRACE_SECONDS,
                )
            ],
        )
        self.assertEqual(records[0]["status"], "pass")
        self.assertEqual(records[0]["type"], "runtime-security-gate")

        records = []
        with mock.patch.object(scan_tool, "run", return_value=1):
            scan_tool.run_postgres_runtime_gate(
                runtime_image_id, linux_amd64_config_id, records
            )
        self.assertEqual(records[0]["status"], "incomplete")
        self.assertEqual(scan_tool.final_status(records, []), "incomplete")

    def test_advisory_alias_family_is_one_blocking_high_finding(self) -> None:
        report = advisory_report()
        normalized = scan_tool.normalize_vulnerability_report(
            report,
            "osv-image-minio",
        )
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["severity"], "HIGH")
        self.assertEqual(
            normalized[0]["advisory_family"],
            ["CVE-2026-1234", "GHSA-AAAA-BBBB-CCCC", "GO-2026-1234"],
        )
        assessment = scan_tool.evaluate_vulnerability_report(
            report,
            "osv-image-minio",
            {
                "default_action": "deny",
                "dispositions": [],
                "format": scan_tool.VULNERABILITY_POLICY_FORMAT,
            },
            IMAGE_IDENTITY,
        )
        self.assertEqual(assessment["status"], "findings")
        self.assertEqual(assessment["blocking"], 1)
        self.assertEqual(assessment["severity"]["HIGH"], 1)

    def test_generic_urgency_never_downgrades_the_group_cvss_score(self) -> None:
        report = advisory_report("8.1")
        affected = report["results"][0]["packages"][0]["vulnerabilities"][0][
            "affected"
        ][0]
        affected["ecosystem_specific"] = {"urgency": "not affected"}
        normalized = scan_tool.normalize_vulnerability_report(
            report,
            "osv-image-docker-base",
        )
        self.assertEqual(normalized[0]["score"], "8.1")
        self.assertEqual(normalized[0]["severity"], "HIGH")

    def test_exact_debian_unimportant_vendor_analysis_overrides_generic_cvss(self) -> None:
        report = {
            "results": [
                {
                    "packages": [
                        {
                            "groups": [
                                {
                                    "aliases": ["CVE-2026-1234", "DEBIAN-CVE-2026-1234"],
                                    "ids": ["DEBIAN-CVE-2026-1234"],
                                    "max_severity": "9.8",
                                }
                            ],
                            "package": {
                                "ecosystem": "Debian:12",
                                "name": "glibc",
                                "version": "2.36-9+deb12u14",
                            },
                            "vulnerabilities": [
                                {
                                    "affected": [
                                        {
                                            "ecosystem_specific": {"urgency": "unimportant"},
                                            "package": {
                                                "ecosystem": "Debian:12",
                                                "name": "glibc",
                                            },
                                        }
                                    ],
                                    "aliases": ["CVE-2026-1234"],
                                    "id": "DEBIAN-CVE-2026-1234",
                                }
                            ],
                        }
                    ]
                }
            ]
        }
        normalized = scan_tool.normalize_vulnerability_report(
            report,
            "osv-image-docker-base",
        )
        self.assertEqual(normalized[0]["score"], "9.8")
        self.assertEqual(normalized[0]["severity"], "LOW")

        report["results"][0]["packages"][0]["vulnerabilities"][0]["affected"][0][
            "ecosystem_specific"
        ]["urgency"] = "not yet assigned"
        normalized = scan_tool.normalize_vulnerability_report(
            report,
            "osv-image-docker-base",
        )
        self.assertEqual(normalized[0]["severity"], "CRITICAL")

        del report["results"][0]["packages"][0]["vulnerabilities"][0][
            "affected"
        ][0]["ecosystem_specific"]
        normalized = scan_tool.normalize_vulnerability_report(
            report,
            "osv-image-docker-base",
        )
        self.assertEqual(normalized[0]["severity"], "CRITICAL")

        report["results"][0]["packages"][0]["vulnerabilities"][0][
            "affected"
        ][0]["ecosystem_specific"] = {"urgency": "unimportant"}
        report["results"][0]["packages"][0]["vulnerabilities"][0][
            "affected"
        ].append(
            {
                "ecosystem_specific": {"urgency": "not yet assigned"},
                "package": {
                    "ecosystem": "Debian:12",
                    "name": "glibc",
                },
            }
        )
        normalized = scan_tool.normalize_vulnerability_report(
            report,
            "osv-image-docker-base",
        )
        self.assertEqual(normalized[0]["severity"], "CRITICAL")

    def test_custom_ecosystem_fixed_versions_are_part_of_exact_identity(self) -> None:
        advisory = {
            "affected": [
                {
                    "ecosystem_specific": {
                        "custom_ranges": [
                            {
                                "events": [
                                    {"introduced": "RELEASE.2024-01-01"},
                                    {"fixed": "RELEASE.2025-02-28"},
                                ],
                                "type": "ECOSYSTEM",
                            }
                        ]
                    },
                    "package": {
                        "ecosystem": "Go",
                        "name": "example.invalid/module",
                    },
                    "ranges": [],
                }
            ]
        }
        package = {
            "ecosystem": "Go",
            "name": "example.invalid/module",
            "version": "(devel)",
        }
        self.assertEqual(
            scan_tool._matching_fixed_versions(advisory, package),
            {"RELEASE.2025-02-28"},
        )
        advisory["affected"][0]["ecosystem_specific"]["custom_ranges"] = "bad"
        with self.assertRaises(scan_tool.ScanError):
            scan_tool._matching_fixed_versions(advisory, package)

    def test_exact_unexpired_static_evidence_disposition_reviews_high(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "docs" / "review.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("Reviewed runtime mitigation evidence.\n", encoding="utf-8")
            disposition = exact_disposition(
                hashlib.sha256(evidence.read_bytes()).hexdigest()
            )
            write_policy(root, [disposition])
            policy = scan_tool.load_vulnerability_policy(
                root,
                today=date(2026, 8, 12),
            )
            assessment = scan_tool.evaluate_vulnerability_report(
                advisory_report(),
                "osv-image-minio",
                policy,
                IMAGE_IDENTITY,
            )
            self.assertEqual(assessment["status"], "pass")
            self.assertEqual(assessment["blocking"], 0)
            self.assertEqual(assessment["dispositioned"], 1)

    def test_disposition_is_exact_across_target_package_version_revision_and_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "docs" / "review.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("Reviewed runtime mitigation evidence.\n", encoding="utf-8")
            digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
            mutations = (
                ("target", lambda item: item.update(target="osv-image-worker")),
                (
                    "package name",
                    lambda item: item["package"].update(name="example.invalid/other"),
                ),
                (
                    "package version",
                    lambda item: item["package"].update(version="1.2.4"),
                ),
                (
                    "source revision",
                    lambda item: item["package"].update(source_revision="def456"),
                ),
                (
                    "image identity",
                    lambda item: item.update(image_identity="sha256:" + "8" * 64),
                ),
                ("severity", lambda item: item.update(severity="CRITICAL")),
                ("score", lambda item: item.update(score="8.2")),
                (
                    "fixed versions",
                    lambda item: item["fixed_versions"].append("1.2.5"),
                ),
                (
                    "advisory family",
                    lambda item: item["advisory_family"].append("OSV-EXTRA-1"),
                ),
            )
            for label, mutate in mutations:
                with self.subTest(label=label):
                    disposition = exact_disposition(digest)
                    mutate(disposition)
                    if label == "advisory family":
                        disposition["advisory_family"].sort()
                    write_policy(root, [disposition])
                    policy = scan_tool.load_vulnerability_policy(
                        root,
                        today=date(2026, 8, 12),
                    )
                    assessment = scan_tool.evaluate_vulnerability_report(
                        advisory_report(),
                        "osv-image-minio",
                        policy,
                        IMAGE_IDENTITY,
                    )
                    self.assertEqual(assessment["status"], "findings")
                    self.assertEqual(assessment["blocking"], 1)

    def test_policy_expiry_digest_schema_and_review_window_mutations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "docs" / "review.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("Reviewed runtime mitigation evidence.\n", encoding="utf-8")
            digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
            mutations = (
                ("expired", lambda item: item.update(expires_on="2026-08-11")),
                ("expiry boundary", lambda item: item.update(expires_on="2026-08-12")),
                ("too long", lambda item: item.update(expires_on="2026-12-31")),
                (
                    "stale digest",
                    lambda item: item["evidence"][0].update(sha256="0" * 64),
                ),
                ("wildcard target", lambda item: item.update(target="osv-image-*")),
                ("unknown target", lambda item: item.update(target="osv-image-unknown")),
                ("typed severity", lambda item: item.update(severity=["HIGH"])),
                ("missing image identity", lambda item: item.pop("image_identity")),
                ("mutable image identity", lambda item: item.update(image_identity="latest")),
                (
                    "typed evidence path",
                    lambda item: item["evidence"][0].update(path=["docs/review.md"]),
                ),
                ("extra field", lambda item: item.update(unreviewed=True)),
            )
            for label, mutate in mutations:
                with self.subTest(label=label):
                    disposition = exact_disposition(digest)
                    mutate(disposition)
                    write_policy(root, [disposition])
                    with self.assertRaises(scan_tool.ScanError):
                        scan_tool.load_vulnerability_policy(
                            root,
                            today=date(2026, 8, 12),
                        )

            policy_path = root / "release" / "vulnerability-policy.json"
            policy_path.write_text(
                '{"dispositions":[],"format":"hbcb-vulnerability-policy/v1",'
                '"format":"hbcb-vulnerability-policy/v1"}',
                encoding="utf-8",
            )
            with self.assertRaises(scan_tool.ScanError):
                scan_tool.load_vulnerability_policy(root, today=date(2026, 8, 12))
            policy_path.write_text(
                '{"dispositions":NaN,"format":"hbcb-vulnerability-policy/v1"}',
                encoding="utf-8",
            )
            with self.assertRaises(scan_tool.ScanError):
                scan_tool.load_vulnerability_policy(root, today=date(2026, 8, 12))

    def test_lower_findings_remain_visible_while_unrated_fails_closed(self) -> None:
        report = advisory_report("3.8")
        package = report["results"][0]["packages"][0]
        package["groups"].append(
            {
                "aliases": ["OSV-UNRATED-1"],
                "ids": ["OSV-UNRATED-1"],
                "max_severity": "",
            }
        )
        package["vulnerabilities"].append({"id": "OSV-UNRATED-1"})
        package["vulnerabilities"][1]["database_specific"]["severity"] = "LOW"
        policy = {
            "default_action": "deny",
            "dispositions": [],
            "format": scan_tool.VULNERABILITY_POLICY_FORMAT,
        }
        assessment = scan_tool.evaluate_vulnerability_report(
            report,
            "osv-image-minio",
            policy,
            IMAGE_IDENTITY,
        )
        self.assertEqual(assessment["status"], "findings")
        self.assertEqual(assessment["families"], 2)
        self.assertEqual(assessment["blocking"], 1)
        self.assertEqual(assessment["severity"]["LOW"], 1)
        self.assertEqual(assessment["severity"]["UNRATED"], 1)
        rendered = scan_tool.render_summary(
            {
                "status": "findings",
                "targets": [
                    {
                        "exit_code": 1,
                        "id": "osv-image-minio",
                        "status": "findings",
                        "type": "vulnerability-scan",
                        "vulnerabilities": assessment,
                    }
                ],
            }
        )
        self.assertIn("unrated=1", rendered)
        self.assertIn("low=1", rendered)
        self.assertIn("moderate=0", rendered)

    def test_malformed_or_incompletely_grouped_report_fails_closed(self) -> None:
        mutations = (
            lambda package: package.update(groups=[]),
            lambda package: package["groups"][0].update(max_severity="NaN"),
            lambda package: package["groups"][0].update(ids=["UNKNOWN-1"]),
            lambda package: package["groups"][0].update(aliases=["GO-2026-1234"]),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                report = advisory_report()
                mutate(report["results"][0]["packages"][0])
                with self.assertRaises(scan_tool.ScanError):
                    scan_tool.normalize_vulnerability_report(
                        report,
                        "osv-image-minio",
                    )

        conflicting = advisory_report()
        duplicate = json.loads(json.dumps(conflicting["results"][0]["packages"][0]))
        duplicate["groups"][0]["max_severity"] = "9.1"
        conflicting["results"][0]["packages"].append(duplicate)
        with self.assertRaisesRegex(scan_tool.ScanError, "snapshot conflicts"):
            scan_tool.normalize_vulnerability_report(
                conflicting,
                "osv-image-minio",
            )

    def test_scanner_exit_and_report_findings_must_agree_and_raw_report_is_retained(self) -> None:
        policy = {
            "default_action": "deny",
            "dispositions": [],
            "format": scan_tool.VULNERABILITY_POLICY_FORMAT,
        }
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "raw.json"
            report.write_text(json.dumps(advisory_report()), encoding="utf-8")
            before = report.read_bytes()
            status, assessment = scan_tool.assess_retained_scan(
                report,
                0,
                "osv-image-minio",
                policy,
                IMAGE_IDENTITY,
            )
            self.assertEqual((status, assessment), ("incomplete", None))
            status, assessment = scan_tool.assess_retained_scan(
                report,
                1,
                "osv-image-minio",
                policy,
                IMAGE_IDENTITY,
            )
            self.assertEqual(status, "findings")
            self.assertIsNotNone(assessment)
            self.assertEqual(report.read_bytes(), before)

    def test_image_scan_keeps_raw_exit_one_but_passes_lower_policy_result(self) -> None:
        policy = {
            "default_action": "deny",
            "dispositions": [],
            "format": scan_tool.VULNERABILITY_POLICY_FORMAT,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            archive = output / "minio.tar"
            archive.write_bytes(b"validated image archive")
            report = advisory_report("3.8")
            report["results"][0]["packages"][0]["vulnerabilities"][1][
                "database_specific"
            ]["severity"] = "LOW"
            (output / "osv-image-minio.json").write_text(
                json.dumps(report),
                encoding="utf-8",
            )
            records: list[dict[str, object]] = []
            with mock.patch.object(scan_tool, "run", return_value=1):
                scan_tool.scan_image(
                    Path("/scanner"),
                    output,
                    "minio",
                    archive,
                    records,
                    policy,
                    image_identity={"policy_digest": IMAGE_IDENTITY},
                )
            self.assertEqual(records[0]["exit_code"], 1)
            self.assertEqual(records[0]["status"], "pass")
            self.assertEqual(records[0]["vulnerabilities"]["severity"]["LOW"], 1)
            self.assertTrue((output / "osv-image-minio.json").is_file())

    def test_unused_disposition_is_a_policy_finding_for_an_evaluated_target(self) -> None:
        disposition = exact_disposition("0" * 64)
        policy = {
            "default_action": "deny",
            "dispositions": [disposition],
            "format": scan_tool.VULNERABILITY_POLICY_FORMAT,
        }
        records = [
            {
                "id": "osv-image-minio",
                "status": "pass",
                "vulnerabilities": {"dispositioned": 0},
            }
        ]
        summary = {"status": "pass"}
        scan_tool.reconcile_policy_dispositions(records, policy, summary)
        self.assertEqual(summary["unused"], 1)
        self.assertEqual(summary["status"], "findings")
        self.assertEqual(records[-1]["id"], "vulnerability-policy-dispositions")

        matched_records = [
            {
                "id": "osv-image-minio",
                "status": "pass",
                "vulnerabilities": {"dispositioned": 1},
            }
        ]
        matched_summary = {"status": "pass"}
        scan_tool.reconcile_policy_dispositions(
            matched_records,
            policy,
            matched_summary,
        )
        self.assertEqual(matched_summary["unused"], 0)
        self.assertEqual(matched_summary["status"], "pass")
        self.assertEqual(len(matched_records), 1)

    def test_parallel_run_tags_are_disjoint_and_builds_stay_within_one_run(self) -> None:
        commands: list[list[str]] = []

        def capture(command, **_kwargs):
            commands.append(list(command))
            return 0

        first = scan_tool.local_image_references("a" * 24)
        second = scan_tool.local_image_references("b" * 24)
        self.assertFalse(
            {reference for _identifier, reference in first}
            & {reference for _identifier, reference in second}
        )
        records: list[dict[str, object]] = []
        attempted: list[str] = []
        recipe = "sha256:" + "c" * 64
        with mock.patch.object(scan_tool, "run", side_effect=capture):
            self.assertTrue(
                scan_tool.build_images(records, first, recipe, attempted)
            )
        self.assertEqual(len(commands), len(scan_tool.LOCAL_IMAGE_IDS))
        first_references = dict(first)
        second_references = {reference for _identifier, reference in second}
        for identifier, command in zip(scan_tool.LOCAL_IMAGE_IDS, commands):
            self.assertEqual(command.count("--tag"), 1)
            tag_index = command.index("--tag")
            self.assertEqual(command[tag_index + 1], first_references[identifier])
            self.assertFalse(set(command) & second_references)
        self.assertEqual(attempted, list(scan_tool.LOCAL_IMAGE_IDS))
        service_commands = [
            command
            for command in commands
            if "docker/service.Dockerfile" in command
        ]
        self.assertEqual(len(service_commands), 2)
        for command in service_commands:
            self.assertIn("HBCB_BUILDER_IMAGE=" + first_references["builder"], command)
        minio = next(command for command in commands if "docker/minio.Dockerfile" in command)
        self.assertIn("HBCB_MINIO_RECIPE_ID=" + recipe, minio)
        postgres = next(
            command for command in commands if "docker/postgres.Dockerfile" in command
        )
        self.assertEqual(postgres[postgres.index("--target") + 1], "postgres")
        caddy = next(
            command for command in commands if "docker/caddy.Dockerfile" in command
        )
        self.assertEqual(caddy[caddy.index("--target") + 1], "caddy")

    def test_parallel_build_references_do_not_change_local_policy_identity(self) -> None:
        labels = {"org.opencontainers.image.revision": "uncommitted"}
        first_reference = scan_tool.local_image_references("d" * 24)[0][1]
        second_reference = scan_tool.local_image_references("e" * 24)[0][1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_archive = root / "first.tar"
            second_archive = root / "second.tar"
            config_digest = self._docker_archive(first_archive, labels=labels)
            self._docker_archive(second_archive, labels=labels)
            inspect_payload = json.dumps(
                [
                    {
                        "Architecture": "amd64",
                        "Config": {"Labels": labels},
                        "Id": config_digest,
                        "Os": "linux",
                    }
                ]
            ).encode("utf-8")
            with mock.patch.object(
                scan_tool,
                "run_bounded_capture",
                return_value=inspect_payload,
            ), mock.patch.object(
                scan_tool,
                "_save_external_image_archive",
                side_effect=[
                    (first_archive.stat().st_size, "1" * 64),
                    (second_archive.stat().st_size, "2" * 64),
                ],
            ):
                first_identity = scan_tool.prepare_local_image_archive(
                    first_reference,
                    "builder",
                    first_archive,
                    None,
                )
                second_identity = scan_tool.prepare_local_image_archive(
                    second_reference,
                    "builder",
                    second_archive,
                    None,
                )
        self.assertNotEqual(
            first_identity["build_reference"],
            second_identity["build_reference"],
        )
        self.assertNotEqual(
            first_identity["archive_sha256"],
            second_identity["archive_sha256"],
        )
        self.assertEqual(
            first_identity["policy_digest"],
            second_identity["policy_digest"],
        )

    def test_local_policy_identity_ignores_timestamps_but_binds_runtime_content(self) -> None:
        labels = {"org.opencontainers.image.revision": "uncommitted"}

        def write_archive(path: Path, created: str, mtime: int, payload: bytes) -> str:
            layer_buffer = io.BytesIO()
            with tarfile.open(fileobj=layer_buffer, mode="w") as layer:
                member = tarfile.TarInfo("usr/local/bin/example")
                member.mode = 0o555
                member.mtime = mtime
                member.size = len(payload)
                layer.addfile(member, io.BytesIO(payload))
            layer_payload = layer_buffer.getvalue()
            layer_name = "layer.tar"
            config_payload = json.dumps(
                {
                    "architecture": "amd64",
                    "config": {
                        "Entrypoint": ["/usr/local/bin/example"],
                        "Labels": labels,
                        "User": "65532:65532",
                    },
                    "created": created,
                    "history": [{"created": created}],
                    "os": "linux",
                },
                separators=(",", ":"),
            ).encode("utf-8")
            config_digest = "sha256:" + hashlib.sha256(config_payload).hexdigest()
            config_name = config_digest.removeprefix("sha256:") + ".json"
            manifest_payload = json.dumps(
                [{"Config": config_name, "Layers": [layer_name], "RepoTags": None}],
                separators=(",", ":"),
            ).encode("utf-8")
            with tarfile.open(path, "w") as archive:
                for name, value in (
                    (config_name, config_payload),
                    (layer_name, layer_payload),
                    ("manifest.json", manifest_payload),
                ):
                    member = tarfile.TarInfo(name)
                    member.mode = 0o600
                    member.size = len(value)
                    archive.addfile(member, io.BytesIO(value))
            return config_digest

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_archive = root / "first.tar"
            second_archive = root / "second.tar"
            changed_archive = root / "changed.tar"
            first_config = write_archive(
                first_archive, "2026-08-12T12:00:00Z", 1, b"same bytes"
            )
            second_config = write_archive(
                second_archive, "2026-08-12T13:00:00Z", 2, b"same bytes"
            )
            changed_config = write_archive(
                changed_archive, "2026-08-12T14:00:00Z", 3, b"changed bytes"
            )

            def inspected(config_digest: str) -> bytes:
                return json.dumps(
                    [
                        {
                            "Architecture": "amd64",
                            "Config": {"Labels": labels},
                            "Id": config_digest,
                            "Os": "linux",
                        }
                    ]
                ).encode("utf-8")

            identities = []
            for reference, archive, config_digest in (
                ("example:first", first_archive, first_config),
                ("example:second", second_archive, second_config),
                ("example:changed", changed_archive, changed_config),
            ):
                with mock.patch.object(
                    scan_tool,
                    "run_bounded_capture",
                    return_value=inspected(config_digest),
                ), mock.patch.object(
                    scan_tool,
                    "_save_external_image_archive",
                    return_value=(archive.stat().st_size, "a" * 64),
                ):
                    identities.append(
                        scan_tool.prepare_local_image_archive(
                            reference,
                            "builder",
                            archive,
                            None,
                        )
                    )

        self.assertNotEqual(identities[0]["config_digest"], identities[1]["config_digest"])
        self.assertEqual(identities[0]["content_digest"], identities[1]["content_digest"])
        self.assertEqual(
            identities[0]["runtime_config_digest"],
            identities[1]["runtime_config_digest"],
        )
        self.assertEqual(identities[0]["policy_digest"], identities[1]["policy_digest"])
        self.assertNotEqual(identities[1]["content_digest"], identities[2]["content_digest"])
        self.assertNotEqual(identities[1]["policy_digest"], identities[2]["policy_digest"])

    def test_local_content_identity_binds_runtime_metadata_and_layer_order(self) -> None:
        baseline_layers = [
            [
                {
                    "devmajor": 0,
                    "devminor": 0,
                    "gid": 20,
                    "linkname": "",
                    "mode": 0o555,
                    "name": "usr/local/bin/example",
                    "pax_headers": {"HBCB.test": "one"},
                    "payload": b"reviewed runtime bytes",
                    "type": tarfile.REGTYPE,
                    "uid": 10,
                },
                {
                    "devmajor": 0,
                    "devminor": 0,
                    "gid": 21,
                    "linkname": "example",
                    "mode": 0o777,
                    "name": "usr/local/bin/example-link",
                    "pax_headers": {},
                    "payload": b"",
                    "type": tarfile.SYMTYPE,
                    "uid": 11,
                },
                {
                    "devmajor": 1,
                    "devminor": 7,
                    "gid": 22,
                    "linkname": "",
                    "mode": 0o600,
                    "name": "dev/example",
                    "pax_headers": {},
                    "payload": b"",
                    "type": tarfile.CHRTYPE,
                    "uid": 12,
                },
            ],
            [
                {
                    "devmajor": 0,
                    "devminor": 0,
                    "gid": 23,
                    "linkname": "",
                    "mode": 0o444,
                    "name": "etc/example.conf",
                    "pax_headers": {},
                    "payload": b"enabled=true\n",
                    "type": tarfile.REGTYPE,
                    "uid": 13,
                }
            ],
        ]

        def write_archive(path: Path, layers: list[list[dict[str, object]]]) -> None:
            layer_payloads = []
            for index, specs in enumerate(layers):
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as layer:
                    for spec in specs:
                        member = tarfile.TarInfo(str(spec["name"]))
                        member.type = spec["type"]
                        member.mode = int(spec["mode"])
                        member.uid = int(spec["uid"])
                        member.gid = int(spec["gid"])
                        member.linkname = str(spec["linkname"])
                        member.devmajor = int(spec["devmajor"])
                        member.devminor = int(spec["devminor"])
                        member.pax_headers = dict(spec["pax_headers"])
                        payload = bytes(spec["payload"])
                        member.size = len(payload) if member.isfile() else 0
                        layer.addfile(
                            member,
                            io.BytesIO(payload) if member.isfile() else None,
                        )
                layer_payloads.append(("layer-%d.tar" % index, buffer.getvalue()))

            manifest = json.dumps(
                [{"Config": "unused.json", "Layers": [name for name, _ in layer_payloads]}],
                separators=(",", ":"),
            ).encode("utf-8")
            with tarfile.open(path, mode="w") as archive:
                for name, payload in layer_payloads + [("manifest.json", manifest)]:
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    archive.addfile(member, io.BytesIO(payload))

        mutations = {
            "bytes": lambda layers: layers[0][0].update(payload=b"changed runtime bytes"),
            "path": lambda layers: layers[0][0].update(name="usr/local/bin/renamed"),
            "mode": lambda layers: layers[0][0].update(mode=0o755),
            "uid": lambda layers: layers[0][0].update(uid=99),
            "gid": lambda layers: layers[0][0].update(gid=99),
            "link target": lambda layers: layers[0][1].update(linkname="other"),
            "link type": lambda layers: layers[0][1].update(type=tarfile.LNKTYPE),
            "device major": lambda layers: layers[0][2].update(devmajor=2),
            "device minor": lambda layers: layers[0][2].update(devminor=8),
            "non-time PAX": lambda layers: layers[0][0]["pax_headers"].update(
                {"HBCB.test": "two"}
            ),
            "layer order": lambda layers: layers.reverse(),
        }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_archive = root / "baseline.tar"
            write_archive(baseline_archive, baseline_layers)
            baseline = scan_tool._normalized_local_image_content_digest(
                baseline_archive
            )
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    changed_layers = copy.deepcopy(baseline_layers)
                    mutate(changed_layers)
                    changed_archive = root / (label.replace(" ", "-") + ".tar")
                    write_archive(changed_archive, changed_layers)
                    self.assertNotEqual(
                        scan_tool._normalized_local_image_content_digest(
                            changed_archive
                        ),
                        baseline,
                    )
            with mock.patch.object(
                scan_tool,
                "MAX_NORMALIZED_LAYER_MEMBERS",
                0,
            ), self.assertRaisesRegex(scan_tool.ScanError, "inventory is too large"):
                scan_tool._normalized_local_image_content_digest(baseline_archive)
            with mock.patch.object(
                scan_tool,
                "MAX_NORMALIZED_LAYER_BYTES",
                1,
            ), self.assertRaisesRegex(scan_tool.ScanError, "content is too large"):
                scan_tool._normalized_local_image_content_digest(baseline_archive)

            duplicate_layers = copy.deepcopy(baseline_layers)
            duplicate_layers[0].append(copy.deepcopy(duplicate_layers[0][0]))
            duplicate_archive = root / "duplicate.tar"
            write_archive(duplicate_archive, duplicate_layers)
            with self.assertRaisesRegex(scan_tool.ScanError, "member is duplicated"):
                scan_tool._normalized_local_image_content_digest(duplicate_archive)

            unsupported_layers = copy.deepcopy(baseline_layers)
            unsupported_layers[0][0]["type"] = b"Z"
            unsupported_archive = root / "unsupported.tar"
            write_archive(unsupported_archive, unsupported_layers)
            with self.assertRaisesRegex(scan_tool.ScanError, "type is unsupported"):
                scan_tool._normalized_local_image_content_digest(unsupported_archive)

        runtime = {
            "architecture": "amd64",
            "config": {
                "Entrypoint": ["/usr/local/bin/example"],
                "Labels": {"org.opencontainers.image.revision": "reviewed"},
                "User": "65532:65532",
            },
            "os": "linux",
        }
        runtime_digest = scan_tool._normalized_runtime_config_digest(runtime)
        for label, mutate in (
            ("entrypoint", lambda item: item["config"].update(Entrypoint=["/bin/sh"])),
            ("user", lambda item: item["config"].update(User="0:0")),
            (
                "label",
                lambda item: item["config"]["Labels"].update(
                    {"org.opencontainers.image.revision": "changed"}
                ),
            ),
        ):
            with self.subTest(runtime=label):
                changed = copy.deepcopy(runtime)
                mutate(changed)
                self.assertNotEqual(
                    scan_tool._normalized_runtime_config_digest(changed),
                    runtime_digest,
                )

    def test_local_tag_cleanup_is_exact_and_reverse_build_order(self) -> None:
        local_images = scan_tool.local_image_references("f" * 24)
        commands = []
        with mock.patch.object(
            scan_tool,
            "run",
            side_effect=lambda command, **_kwargs: commands.append(list(command)) or 0,
        ):
            self.assertEqual(
                scan_tool.cleanup_local_image_tags(
                    local_images,
                    list(scan_tool.LOCAL_IMAGE_IDS),
                ),
                [],
            )
        self.assertEqual(
            commands,
            [
                ["docker", "image", "rm", reference]
                for _identifier, reference in reversed(local_images)
            ],
        )

    @unittest.skipUnless(hasattr(signal, "SIGTERM"), "requires SIGTERM")
    def test_local_tag_cleanup_defers_repeated_signal_until_every_tag(self) -> None:
        local_images = scan_tool.local_image_references("0" * 24)
        commands = []

        def capture(command, **_kwargs):
            commands.append(list(command))
            if len(commands) == 1:
                os.kill(os.getpid(), signal.SIGTERM)
            return 0

        with mock.patch.object(
            scan_tool,
            "run",
            side_effect=capture,
        ), self.assertRaises(scan_tool.TerminationSignal) as raised:
            with scan_tool._TerminationGuard() as ownership:
                # Model a signal received between guarded build/scan children.
                os.kill(os.getpid(), signal.SIGTERM)
                ownership.defer_nested_signals_until_exit()
                scan_tool.cleanup_local_image_tags(
                    local_images,
                    list(scan_tool.LOCAL_IMAGE_IDS),
                )
        self.assertEqual(raised.exception.code, 128 + signal.SIGTERM)
        self.assertEqual(
            commands,
            [
                ["docker", "image", "rm", reference]
                for _identifier, reference in reversed(local_images)
            ],
        )

    @unittest.skipUnless(hasattr(signal, "SIGTERM"), "requires SIGTERM")
    def test_deferred_ownership_guard_finishes_real_cleanup_children(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "second-cleanup-ran"
            first = "import os,signal;os.kill(os.getppid(),signal.SIGTERM)"
            second = (
                "import sys;from pathlib import Path;"
                "Path(sys.argv[1]).write_text('done',encoding='ascii')"
            )
            with self.assertRaises(scan_tool.TerminationSignal) as raised:
                with scan_tool._TerminationGuard() as ownership:
                    ownership.defer_nested_signals_until_exit()
                    self.assertEqual(
                        scan_tool.run([sys.executable, "-c", first], timeout=5),
                        0,
                    )
                    self.assertEqual(
                        scan_tool.run(
                            [sys.executable, "-c", second, str(marker)],
                            timeout=5,
                        ),
                        0,
                    )
            self.assertEqual(raised.exception.code, 128 + signal.SIGTERM)
            self.assertEqual(marker.read_text(encoding="ascii"), "done")

    @unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
    def test_outer_ownership_guard_still_allows_child_signal_teardown(self) -> None:
        child = (
            "import os,signal,time;"
            "os.kill(os.getppid(),signal.SIGTERM);"
            "time.sleep(30)"
        )
        with mock.patch.object(
            scan_tool,
            "PROCESS_TERM_GRACE_SECONDS",
            0.1,
        ), mock.patch.object(
            scan_tool,
            "PROCESS_KILL_GRACE_SECONDS",
            0.5,
        ), self.assertRaises(scan_tool.TerminationSignal) as raised:
            with scan_tool._TerminationGuard():
                scan_tool.run([sys.executable, "-c", child], timeout=5)
        self.assertEqual(raised.exception.code, 128 + signal.SIGTERM)

    def test_minio_recipe_helper_output_is_strict_and_failure_is_not_echoed(self) -> None:
        with mock.patch.object(
            scan_tool,
            "run_bounded_capture",
            return_value=("sha256:" + "c" * 64 + "\n").encode("ascii"),
        ):
            self.assertEqual(scan_tool.minio_recipe_id(), "sha256:" + "c" * 64)
        for payload in (
            b"not-a-recipe\n",
            b"sha256:" + b"a" * 65,
            b"\xff",
        ):
            with self.subTest(output=payload), mock.patch.object(
                scan_tool,
                "run_bounded_capture",
                return_value=payload,
            ):
                with self.assertRaisesRegex(
                    scan_tool.ScanError,
                    "composite recipe identity was invalid",
                ) as raised:
                    scan_tool.minio_recipe_id()
                self.assertNotIn("secret", str(raised.exception))
        with mock.patch.object(
            scan_tool,
            "run_bounded_capture",
            side_effect=scan_tool.ScanError("secret subprocess detail"),
        ), self.assertRaisesRegex(
            scan_tool.ScanError,
            "composite recipe identity failed",
        ) as raised:
            scan_tool.minio_recipe_id()
        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
