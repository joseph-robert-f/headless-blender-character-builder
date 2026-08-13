from __future__ import annotations

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
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.release.support import (
    audit_report,
    git,
    image_inspect,
    load_script,
    sample_artifacts,
    spdx_document,
    write,
)


packager = load_script("release_artifacts_under_test", "release-artifacts")
preflight = load_script(
    "release_publication_preflight_under_test", "release-publication-preflight"
)


class ReleaseArtifactsTests(unittest.TestCase):
    @staticmethod
    def _main_arguments(root: Path) -> SimpleNamespace:
        return SimpleNamespace(
            docker="docker",
            finalize_output_dir=root / "published",
            git="git",
            print_image_id=None,
            registry_owner="reviewed-owner",
            release_dir=root / "release",
            remote_manifest=[
                role + "=" + str(root / (role + ".json"))
                for role in sorted(preflight.IMAGE_TAGS)
            ],
            repo=root,
            require_published_digests=False,
            version="0.1.0-rc.1",
        )

    @staticmethod
    def _process_group_exists(process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _wait_for_path(path: Path, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while not path.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not path.is_file():
            raise AssertionError("child marker was not published before the deadline")

    @staticmethod
    def _term_resistant_command(marker: Path) -> list[str]:
        descendant = (
            "import os,signal,sys,time;"
            "from pathlib import Path;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "signal.signal(getattr(signal,'SIGHUP',signal.SIGTERM),signal.SIG_IGN);"
            "Path(sys.argv[1]).write_text("
            "str(os.getpid())+' '+str(os.getpgrp()),encoding='ascii');"
            "time.sleep(30)"
        )
        leader = (
            "import signal,subprocess,sys,time;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "signal.signal(getattr(signal,'SIGHUP',signal.SIGTERM),signal.SIG_IGN);"
            "sys.stderr.write('preflight-secret-canary');sys.stderr.flush();"
            "subprocess.Popen([sys.executable,'-c',%r,sys.argv[1]]);"
            "time.sleep(30)"
        ) % descendant
        return [sys.executable, "-c", leader, str(marker)]

    def _inputs(
        self, root: Path, publication_ready: bool = False
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
            "publication": {
                "delivery_method": "co-published-release-assets",
                "public_oci_ready": publication_ready,
                "publication_gate": (
                    "reviewed-complete-source-delivery"
                    if publication_ready
                    else "blocked-pending-complete-copyleft-source-review"
                ),
                "retention": "retain-with-each-public-image-version-for-its-public-lifetime",
                "scope": (
                    "complete-reviewed-image-source"
                    if publication_ready
                    else "project-and-blender-source-only"
                ),
            },
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

    @staticmethod
    def _tamper_generated_publication(output: Path) -> None:
        # Deliberately mutate only generated evidence. The tracked policy test
        # proves this coherent rehash cannot authorize publication.
        inventory_path = output / "corresponding-source.json"
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        inventory["public_oci_ready"] = True
        inventory["publication_gate"] = "reviewed-complete-source-delivery"
        inventory_payload = (
            json.dumps(inventory, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        inventory_path.write_bytes(inventory_payload)
        metadata_path = output / "release-metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["corresponding_source_inventory_sha256"] = hashlib.sha256(
            inventory_payload
        ).hexdigest()
        inventory_records = 0
        for item in metadata["artifacts"]:
            if item["name"] == "corresponding-source.json":
                inventory_records += 1
                item["bytes"] = len(inventory_payload)
                item["sha256"] = hashlib.sha256(inventory_payload).hexdigest()
        if inventory_records != 1:
            raise AssertionError("fixture inventory must describe corresponding-source.json once")
        metadata_path.write_text(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        checksums = []
        for line in (output / "SHA256SUMS").read_text(encoding="ascii").splitlines():
            _digest, name = line.split("  ", 1)
            checksums.append(
                hashlib.sha256((output / name).read_bytes()).hexdigest() + "  " + name
            )
        (output / "SHA256SUMS").write_text(
            "\n".join(checksums) + "\n", encoding="ascii"
        )

    @staticmethod
    def _refresh_bundle_checksums(output: Path) -> None:
        names = sorted(
            path.relative_to(output).as_posix()
            for path in output.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        )
        (output / "SHA256SUMS").write_text(
            "".join(
                hashlib.sha256((output / name).read_bytes()).hexdigest()
                + "  "
                + name
                + "\n"
                for name in names
            ),
            encoding="ascii",
        )

    @staticmethod
    def _bind_corresponding_source_inventory(output: Path) -> None:
        inventory_payload = (output / "corresponding-source.json").read_bytes()
        metadata_path = output / "release-metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["corresponding_source_inventory_sha256"] = hashlib.sha256(
            inventory_payload
        ).hexdigest()
        matches = 0
        for item in metadata["artifacts"]:
            if item["name"] == "corresponding-source.json":
                matches += 1
                item["bytes"] = len(inventory_payload)
                item["sha256"] = hashlib.sha256(inventory_payload).hexdigest()
        if matches != 1:
            raise AssertionError("fixture must inventory corresponding-source.json once")
        metadata_path.write_text(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        ReleaseArtifactsTests._refresh_bundle_checksums(output)

    @staticmethod
    def _rebind_artifact(output: Path, name: str) -> None:
        payload = (output / name).read_bytes()
        metadata_path = output / "release-metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        matches = 0
        for item in metadata["artifacts"]:
            if item["name"] == name:
                matches += 1
                item["bytes"] = len(payload)
                item["sha256"] = hashlib.sha256(payload).hexdigest()
        if matches != 1:
            raise AssertionError("fixture must inventory the mutated artifact once")
        metadata_path.write_text(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        ReleaseArtifactsTests._refresh_bundle_checksums(output)

    @staticmethod
    def _source_policy(root: Path) -> dict[str, object]:
        payload = (root / "source" / "release" / "corresponding-source-policy.json").read_bytes()
        return preflight._source_policy(payload)

    @staticmethod
    def _trusted_source_records(output: Path) -> dict[str, tuple[str, int, str]]:
        report = json.loads((output / "source-audit.json").read_text(encoding="utf-8"))
        return {
            item["path"]: (item["git_mode"], item["bytes"], item["sha256"])
            for item in report["files"]
        }

    @staticmethod
    def _remote_manifest(image_id: str, role: str) -> bytes:
        layer_digest = "sha256:" + hashlib.sha256(
            ("reviewed-" + role + "-layer").encode("ascii")
        ).hexdigest()
        value = {
            "config": {
                "digest": image_id,
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "size": 512,
            },
            "layers": [
                {
                    "digest": layer_digest,
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "size": 1024,
                }
            ],
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "schemaVersion": 2,
        }
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")

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

    def test_public_image_metadata_never_copies_private_daemon_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, corresponding, demo, images = self._inputs(root)
            private_tag = "private-registry.invalid/team/secret-builder:internal"
            private_digest = (
                "private-registry.invalid/team/secret-builder@sha256:" + "f" * 64
            )
            private_label = "private-registry.invalid/team/internal:secret"
            builder = json.loads(images["builder"].read_text(encoding="utf-8"))
            builder[0]["RepoTags"].append(private_tag)
            builder[0]["RepoDigests"] = [private_digest]
            builder[0]["Config"]["Labels"]["org.opencontainers.image.url"] = private_label
            write(
                images["builder"],
                (json.dumps(builder, sort_keys=True, separators=(",", ":")) + "\n").encode(
                    "utf-8"
                ),
            )

            output = root / "release"
            packager.package(
                source,
                report,
                supplements,
                corresponding,
                demo,
                images,
                output,
                "0.1.0-rc.1",
                123456789,
            )
            payload = (output / "image-metadata.json").read_text(encoding="utf-8")
            metadata = json.loads(payload)

        record = metadata["images"]["builder"]
        self.assertEqual(
            record["expected_public_tag"],
            "headless-blender-character-builder:0.1.0-rc.1",
        )
        self.assertIsNone(record["published_digest"])
        self.assertNotIn("repo_tags", record)
        self.assertNotIn("repo_digests", record)
        self.assertNotIn(private_tag, payload)
        self.assertNotIn(private_digest, payload)
        self.assertNotIn(private_label, payload)

    def test_publication_preflight_rebinds_bundle_to_live_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, corresponding, demo, images = self._inputs(root)
            output = root / "release"
            packager.package(
                source,
                report,
                supplements,
                corresponding,
                demo,
                images,
                output,
                "0.1.0-rc.1",
                123456789,
            )
            with self.assertRaises(preflight.PreflightFailure) as blocked:
                preflight.verify_bundle(output, "0.1.0-rc.1", "a" * 40)
            self.assertEqual(blocked.exception.code, "identity_mismatch")

            blocked_policy = preflight.current_publication_policy(source)
            self._tamper_generated_publication(output)
            with self.assertRaises(preflight.PreflightFailure) as unreviewed:
                preflight.verify_bundle(
                    output,
                    "0.1.0-rc.1",
                    "a" * 40,
                    expected_publication=blocked_policy,
                )
            self.assertEqual(unreviewed.exception.code, "identity_mismatch")

            ready_root = root / "reviewed"
            ready_root.mkdir()
            source, report, supplements, corresponding, demo, images = self._inputs(
                ready_root, publication_ready=True
            )
            output = ready_root / "release"
            packager.package(
                source,
                report,
                supplements,
                corresponding,
                demo,
                images,
                output,
                "0.1.0-rc.1",
                123456789,
            )
            records = preflight.verify_bundle(output, "0.1.0-rc.1", "a" * 40)
            payloads = {
                {
                    "api": "headless-blender-character-builder-api",
                    "builder": "headless-blender-character-builder",
                    "worker": "headless-blender-character-builder-worker",
                }[role]
                + ":0.1.0-rc.1": path.read_bytes()
                for role, path in images.items()
            }

            def runner(arguments: tuple[str, ...], **_kwargs: object) -> bytes:
                return payloads[arguments[-1]]

            preflight.verify_live_images(
                records,
                "0.1.0-rc.1",
                "a" * 40,
                runner=runner,
                repo=root,
            )
            outgoing_payloads = dict(payloads)
            for role, repository in preflight.IMAGE_TAGS.items():
                outgoing_payloads[
                    "ghcr.io/reviewed-owner/" + repository + ":0.1.0-rc.1"
                ] = payloads[repository + ":0.1.0-rc.1"]

            def outgoing_runner(
                arguments: tuple[str, ...], **_kwargs: object
            ) -> bytes:
                return outgoing_payloads[arguments[-1]]

            preflight.verify_live_images(
                records,
                "0.1.0-rc.1",
                "a" * 40,
                registry_owner="reviewed-owner",
                runner=outgoing_runner,
                repo=root,
            )
            changed_destination = json.loads(
                outgoing_payloads[
                    "ghcr.io/reviewed-owner/"
                    "headless-blender-character-builder-worker:0.1.0-rc.1"
                ]
            )
            changed_destination[0]["Id"] = "sha256:" + "8" * 64
            outgoing_payloads[
                "ghcr.io/reviewed-owner/"
                "headless-blender-character-builder-worker:0.1.0-rc.1"
            ] = (
                json.dumps(
                    changed_destination, sort_keys=True, separators=(",", ":")
                )
                + "\n"
            ).encode("utf-8")
            with self.assertRaises(preflight.PreflightFailure) as outgoing:
                preflight.verify_live_images(
                    records,
                    "0.1.0-rc.1",
                    "a" * 40,
                    registry_owner="reviewed-owner",
                    runner=outgoing_runner,
                    repo=root,
                )
            self.assertEqual(outgoing.exception.code, "live_image_mismatch")
            changed = json.loads(payloads["headless-blender-character-builder:0.1.0-rc.1"])
            changed[0]["Id"] = "sha256:" + "9" * 64
            payloads["headless-blender-character-builder:0.1.0-rc.1"] = (
                json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            with self.assertRaises(preflight.PreflightFailure) as rebound:
                preflight.verify_live_images(
                    records,
                    "0.1.0-rc.1",
                    "a" * 40,
                    runner=runner,
                    repo=root,
                )
            self.assertEqual(rebound.exception.code, "live_image_mismatch")

            (output / "image-metadata.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(preflight.PreflightFailure) as tampered:
                preflight.verify_bundle(output, "0.1.0-rc.1", "a" * 40)
            self.assertEqual(tampered.exception.code, "checksum_mismatch")

    def test_publication_preflight_requires_every_release_artifact_role(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, corresponding, demo, images = self._inputs(
                root, publication_ready=True
            )
            output = root / "release"
            packager.package(
                source,
                report,
                supplements,
                corresponding,
                demo,
                images,
                output,
                "0.1.0-rc.1",
                123456789,
            )
            preflight.verify_bundle(output, "0.1.0-rc.1", "a" * 40)
            metadata_path = output / "release-metadata.json"
            original_metadata = metadata_path.read_bytes()
            original_checksums = (output / "SHA256SUMS").read_bytes()
            required = (
                "blender-4.5.12.tar.xz",
                "headless-blender-character-builder-0.1.0-rc.1.tar.gz",
                "source-audit.json",
                "api.spdx.json",
                "builder.spdx.json",
                "worker.spdx.json",
                "BLENDER_SOURCE_NOTICE.md",
                "SERVICE_THIRD_PARTY_NOTICES.txt",
                "headless-blender-character-builder-0.1.0-rc.1-sample.tar.gz",
                "sample/diagnostics/back.png",
                "sample/diagnostics/front.png",
                "sample/diagnostics/side.png",
                "sample/manifest.json",
                "sample/model.blend",
                "sample/model.glb",
                "sample/model.stl",
                "sample/preview.png",
                "sample/qa.json",
            )
            for name in required:
                with self.subTest(missing=name):
                    target = output / name
                    original_payload = target.read_bytes()
                    target.unlink()
                    metadata = json.loads(original_metadata)
                    metadata["artifacts"] = [
                        item for item in metadata["artifacts"] if item["name"] != name
                    ]
                    metadata_path.write_text(
                        json.dumps(metadata, sort_keys=True, separators=(",", ":"))
                        + "\n",
                        encoding="utf-8",
                    )
                    self._refresh_bundle_checksums(output)
                    try:
                        with self.assertRaises(preflight.PreflightFailure) as missing:
                            preflight.verify_bundle(output, "0.1.0-rc.1", "a" * 40)
                        self.assertEqual(missing.exception.code, "identity_mismatch")
                    finally:
                        target.write_bytes(original_payload)
                        metadata_path.write_bytes(original_metadata)
                        (output / "SHA256SUMS").write_bytes(original_checksums)

    def test_publication_preflight_validates_source_material_and_image_references(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, corresponding, demo, images = self._inputs(
                root, publication_ready=True
            )
            output = root / "release"
            packager.package(
                source,
                report,
                supplements,
                corresponding,
                demo,
                images,
                output,
                "0.1.0-rc.1",
                123456789,
            )
            inventory_path = output / "corresponding-source.json"
            metadata_path = output / "release-metadata.json"
            checksum_path = output / "SHA256SUMS"
            original_inventory = inventory_path.read_bytes()
            original_metadata = metadata_path.read_bytes()
            original_checksums = checksum_path.read_bytes()

            def wrong_byte_count(inventory: dict[str, object]) -> None:
                materials = inventory["materials"]
                assert isinstance(materials, dict)
                project = materials["project-source"]
                assert isinstance(project, dict)
                project["bytes"] += 1

            def wrong_digest(inventory: dict[str, object]) -> None:
                materials = inventory["materials"]
                assert isinstance(materials, dict)
                project = materials["project-source"]
                assert isinstance(project, dict)
                project["sha256"] = "0" * 64

            def wrong_material_reference(inventory: dict[str, object]) -> None:
                materials = inventory["materials"]
                assert isinstance(materials, dict)
                project = materials["project-source"]
                assert isinstance(project, dict)
                replacement = (output / "sample/model.blend").read_bytes()
                project["artifact"] = "sample/model.blend"
                project["bytes"] = len(replacement)
                project["sha256"] = hashlib.sha256(replacement).hexdigest()

            def wrong_sbom_reference(inventory: dict[str, object]) -> None:
                image_records = inventory["images"]
                assert isinstance(image_records, dict)
                builder = image_records["builder"]
                assert isinstance(builder, dict)
                builder["sbom"] = "api.spdx.json"

            def wrong_notice_reference(inventory: dict[str, object]) -> None:
                image_records = inventory["images"]
                assert isinstance(image_records, dict)
                api = image_records["api"]
                assert isinstance(api, dict)
                api["notices"] = ["BLENDER_SOURCE_NOTICE.md"]

            mutations = {
                "material_bytes": wrong_byte_count,
                "material_sha256": wrong_digest,
                "material_artifact": wrong_material_reference,
                "image_sbom": wrong_sbom_reference,
                "image_notice": wrong_notice_reference,
            }
            for name, mutate in mutations.items():
                with self.subTest(mutation=name):
                    inventory = json.loads(original_inventory)
                    mutate(inventory)
                    inventory_path.write_text(
                        json.dumps(inventory, sort_keys=True, separators=(",", ":"))
                        + "\n",
                        encoding="utf-8",
                    )
                    self._bind_corresponding_source_inventory(output)
                    try:
                        with self.assertRaises(preflight.PreflightFailure) as mismatch:
                            preflight.verify_bundle(output, "0.1.0-rc.1", "a" * 40)
                        self.assertEqual(mismatch.exception.code, "identity_mismatch")
                    finally:
                        inventory_path.write_bytes(original_inventory)
                        metadata_path.write_bytes(original_metadata)
                        checksum_path.write_bytes(original_checksums)

    def test_publication_preflight_rejects_coherently_replaced_release_content(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, corresponding, demo, images = self._inputs(
                root, publication_ready=True
            )
            output = root / "release"
            packager.package(
                source,
                report,
                supplements,
                corresponding,
                demo,
                images,
                output,
                "0.1.0-rc.1",
                123456789,
            )
            policy = self._source_policy(root)
            trusted_source_records = self._trusted_source_records(output)
            preflight.verify_bundle(
                output,
                "0.1.0-rc.1",
                "a" * 40,
                "b" * 64,
                source_policy=policy,
                tracked_source_records=trusted_source_records,
            )
            originals = self._output_payloads(output)

            def restore() -> None:
                for name, payload in originals.items():
                    write(output / name, payload)

            def mutate_blender() -> None:
                path = output / "blender-4.5.12.tar.xz"
                path.write_bytes(b"coherent Blender replacement\n")
                inventory_path = output / "corresponding-source.json"
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                material = inventory["materials"]["blender-source"]
                material["bytes"] = path.stat().st_size
                material["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                inventory_path.write_text(
                    json.dumps(inventory, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                self._bind_corresponding_source_inventory(output)
                self._rebind_artifact(output, "blender-4.5.12.tar.xz")

            def mutate_project_archive() -> None:
                path = output / "headless-blender-character-builder-0.1.0-rc.1.tar.gz"
                payload = path.read_bytes()
                path.write_bytes(payload[:-8] + b"replacement")
                self._rebind_artifact(output, path.name)

            def mutate_source_audit() -> None:
                audit_path = output / "source-audit.json"
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                replacement_path = "README.md"
                replacement_payload = b"# Coherently replaced source\n"
                for item in audit["files"]:
                    if item["path"] == replacement_path:
                        item["bytes"] = len(replacement_payload)
                        item["sha256"] = hashlib.sha256(
                            replacement_payload
                        ).hexdigest()
                        break
                else:
                    raise AssertionError("fixture source audit lacks README.md")
                tree = hashlib.sha256()
                audit["total_bytes"] = 0
                for item in audit["files"]:
                    tree.update(
                        item["git_mode"].encode("ascii")
                        + b"\0"
                        + item["path"].encode("utf-8")
                        + b"\0"
                        + str(item["bytes"]).encode("ascii")
                        + b"\0"
                        + item["sha256"].encode("ascii")
                        + b"\n"
                    )
                    audit["total_bytes"] += item["bytes"]
                audit["source_tree_sha256"] = tree.hexdigest()
                audit_path.write_text(
                    json.dumps(audit, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )

                archive_name = (
                    "headless-blender-character-builder-0.1.0-rc.1.tar.gz"
                )
                archive_path = output / archive_name
                original_archive = io.BytesIO(originals[archive_name])
                rebuilt_members = []
                with tarfile.open(fileobj=original_archive, mode="r:gz") as archive:
                    for member in archive:
                        payload = None
                        if member.isfile():
                            stream = archive.extractfile(member)
                            if stream is None:
                                raise AssertionError("fixture source archive is unreadable")
                            payload = stream.read()
                            if member.name.endswith("/" + replacement_path):
                                payload = replacement_payload
                        rebuilt_members.append((member, payload))
                with tarfile.open(archive_path, mode="w:gz") as archive:
                    for original_member, payload in rebuilt_members:
                        member = tarfile.TarInfo(original_member.name)
                        member.type = original_member.type
                        member.mode = original_member.mode
                        member.uid = original_member.uid
                        member.gid = original_member.gid
                        member.uname = original_member.uname
                        member.gname = original_member.gname
                        member.mtime = original_member.mtime
                        if payload is not None:
                            member.size = len(payload)
                            archive.addfile(member, io.BytesIO(payload))
                        else:
                            archive.addfile(member)

                inventory_path = output / "corresponding-source.json"
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                project = inventory["materials"]["project-source"]
                project["bytes"] = archive_path.stat().st_size
                project["sha256"] = hashlib.sha256(
                    archive_path.read_bytes()
                ).hexdigest()
                inventory_path.write_text(
                    json.dumps(inventory, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                metadata_path = output / "release-metadata.json"
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata["source_tree_sha256"] = audit["source_tree_sha256"]
                metadata_path.write_text(
                    json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                self._bind_corresponding_source_inventory(output)
                self._rebind_artifact(output, archive_name)
                self._rebind_artifact(output, "source-audit.json")

            def mutate_sample_file() -> None:
                path = output / "sample/model.blend"
                path.write_bytes(b"coherent sample replacement\n")
                manifest_path = output / "sample/manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                record = manifest["artifacts"]["model.blend"]
                record["bytes"] = path.stat().st_size
                record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest_path.write_text(
                    json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                self._rebind_artifact(output, "sample/model.blend")
                self._rebind_artifact(output, "sample/manifest.json")

            def mutate_sbom() -> None:
                path = output / "builder.spdx.json"
                path.write_text("{}\n", encoding="utf-8")
                self._rebind_artifact(output, path.name)

            def mutate_notice() -> None:
                path = output / "SERVICE_THIRD_PARTY_NOTICES.txt"
                path.write_text("coherent replacement\n", encoding="utf-8")
                self._rebind_artifact(output, path.name)

            def mutate_blender_notice() -> None:
                path = output / "BLENDER_SOURCE_NOTICE.md"
                path.write_text("coherent replacement\n", encoding="utf-8")
                self._rebind_artifact(output, path.name)

            mutations = {
                "blender": mutate_blender,
                "project_archive": mutate_project_archive,
                "source_audit": mutate_source_audit,
                "sample": mutate_sample_file,
                "sbom": mutate_sbom,
                "notice": mutate_notice,
                "blender_notice": mutate_blender_notice,
            }
            for name, mutate in mutations.items():
                with self.subTest(mutation=name):
                    restore()
                    mutate()
                    with self.assertRaises(preflight.PreflightFailure) as replaced:
                        preflight.verify_bundle(
                            output,
                            "0.1.0-rc.1",
                            "a" * 40,
                            "b" * 64,
                            source_policy=policy,
                            tracked_source_records=trusted_source_records,
                        )
                    self.assertEqual(replaced.exception.code, "identity_mismatch")

    def test_private_manifest_finalization_is_checksum_bound_and_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, corresponding, demo, images = self._inputs(
                root, publication_ready=True
            )
            release = root / "release"
            packager.package(
                source,
                report,
                supplements,
                corresponding,
                demo,
                images,
                release,
                "0.1.0-rc.1",
                123456789,
            )
            records = preflight.verify_bundle(release, "0.1.0-rc.1", "a" * 40)
            manifests = {}
            expected_digests = {}
            for role in sorted(preflight.IMAGE_TAGS):
                path = root / (role + "-remote-manifest.json")
                payload = self._remote_manifest(str(records[role]["image_id"]), role)
                write(path, payload)
                manifests[role] = path
                expected_digests[role] = "sha256:" + hashlib.sha256(payload).hexdigest()

            published = root / "published-release"
            preflight.finalize_published_bundle(
                release, published, records, manifests, "reviewed-owner"
            )
            finalized = preflight.verify_bundle(
                published,
                "0.1.0-rc.1",
                "a" * 40,
                require_published_digests=True,
                registry_owner="reviewed-owner",
            )
            metadata_payload = (published / "image-metadata.json").read_bytes()
            release_metadata = json.loads(
                (published / "release-metadata.json").read_text(encoding="utf-8")
            )
            image_artifact = [
                item
                for item in release_metadata["artifacts"]
                if item["name"] == "image-metadata.json"
            ]

            self.assertEqual(len(image_artifact), 1)
            self.assertEqual(image_artifact[0]["bytes"], len(metadata_payload))
            self.assertEqual(
                image_artifact[0]["sha256"], hashlib.sha256(metadata_payload).hexdigest()
            )
            for role, repository in preflight.IMAGE_TAGS.items():
                self.assertEqual(finalized[role]["published_digest"], expected_digests[role])
                self.assertEqual(
                    finalized[role]["expected_public_tag"],
                    "ghcr.io/reviewed-owner/" + repository + ":0.1.0-rc.1",
                )
            self.assertNotIn("private-registry", metadata_payload.decode("utf-8"))

            with self.assertRaises(preflight.PreflightFailure) as missing_owner:
                preflight.verify_bundle(
                    published,
                    "0.1.0-rc.1",
                    "a" * 40,
                    require_published_digests=True,
                )
            self.assertEqual(missing_owner.exception.code, "invalid_identity")

            foreign_file = root / "foreign-file"
            foreign_file.write_bytes(b"foreign bytes\n")
            foreign_dir = root / "foreign-dir"
            foreign_dir.mkdir()
            foreign_marker = foreign_dir / "marker"
            foreign_marker.write_bytes(b"foreign directory\n")
            foreign_link = root / "foreign-link"
            foreign_link.symlink_to(root / "missing-target")
            for foreign in (foreign_file, foreign_dir, foreign_link):
                with self.assertRaises(preflight.PreflightFailure) as no_clobber:
                    preflight.finalize_published_bundle(
                        release, foreign, records, manifests, "reviewed-owner"
                    )
                self.assertEqual(no_clobber.exception.code, "output_exists")
            self.assertEqual(foreign_file.read_bytes(), b"foreign bytes\n")
            self.assertEqual(foreign_marker.read_bytes(), b"foreign directory\n")
            self.assertTrue(foreign_link.is_symlink())

            raced_foreign = root / "raced-foreign"
            raced_foreign.write_bytes(b"race winner\n")
            with mock.patch.object(
                preflight,
                "finalize_published_bundle",
                side_effect=preflight.PreflightFailure("output_exists", "fixture"),
            ):
                with self.assertRaises(preflight.PreflightFailure):
                    # The CLI layer has no owned identity on reservation
                    # failure and therefore must never remove the race winner.
                    owned_identity = None
                    try:
                        owned_identity = preflight.finalize_published_bundle(
                            release, raced_foreign, records, manifests, "reviewed-owner"
                        )
                    except BaseException:
                        if owned_identity is not None:
                            preflight._remove_owned_output(raced_foreign, owned_identity)
                        raise
            self.assertEqual(raced_foreign.read_bytes(), b"race winner\n")

            owned = root / "owned-output"
            owned.mkdir()
            owned_metadata = owned.lstat()
            old_identity = (owned_metadata.st_dev, owned_metadata.st_ino)
            owned.rmdir()
            owned.mkdir()
            (owned / "foreign-marker").write_bytes(b"replacement\n")
            with self.assertRaises(preflight.PreflightFailure) as replaced:
                preflight._remove_owned_output(owned, old_identity)
            self.assertEqual(replaced.exception.code, "finalization_failed")
            self.assertEqual(
                (owned / "foreign-marker").read_bytes(), b"replacement\n"
            )

            bad_manifest = root / "bad-manifest.json"
            write(bad_manifest, self._remote_manifest("sha256:" + "9" * 64, "api"))
            bad_manifests = dict(manifests)
            bad_manifests["api"] = bad_manifest
            rejected_output = root / "rejected-output"
            with self.assertRaises(preflight.PreflightFailure) as mismatch:
                preflight.finalize_published_bundle(
                    release,
                    rejected_output,
                    records,
                    bad_manifests,
                    "reviewed-owner",
                )
            self.assertEqual(mismatch.exception.code, "remote_manifest_mismatch")
            self.assertFalse(rejected_output.exists())

            stale_metadata = json.loads(
                (published / "release-metadata.json").read_text(encoding="utf-8")
            )
            stale_entry = next(
                item
                for item in stale_metadata["artifacts"]
                if item["name"] == "image-metadata.json"
            )
            stale_entry["sha256"] = "0" * 64
            stale_payload = (
                json.dumps(stale_metadata, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            (published / "release-metadata.json").write_bytes(stale_payload)
            checksum_lines = []
            for line in (published / "SHA256SUMS").read_text(encoding="ascii").splitlines():
                _digest, name = line.split("  ", 1)
                checksum_lines.append(
                    hashlib.sha256((published / name).read_bytes()).hexdigest()
                    + "  "
                    + name
                )
            (published / "SHA256SUMS").write_text(
                "\n".join(checksum_lines) + "\n", encoding="ascii"
            )
            with self.assertRaises(preflight.PreflightFailure) as stale:
                preflight.verify_bundle(
                    published,
                    "0.1.0-rc.1",
                    "a" * 40,
                    require_published_digests=True,
                    registry_owner="reviewed-owner",
                )
            self.assertEqual(stale.exception.code, "identity_mismatch")

    def test_finalization_signal_removes_owned_partial_output_and_restores_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, supplements, corresponding, demo, images = self._inputs(
                root, publication_ready=True
            )
            release = root / "release"
            packager.package(
                source,
                report,
                supplements,
                corresponding,
                demo,
                images,
                release,
                "0.1.0-rc.1",
                123456789,
            )
            records = preflight.verify_bundle(release, "0.1.0-rc.1", "a" * 40)
            manifests = {}
            for role in sorted(preflight.IMAGE_TAGS):
                path = root / (role + "-manifest.json")
                write(path, self._remote_manifest(str(records[role]["image_id"]), role))
                manifests[role] = path
            output = root / "published"
            original_write = preflight._write_new
            calls = 0

            def interrupted_write(path: Path, payload: bytes, mode: int = 0o644) -> None:
                nonlocal calls
                original_write(path, payload, mode)
                calls += 1
                if calls == 1:
                    os.kill(os.getpid(), signal.SIGTERM)
                    os.kill(os.getpid(), signal.SIGINT)

            previous = {
                item: signal.getsignal(item)
                for item in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
            }
            with mock.patch.object(preflight, "_write_new", side_effect=interrupted_write):
                with self.assertRaises(preflight._FinalizationInterrupted) as interrupted:
                    preflight.finalize_published_bundle(
                        release, output, records, manifests, "reviewed-owner"
                    )
            self.assertEqual(interrupted.exception.signum, signal.SIGTERM)
            self.assertFalse(output.exists())
            quarantines = list(root.glob(".published.failed-*"))
            self.assertEqual(len(quarantines), 1)
            self.assertTrue(quarantines[0].is_dir())
            for item, handler in previous.items():
                self.assertIs(signal.getsignal(item), handler)

    def test_publication_main_finalization_is_one_policy_bound_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            arguments = self._main_arguments(root)
            publication = {
                "delivery_method": "co-published-release-assets",
                "public_oci_ready": True,
                "publication_gate": "reviewed-complete-source-delivery",
                "retention": "retain-with-each-public-image-version-for-its-public-lifetime",
                "scope": "complete-reviewed-image-source",
            }
            records = {role: {"image_id": "sha256:" + str(index) * 64} for role, index in (("api", 1), ("builder", 2), ("worker", 3))}
            identity = (123, 456)
            source_policy = {"blender": {}, "publication": publication}
            tracked_source_records = {"README.md": ("100644", 1, "c" * 64)}
            with (
                mock.patch.object(preflight, "_arguments", return_value=arguments),
                mock.patch.object(preflight, "current_revision", return_value="a" * 40),
                mock.patch.object(preflight, "require_normal_index") as normal_index,
                mock.patch.object(preflight, "current_index_digest", return_value="b" * 64),
                mock.patch.object(
                    preflight,
                    "_tracked_blob",
                    side_effect=[b"{}\n", b"0.1.0-rc.1\n"],
                ),
                mock.patch.object(preflight, "_source_policy", return_value=source_policy),
                mock.patch.object(
                    preflight,
                    "_tracked_source_records",
                    return_value=tracked_source_records,
                ),
                mock.patch.object(preflight, "verify_bundle", return_value=records) as verify,
                mock.patch.object(preflight, "verify_live_images"),
                mock.patch.object(preflight.Path, "resolve", return_value=root),
                mock.patch.object(preflight, "finalize_published_bundle", return_value=identity),
                mock.patch.object(preflight, "verify_and_commit_published_bundle") as commit,
                mock.patch.object(
                    preflight,
                    "current_publication_policy",
                    return_value=publication,
                ),
                mock.patch.object(preflight, "_directory_identity", return_value=identity),
            ):
                self.assertEqual(preflight.main([]), 0)
            self.assertGreaterEqual(normal_index.call_count, 2)
            self.assertIs(verify.call_args.args[-3], publication)
            self.assertIs(verify.call_args.args[-2], source_policy)
            self.assertIs(verify.call_args.args[-1], tracked_source_records)
            self.assertEqual(commit.call_args.args[-1], identity)
            self.assertIs(commit.call_args.args[-2], tracked_source_records)
            self.assertIs(commit.call_args.args[-3], source_policy)
            self.assertIs(commit.call_args.args[-4], publication)

    def test_publication_main_signal_quarantines_owned_output_before_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            arguments = self._main_arguments(root)
            publication = {
                "delivery_method": "co-published-release-assets",
                "public_oci_ready": True,
                "publication_gate": "reviewed-complete-source-delivery",
                "retention": "retain-with-each-public-image-version-for-its-public-lifetime",
                "scope": "complete-reviewed-image-source",
            }
            records = {role: {} for role in preflight.IMAGE_TAGS}
            identity = (123, 456)
            source_policy = {"blender": {}, "publication": publication}
            tracked_source_records = {"README.md": ("100644", 1, "c" * 64)}
            with (
                mock.patch.object(preflight, "_arguments", return_value=arguments),
                mock.patch.object(preflight, "current_revision", return_value="a" * 40),
                mock.patch.object(preflight, "require_normal_index"),
                mock.patch.object(preflight, "current_index_digest", return_value="b" * 64),
                mock.patch.object(
                    preflight,
                    "_tracked_blob",
                    side_effect=[b"{}\n", b"0.1.0-rc.1\n"],
                ),
                mock.patch.object(preflight, "_source_policy", return_value=source_policy),
                mock.patch.object(
                    preflight,
                    "_tracked_source_records",
                    return_value=tracked_source_records,
                ),
                mock.patch.object(preflight, "verify_bundle", return_value=records),
                mock.patch.object(preflight, "verify_live_images"),
                mock.patch.object(preflight.Path, "resolve", return_value=root),
                mock.patch.object(preflight, "finalize_published_bundle", return_value=identity),
                mock.patch.object(
                    preflight,
                    "verify_and_commit_published_bundle",
                    side_effect=preflight._FinalizationInterrupted(signal.SIGTERM),
                ),
                mock.patch.object(preflight, "_remove_owned_output") as remove,
            ):
                self.assertEqual(preflight.main([]), 128 + signal.SIGTERM)
            remove.assert_called_once_with(arguments.finalize_output_dir, identity)

    def test_publication_main_rejects_replaced_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            arguments = self._main_arguments(root)
            publication = {
                "delivery_method": "co-published-release-assets",
                "public_oci_ready": True,
                "publication_gate": "reviewed-complete-source-delivery",
                "retention": "retain-with-each-public-image-version-for-its-public-lifetime",
                "scope": "complete-reviewed-image-source",
            }
            identity = (123, 456)
            source_policy = {"blender": {}, "publication": publication}
            tracked_source_records = {"README.md": ("100644", 1, "c" * 64)}
            with (
                mock.patch.object(preflight, "_arguments", return_value=arguments),
                mock.patch.object(preflight, "current_revision", return_value="a" * 40),
                mock.patch.object(preflight, "require_normal_index"),
                mock.patch.object(preflight, "current_index_digest", return_value="b" * 64),
                mock.patch.object(
                    preflight,
                    "_tracked_blob",
                    side_effect=[b"{}\n", b"0.1.0-rc.1\n"],
                ),
                mock.patch.object(preflight, "_source_policy", return_value=source_policy),
                mock.patch.object(
                    preflight,
                    "_tracked_source_records",
                    return_value=tracked_source_records,
                ),
                mock.patch.object(preflight, "verify_bundle", return_value={role: {} for role in preflight.IMAGE_TAGS}),
                mock.patch.object(preflight, "verify_live_images"),
                mock.patch.object(preflight.Path, "resolve", return_value=root),
                mock.patch.object(preflight, "finalize_published_bundle", return_value=identity),
                mock.patch.object(preflight, "verify_and_commit_published_bundle"),
                mock.patch.object(
                    preflight,
                    "current_publication_policy",
                    return_value=publication,
                ),
                mock.patch.object(preflight, "_directory_identity", return_value=(999, 999)),
                mock.patch.object(preflight, "_remove_owned_output") as remove,
            ):
                self.assertEqual(preflight.main([]), 1)
            remove.assert_called_once_with(arguments.finalize_output_dir, identity)

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "killpg"),
        "requires POSIX process groups",
    )
    def test_publication_command_timeout_reaps_term_resistant_descendant(self) -> None:
        process_group = None
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "descendant.pid"
            try:
                with (
                    mock.patch.object(preflight, "PROCESS_TERM_GRACE_SECONDS", 0.1),
                    mock.patch.object(preflight, "PROCESS_KILL_GRACE_SECONDS", 0.8),
                    self.assertRaises(preflight.PreflightFailure) as raised,
                ):
                    preflight._command(
                        self._term_resistant_command(marker),
                        cwd=preflight.ROOT,
                        timeout=0.5,
                    )
                self.assertEqual(raised.exception.code, "command_failed")
                self.assertNotIn("preflight-secret-canary", str(raised.exception))
                self._wait_for_path(marker)
                _descendant_pid, rendered_group = marker.read_text(
                    encoding="ascii"
                ).split()
                process_group = int(rendered_group)
                self.assertGreater(process_group, 1)
                self.assertNotEqual(process_group, os.getpgrp())
                self.assertFalse(self._process_group_exists(process_group))
            finally:
                if (
                    process_group is not None
                    and process_group != os.getpgrp()
                    and self._process_group_exists(process_group)
                ):
                    os.killpg(process_group, signal.SIGKILL)

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "killpg"),
        "requires POSIX process groups",
    )
    def test_publication_command_signals_during_popen_publication_reap_group(
        self,
    ) -> None:
        selected_signals = [signal.SIGINT, signal.SIGTERM]
        if hasattr(signal, "SIGHUP"):
            selected_signals.append(signal.SIGHUP)
        real_popen = subprocess.Popen
        for selected_signal in selected_signals:
            with self.subTest(signal=selected_signal), tempfile.TemporaryDirectory() as temporary:
                process_group = None
                previous = signal.getsignal(selected_signal)
                marker = Path(temporary) / "descendant.pid"

                def signal_before_publication(*args: object, **kwargs: object):
                    process = real_popen(*args, **kwargs)
                    self._wait_for_path(marker)
                    os.kill(os.getpid(), selected_signal)
                    return process

                try:
                    expected = (
                        KeyboardInterrupt
                        if selected_signal == signal.SIGINT
                        else SystemExit
                    )
                    with (
                        mock.patch.object(
                            preflight.subprocess,
                            "Popen",
                            side_effect=signal_before_publication,
                        ),
                        mock.patch.object(
                            preflight, "PROCESS_TERM_GRACE_SECONDS", 0.1
                        ),
                        mock.patch.object(
                            preflight, "PROCESS_KILL_GRACE_SECONDS", 0.8
                        ),
                        self.assertRaises(expected) as raised,
                    ):
                        preflight._command(
                            self._term_resistant_command(marker),
                            cwd=preflight.ROOT,
                            timeout=5,
                        )
                    if selected_signal != signal.SIGINT:
                        self.assertEqual(
                            raised.exception.code, 128 + selected_signal
                        )
                    _descendant_pid, rendered_group = marker.read_text(
                        encoding="ascii"
                    ).split()
                    process_group = int(rendered_group)
                    self.assertNotEqual(process_group, os.getpgrp())
                    self.assertFalse(self._process_group_exists(process_group))
                    self.assertIs(signal.getsignal(selected_signal), previous)
                finally:
                    signal.signal(selected_signal, previous)
                    if (
                        process_group is not None
                        and process_group != os.getpgrp()
                        and self._process_group_exists(process_group)
                    ):
                        os.killpg(process_group, signal.SIGKILL)

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "killpg"),
        "requires POSIX process groups",
    )
    def test_publication_command_base_exception_reaps_owned_group(self) -> None:
        process_group = None
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "descendant.pid"
            real_popen = subprocess.Popen

            def fail_after_publication(*args: object, **kwargs: object):
                process = real_popen(*args, **kwargs)
                self._wait_for_path(marker)
                process.communicate = mock.Mock(
                    side_effect=RuntimeError("trusted wrapper failure")
                )
                return process

            try:
                with (
                    mock.patch.object(
                        preflight.subprocess,
                        "Popen",
                        side_effect=fail_after_publication,
                    ),
                    mock.patch.object(preflight, "PROCESS_TERM_GRACE_SECONDS", 0.1),
                    mock.patch.object(preflight, "PROCESS_KILL_GRACE_SECONDS", 0.8),
                    self.assertRaisesRegex(RuntimeError, "trusted wrapper failure"),
                ):
                    preflight._command(
                        self._term_resistant_command(marker),
                        cwd=preflight.ROOT,
                        timeout=5,
                    )
                _descendant_pid, rendered_group = marker.read_text(
                    encoding="ascii"
                ).split()
                process_group = int(rendered_group)
                self.assertNotEqual(process_group, os.getpgrp())
                self.assertFalse(self._process_group_exists(process_group))
            finally:
                if (
                    process_group is not None
                    and process_group != os.getpgrp()
                    and self._process_group_exists(process_group)
                ):
                    os.killpg(process_group, signal.SIGKILL)

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "killpg"),
        "requires POSIX process groups",
    )
    def test_publication_command_fails_closed_when_group_cannot_be_reaped(
        self,
    ) -> None:
        process = mock.Mock()
        process.pid = 987654321
        process.poll.return_value = 0
        process.communicate.side_effect = RuntimeError("trusted wrapper failure")
        process.stdout = None
        process.stderr = None
        with (
            mock.patch.object(preflight.subprocess, "Popen", return_value=process),
            mock.patch.object(preflight.os, "killpg"),
            mock.patch.object(preflight, "PROCESS_GROUP_POLL_SECONDS", 0.001),
            mock.patch.object(preflight, "PROCESS_TERM_GRACE_SECONDS", 0.1),
            mock.patch.object(preflight, "PROCESS_KILL_GRACE_SECONDS", 0.1),
            self.assertRaises(preflight.PreflightFailure) as raised,
        ):
            preflight._command(
                [sys.executable, "-c", "pass"],
                cwd=preflight.ROOT,
                timeout=2,
            )
        self.assertEqual(raised.exception.code, "command_cleanup_failed")
        self.assertNotIn("trusted wrapper failure", str(raised.exception))

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "killpg"),
        "requires POSIX process groups",
    )
    def test_live_publication_command_term_reaps_group_before_exit(self) -> None:
        controller = None
        process_group = None
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "descendant.pid"
            command = self._term_resistant_command(marker)
            controller_code = (
                "from tests.release.support import load_script;"
                "m=load_script('release_preflight_signal_controller',"
                "'release-publication-preflight');"
                "m.PROCESS_TERM_GRACE_SECONDS=0.1;"
                "m.PROCESS_KILL_GRACE_SECONDS=0.8;"
                "m._command(%r,cwd=m.ROOT,timeout=30)"
            ) % command
            try:
                controller = subprocess.Popen(
                    [sys.executable, "-c", controller_code],
                    cwd=str(preflight.ROOT),
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
                _descendant_pid, rendered_group = marker.read_text(
                    encoding="ascii"
                ).split()
                process_group = int(rendered_group)
                self.assertNotEqual(process_group, os.getpgrp())
                controller.send_signal(signal.SIGTERM)
                controller.wait(timeout=5)
                self.assertEqual(controller.returncode, 128 + signal.SIGTERM)
                self.assertFalse(self._process_group_exists(process_group))
            finally:
                if controller is not None and controller.poll() is None:
                    os.killpg(controller.pid, signal.SIGKILL)
                    controller.wait(timeout=2)
                if (
                    process_group is not None
                    and process_group != os.getpgrp()
                    and self._process_group_exists(process_group)
                ):
                    os.killpg(process_group, signal.SIGKILL)

    def test_publication_command_preserves_custom_and_ignored_handlers(self) -> None:
        def custom_handler(_signum: int, _frame: object) -> None:
            return None

        selected_signals = tuple(
            item
            for item in (
                signal.SIGINT,
                getattr(signal, "SIGHUP", None),
                signal.SIGTERM,
            )
            if isinstance(item, int)
        )
        for selected_signal in selected_signals:
            original = signal.getsignal(selected_signal)
            try:
                for handler in (custom_handler, signal.SIG_IGN):
                    with self.subTest(signal=selected_signal, handler=handler):
                        signal.signal(selected_signal, handler)
                        payload = preflight._command(
                            [sys.executable, "-c", "print('ok')"],
                            cwd=preflight.ROOT,
                            timeout=2,
                        )
                        self.assertEqual(payload, b"ok\n")
                        self.assertIs(signal.getsignal(selected_signal), handler)
            finally:
                signal.signal(selected_signal, original)

    def test_publication_preflight_requires_one_clean_exact_git_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            repository.mkdir()
            write(repository / "VERSION", b"0.1.0-rc.1\n")
            write(repository / "README.md", b"clean fixture\n")
            git(repository, "init", "-q")
            git(repository, "config", "user.name", "Release Test")
            git(repository, "config", "user.email", "release-test@example.invalid")
            git(repository, "add", "--all")
            git(repository, "commit", "-qm", "fixture")

            revision = preflight.current_revision(repository)
            first_digest = preflight.current_index_digest(repository)
            self.assertRegex(revision, r"^[0-9a-f]{40,64}$")
            self.assertRegex(first_digest, r"^[0-9a-f]{64}$")

            write(repository / "untracked.txt", b"not part of the candidate\n")
            with self.assertRaises(preflight.PreflightFailure) as untracked:
                preflight.current_revision(repository)
            self.assertEqual(untracked.exception.code, "worktree_dirty")
            (repository / "untracked.txt").unlink()

            write(repository / "README.md", b"staged but not committed\n")
            git(repository, "add", "README.md")
            self.assertNotEqual(
                preflight.current_index_digest(repository), first_digest
            )
            with self.assertRaises(preflight.PreflightFailure) as staged:
                preflight.current_revision(repository)
            self.assertEqual(staged.exception.code, "worktree_dirty")

    def test_publication_rejects_non_normal_index_and_reads_commit_blobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            repository.mkdir()
            policy = {
                "blender": {
                    "archive": "blender-4.5.12.tar.xz",
                    "bytes": 1,
                    "license": "GPL-3.0-or-later",
                    "official_md5": "c" * 32,
                    "sha256": "d" * 64,
                    "source_url": "https://download.blender.org/source/blender-4.5.12.tar.xz",
                    "version": "4.5.12",
                },
                "format": "hbcb-corresponding-source-policy/v1",
                "publication": {
                    "delivery_method": "co-published-release-assets",
                    "public_oci_ready": False,
                    "publication_gate": "blocked-pending-complete-copyleft-source-review",
                    "retention": "retain-with-each-public-image-version-for-its-public-lifetime",
                    "scope": "project-and-blender-source-only",
                },
            }
            write(repository / "VERSION", b"0.1.0-rc.1\n")
            write(
                repository / "release" / "corresponding-source-policy.json",
                (json.dumps(policy, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            )
            git(repository, "init", "-q")
            git(repository, "config", "user.name", "Release Test")
            git(repository, "config", "user.email", "release-test@example.invalid")
            git(repository, "add", "--all")
            git(repository, "commit", "-qm", "fixture")
            revision = preflight.current_revision(repository)
            expected = preflight.current_publication_policy(repository, "git", revision)
            tracked = preflight._tracked_source_records(repository, "git", revision)
            self.assertEqual(
                tracked["VERSION"],
                (
                    "100644",
                    len(b"0.1.0-rc.1\n"),
                    hashlib.sha256(b"0.1.0-rc.1\n").hexdigest(),
                ),
            )
            git(repository, "update-index", "--skip-worktree", "VERSION")
            (repository / "VERSION").write_text("9.9.9\n", encoding="ascii")
            with self.assertRaises(preflight.PreflightFailure) as flagged:
                preflight.require_normal_index(repository)
            self.assertEqual(flagged.exception.code, "git_identity_invalid")
            self.assertEqual(
                preflight._tracked_blob(repository, "git", revision, "VERSION", 128),
                b"0.1.0-rc.1\n",
            )
            self.assertEqual(
                preflight.current_publication_policy(repository, "git", revision),
                expected,
            )
            git(repository, "update-index", "--no-skip-worktree", "VERSION")

    def test_remote_manifest_rejects_redirects_layer_count_and_foreign_types(self) -> None:
        image_id = "sha256:" + "2" * 64
        valid = json.loads(self._remote_manifest(image_id, "builder"))
        cases = {}
        redirected = json.loads(json.dumps(valid))
        redirected["config"]["urls"] = ["https://private.invalid/config"]
        cases["config_urls"] = redirected
        wrong_count = json.loads(json.dumps(valid))
        wrong_count["layers"].append(dict(wrong_count["layers"][0]))
        cases["layer_count"] = wrong_count
        foreign = json.loads(json.dumps(valid))
        foreign["layers"][0]["mediaType"] = (
            "application/vnd.docker.image.rootfs.foreign.diff.tar.gzip"
        )
        cases["foreign_layer"] = foreign
        for name, value in cases.items():
            with self.subTest(name=name), self.assertRaises(preflight.PreflightFailure):
                preflight._remote_manifest_digest(
                    json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    ),
                    image_id,
                    1,
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
