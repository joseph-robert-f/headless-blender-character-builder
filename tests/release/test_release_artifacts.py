from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from tests.release.support import (
    audit_report,
    image_inspect,
    load_script,
    sample_artifacts,
    spdx_document,
    write,
)


packager = load_script("release_artifacts_under_test", "release-artifacts")


class ReleaseArtifactsTests(unittest.TestCase):
    def _inputs(
        self, root: Path
    ) -> tuple[Path, Path, Path, Path, Path, dict[str, Path]]:
        source = root / "source"
        source.mkdir(mode=0o755)
        blender_source = b"Blender corresponding source fixture\n"
        source_policy = {
            "blender": {
                "archive": "blender-4.5.12.tar.xz",
                "bytes": len(blender_source),
                "license": "GPL-3.0-or-later",
                "official_md5": "c" * 32,
                "sha256": hashlib.sha256(blender_source).hexdigest(),
                "source_url": "https://download.blender.org/source/blender-4.5.12.tar.xz",
                "version": "4.5.12",
            },
            "format": "hbcb-corresponding-source-policy/v1",
        }
        source_notice = (
            "Corresponding source archive: <https://download.blender.org/source/blender-4.5.12.tar.xz>\n"
            f"Corresponding source bytes: `{len(blender_source)}`\n"
            f"Corresponding source SHA-256: `{hashlib.sha256(blender_source).hexdigest()}`\n"
            f"Upstream-published corresponding source MD5: `{'c' * 32}`\n"
        ).encode("utf-8")
        source_files = {
            "LICENSE": b"GPL fixture\n",
            "README.md": b"# Release fixture\n",
            "docker/BLENDER_SOURCE_NOTICE.md": source_notice,
            "release/corresponding-source-policy.json": (
                json.dumps(source_policy, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8"),
            "scripts/example": b"#!/bin/sh\nexit 0\n",
        }
        for name, payload in source_files.items():
            write(source / name, payload, 0o755 if name.startswith("scripts/") else 0o644)
        report_path = root / "source-audit-input.json"
        write(
            report_path,
            (
                json.dumps(audit_report(source_files), sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8"),
        )
        supplements = root / "supplements"
        supplements.mkdir(mode=0o755)
        write(
            supplements / "api.spdx.json",
            spdx_document("headless-blender-character-builder-api"),
        )
        write(
            supplements / "builder.spdx.json",
            spdx_document("headless-blender-character-builder"),
        )
        write(
            supplements / "worker.spdx.json",
            spdx_document("headless-blender-character-builder-worker"),
        )
        write(
            supplements / "SERVICE_THIRD_PARTY_NOTICES.txt",
            b"Lock SHA-256: " + b"a" * 64 + b"\nLicense: MIT\n",
        )
        image_paths = {}
        for role, number in (("api", 1), ("builder", 2), ("worker", 3)):
            path = root / (role + "-inspect.json")
            write(path, image_inspect(role, number))
            image_paths[role] = path
        corresponding_source = root / "corresponding-source"
        corresponding_source.mkdir(mode=0o755)
        write(corresponding_source / "blender-4.5.12.tar.xz", blender_source)
        demo = root / "demo"
        demo.mkdir(mode=0o755)
        builder_id = "sha256:" + "2" * 64
        for name, payload in sample_artifacts(builder_id).items():
            write(demo / name, payload)
        return source, report_path, supplements, corresponding_source, demo, image_paths

    @staticmethod
    def _output_payloads(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_release_bundle_is_deterministic_complete_and_non_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, corresponding, demo, images = self._inputs(root)
            first = root / "release-one"
            second = root / "release-two"
            first_metadata = packager.package(
                source, report, supplements, corresponding, demo, images, first, "0.1.0-rc.1", 123456789
            )
            second_metadata = packager.package(
                source, report, supplements, corresponding, demo, images, second, "0.1.0-rc.1", 123456789
            )
            first_payloads = self._output_payloads(first)
            second_payloads = self._output_payloads(second)
            archive = first / "headless-blender-character-builder-0.1.0-rc.1.tar.gz"
            with tarfile.open(archive, "r:gz") as handle:
                members = handle.getmembers()
                member_names = [member.name for member in members]
                member_modes = {member.name: member.mode for member in members if member.isfile()}
            sample_archive = (
                first
                / "headless-blender-character-builder-0.1.0-rc.1-sample.tar.gz"
            )
            with tarfile.open(sample_archive, "r:gz") as handle:
                sample_member_names = [member.name for member in handle.getmembers()]

        self.assertEqual(first_metadata, second_metadata)
        self.assertEqual(first_payloads, second_payloads)
        self.assertIn("SHA256SUMS", first_payloads)
        self.assertIn("release-metadata.json", first_payloads)
        self.assertIn("image-metadata.json", first_payloads)
        self.assertIn("corresponding-source.json", first_payloads)
        self.assertIn("blender-4.5.12.tar.xz", first_payloads)
        self.assertIn("BLENDER_SOURCE_NOTICE.md", first_payloads)
        self.assertIn("sample/manifest.json", first_payloads)
        self.assertIn("sample/model.blend", first_payloads)
        self.assertIn(
            "headless-blender-character-builder-0.1.0-rc.1-sample.tar.gz",
            first_payloads,
        )
        self.assertIn("api.spdx.json", first_payloads)
        self.assertIn("builder.spdx.json", first_payloads)
        self.assertIn("worker.spdx.json", first_payloads)
        self.assertIn(
            "headless-blender-character-builder-0.1.0-rc.1/scripts/example",
            member_names,
        )
        self.assertEqual(
            member_modes["headless-blender-character-builder-0.1.0-rc.1/scripts/example"],
            0o755,
        )
        self.assertNotIn("sample/model.blend", "\n".join(member_names))
        self.assertIn("sample/model.blend", sample_member_names)
        self.assertIn("sample/manifest.json", sample_member_names)
        checksums = first_payloads["SHA256SUMS"].decode("ascii").splitlines()
        self.assertTrue(any(line.endswith("  sample/model.blend") for line in checksums))
        self.assertTrue(any(line.endswith("  blender-4.5.12.tar.xz") for line in checksums))
        checksum_records = dict(line.split("  ", 1)[::-1] for line in checksums)
        self.assertEqual(set(checksum_records), set(first_payloads) - {"SHA256SUMS"})
        for name, digest in checksum_records.items():
            self.assertEqual(digest, hashlib.sha256(first_payloads[name]).hexdigest())
        inventory = json.loads(first_payloads["corresponding-source.json"])
        self.assertEqual(inventory["distribution_version"], "0.1.0-rc.1")
        self.assertEqual(inventory["source_revision"], "a" * 40)
        self.assertEqual(inventory["delivery_method"], "co-published-release-assets")
        self.assertIs(inventory["public_oci_ready"], False)
        self.assertEqual(
            inventory["publication_gate"],
            "blocked-pending-complete-copyleft-source-review",
        )
        self.assertEqual(inventory["scope"], "project-and-blender-source-only")
        self.assertEqual(
            inventory["images"]["worker"]["materials"],
            ["blender-source", "project-source"],
        )
        metadata = json.loads(first_payloads["release-metadata.json"])
        self.assertEqual(metadata["format"], "hbcb-release-metadata/v2")
        self.assertEqual(
            metadata["corresponding_source_inventory_sha256"],
            hashlib.sha256(first_payloads["corresponding-source.json"]).hexdigest(),
        )

    def test_sample_artifact_hash_and_builder_image_binding_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, corresponding, demo, images = self._inputs(root)
            (demo / "model.stl").write_bytes(b"tampered\n")
            with self.assertRaises(packager.PackagingFailure) as raised:
                packager.package(
                    source,
                    report,
                    supplements,
                    corresponding,
                    demo,
                    images,
                    root / "release",
                    "0.1.0-rc.1",
                    0,
                )
            self.assertEqual(raised.exception.code, "sample_hash_mismatch")

            # Restore the demo and substitute a different builder image ID.
            for name, payload in sample_artifacts("sha256:" + "2" * 64).items():
                write(demo / name, payload)
            wrong = json.loads(images["builder"].read_text(encoding="utf-8"))
            wrong[0]["Id"] = "sha256:" + "9" * 64
            write(
                images["builder"],
                (json.dumps(wrong, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
            )
            with self.assertRaises(packager.PackagingFailure) as binding:
                packager.package(
                    source,
                    report,
                    supplements,
                    corresponding,
                    demo,
                    images,
                    root / "release-two",
                    "0.1.0-rc.1",
                    0,
                )
            self.assertEqual(binding.exception.code, "invalid_sample_evidence")

    def test_source_mutation_unsafe_image_metadata_and_no_clobber_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, corresponding, demo, images = self._inputs(root)
            (source / "README.md").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(packager.PackagingFailure) as source_failure:
                packager.package(
                    source, report, supplements, corresponding, demo, images, root / "one", "0.1.0-rc.1", 0
                )
            self.assertEqual(source_failure.exception.code, "source_content_mismatch")

            write(source / "README.md", b"# Release fixture\n")
            notice_path = source / "docker" / "BLENDER_SOURCE_NOTICE.md"
            original_notice = notice_path.read_bytes()
            write(
                notice_path,
                original_notice.replace(b"Corresponding source bytes:", b"Source bytes:"),
            )
            changed_files = {
                path.relative_to(source).as_posix(): path.read_bytes()
                for path in sorted(source.rglob("*"))
                if path.is_file()
            }
            write(
                report,
                (
                    json.dumps(
                        audit_report(changed_files), sort_keys=True, separators=(",", ":")
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            with self.assertRaises(packager.PackagingFailure) as notice_failure:
                packager.package(
                    source,
                    report,
                    supplements,
                    corresponding,
                    demo,
                    images,
                    root / "bad-notice",
                    "0.1.0-rc.1",
                    0,
                )
            self.assertEqual(notice_failure.exception.code, "invalid_source_notice")
            write(notice_path, original_notice)
            restored_files = {
                path.relative_to(source).as_posix(): path.read_bytes()
                for path in sorted(source.rglob("*"))
                if path.is_file()
            }
            write(
                report,
                (
                    json.dumps(
                        audit_report(restored_files), sort_keys=True, separators=(",", ":")
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            invalid_image = json.loads(images["api"].read_text(encoding="utf-8"))
            del invalid_image[0]["Config"]["Labels"]["org.opencontainers.image.licenses"]
            write(
                images["api"],
                (json.dumps(invalid_image, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
            )
            with self.assertRaises(packager.PackagingFailure) as image_failure:
                packager.package(
                    source, report, supplements, corresponding, demo, images, root / "two", "0.1.0-rc.1", 0
                )
            self.assertEqual(image_failure.exception.code, "invalid_image_metadata")

            write(images["api"], image_inspect("api", 1))
            wrong_platform = json.loads(images["api"].read_text(encoding="utf-8"))
            wrong_platform[0]["Architecture"] = "arm64"
            write(
                images["api"],
                (
                    json.dumps(wrong_platform, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode("utf-8"),
            )
            with self.assertRaises(packager.PackagingFailure) as platform_failure:
                packager.package(
                    source,
                    report,
                    supplements,
                    corresponding,
                    demo,
                    images,
                    root / "three",
                    "0.1.0-rc.1",
                    0,
                )
            self.assertEqual(platform_failure.exception.code, "invalid_image_metadata")

            write(images["api"], image_inspect("api", 1))
            for field, value in (
                ("org.opencontainers.image.version", "0.1.0"),
                ("org.opencontainers.image.revision", "b" * 40),
                ("org.opencontainers.image.source", "https://example.invalid/project"),
            ):
                with self.subTest(identity_field=field):
                    invalid_identity = json.loads(
                        images["api"].read_text(encoding="utf-8")
                    )
                    invalid_identity[0]["Config"]["Labels"][field] = value
                    write(
                        images["api"],
                        (
                            json.dumps(
                                invalid_identity, sort_keys=True, separators=(",", ":")
                            )
                            + "\n"
                        ).encode("utf-8"),
                    )
                    with self.assertRaises(packager.PackagingFailure) as identity:
                        packager.package(
                            source,
                            report,
                            supplements,
                            corresponding,
                            demo,
                            images,
                            root / ("identity-" + field.rsplit(".", 1)[-1]),
                            "0.1.0-rc.1",
                            0,
                        )
                    self.assertEqual(identity.exception.code, "invalid_image_metadata")
                    write(images["api"], image_inspect("api", 1))

            wrong_tag = json.loads(images["api"].read_text(encoding="utf-8"))
            wrong_tag[0]["RepoTags"] = ["headless-blender-character-builder-api:latest"]
            write(
                images["api"],
                (json.dumps(wrong_tag, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            )
            with self.assertRaises(packager.PackagingFailure) as tag_identity:
                packager.package(
                    source,
                    report,
                    supplements,
                    corresponding,
                    demo,
                    images,
                    root / "wrong-tag",
                    "0.1.0-rc.1",
                    0,
                )
            self.assertEqual(tag_identity.exception.code, "invalid_image_metadata")
            write(images["api"], image_inspect("api", 1))

            (corresponding / "blender-4.5.12.tar.xz").write_bytes(b"altered")
            with self.assertRaises(packager.PackagingFailure) as source_archive:
                packager.package(
                    source,
                    report,
                    supplements,
                    corresponding,
                    demo,
                    images,
                    root / "bad-corresponding-source",
                    "0.1.0-rc.1",
                    0,
                )
            self.assertEqual(
                source_archive.exception.code, "corresponding_source_mismatch"
            )

            write(
                corresponding / "blender-4.5.12.tar.xz",
                b"Blender corresponding source fixture\n",
            )
            output = root / "existing"
            output.mkdir()
            with self.assertRaises(packager.PackagingFailure) as clobber:
                packager.package(
                    source, report, supplements, corresponding, demo, images, output, "0.1.0-rc.1", 0
                )
            self.assertEqual(clobber.exception.code, "output_exists")


if __name__ == "__main__":
    unittest.main()
