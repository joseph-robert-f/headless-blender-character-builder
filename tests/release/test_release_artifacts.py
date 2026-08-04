from __future__ import annotations

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
    def _inputs(self, root: Path) -> tuple[Path, Path, Path, Path, dict[str, Path]]:
        source = root / "source"
        source.mkdir(mode=0o755)
        source_files = {
            "LICENSE": b"GPL fixture\n",
            "README.md": b"# Release fixture\n",
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
        demo = root / "demo"
        demo.mkdir(mode=0o755)
        builder_id = "sha256:" + "2" * 64
        for name, payload in sample_artifacts(builder_id).items():
            write(demo / name, payload)
        return source, report_path, supplements, demo, image_paths

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
            source, report, supplements, demo, images = self._inputs(root)
            first = root / "release-one"
            second = root / "release-two"
            first_metadata = packager.package(
                source, report, supplements, demo, images, first, "0.1.0-rc.1", 123456789
            )
            second_metadata = packager.package(
                source, report, supplements, demo, images, second, "0.1.0-rc.1", 123456789
            )
            first_payloads = self._output_payloads(first)
            second_payloads = self._output_payloads(second)
            archive = first / "headless-blender-character-builder-0.1.0-rc.1.tar.gz"
            with tarfile.open(archive, "r:gz") as handle:
                members = handle.getmembers()
                member_names = [member.name for member in members]
                member_modes = {member.name: member.mode for member in members if member.isfile()}

        self.assertEqual(first_metadata, second_metadata)
        self.assertEqual(first_payloads, second_payloads)
        self.assertIn("SHA256SUMS", first_payloads)
        self.assertIn("release-metadata.json", first_payloads)
        self.assertIn("image-metadata.json", first_payloads)
        self.assertIn("sample/manifest.json", first_payloads)
        self.assertIn("sample/model.blend", first_payloads)
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
        checksums = first_payloads["SHA256SUMS"].decode("ascii").splitlines()
        self.assertTrue(any(line.endswith("  sample/model.blend") for line in checksums))

    def test_sample_artifact_hash_and_builder_image_binding_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, demo, images = self._inputs(root)
            (demo / "model.stl").write_bytes(b"tampered\n")
            with self.assertRaises(packager.PackagingFailure) as raised:
                packager.package(
                    source,
                    report,
                    supplements,
                    demo,
                    images,
                    root / "release",
                    "0.1.0",
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
                    demo,
                    images,
                    root / "release-two",
                    "0.1.0",
                    0,
                )
            self.assertEqual(binding.exception.code, "invalid_sample_evidence")

    def test_source_mutation_unsafe_image_metadata_and_no_clobber_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, demo, images = self._inputs(root)
            (source / "README.md").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(packager.PackagingFailure) as source_failure:
                packager.package(
                    source, report, supplements, demo, images, root / "one", "0.1.0", 0
                )
            self.assertEqual(source_failure.exception.code, "source_content_mismatch")

            write(source / "README.md", b"# Release fixture\n")
            invalid_image = json.loads(images["api"].read_text(encoding="utf-8"))
            del invalid_image[0]["Config"]["Labels"]["org.opencontainers.image.licenses"]
            write(
                images["api"],
                (json.dumps(invalid_image, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
            )
            with self.assertRaises(packager.PackagingFailure) as image_failure:
                packager.package(
                    source, report, supplements, demo, images, root / "two", "0.1.0", 0
                )
            self.assertEqual(image_failure.exception.code, "invalid_image_metadata")

            write(images["api"], image_inspect("api", 1))
            output = root / "existing"
            output.mkdir()
            with self.assertRaises(packager.PackagingFailure) as clobber:
                packager.package(
                    source, report, supplements, demo, images, output, "0.1.0", 0
                )
            self.assertEqual(clobber.exception.code, "output_exists")


if __name__ == "__main__":
    unittest.main()
