from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ReleaseWrapperTests(unittest.TestCase):
    def test_full_release_run_id_is_validated_before_scratch_or_docker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-release-id-") as raw:
            checkout = Path(raw)
            (checkout / "scripts").mkdir()
            shutil.copyfile(
                ROOT / "scripts" / "release-check",
                checkout / "scripts" / "release-check",
            )
            shutil.copyfile(
                ROOT / "scripts" / "service-common",
                checkout / "scripts" / "service-common",
            )
            (checkout / "VERSION").write_text("0.1.0\n", encoding="ascii")
            tools = checkout / "tools"
            tools.mkdir()
            marker = checkout / "mktemp.called"
            fake_mktemp = tools / "mktemp"
            fake_mktemp.write_text(
                "#!/bin/sh\n"
                f"printf called > {marker}\n"
                "exit 77\n",
                encoding="utf-8",
            )
            fake_mktemp.chmod(0o700)
            old_python = tools / "old-python"
            old_python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            old_python.chmod(0o700)
            supported_python = tools / "supported-python"
            supported_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            supported_python.chmod(0o700)
            subprocess.run(("git", "init", "-q"), cwd=checkout, check=True)
            subprocess.run(("git", "add", "."), cwd=checkout, check=True)

            base_environment = {
                **os.environ,
                "PATH": str(tools) + os.pathsep + os.environ.get("PATH", ""),
                "PYTHON": str(supported_python),
            }
            base_environment.pop("HBCB_RELEASE_RUN_ID", None)
            base_environment.pop("HBCB_RELEASE_VERSION", None)
            completed = subprocess.run(
                ("sh", "scripts/release-check"),
                cwd=checkout,
                env=base_environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn("HBCB_RELEASE_RUN_ID is required", completed.stdout)
            self.assertFalse(marker.exists())

            completed = subprocess.run(
                ("sh", "scripts/release-check"),
                cwd=checkout,
                env={
                    **base_environment,
                    "PYTHON": str(old_python),
                    "HBCB_RELEASE_RUN_ID": "runtime",
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn("Python 3.11 or newer is required", completed.stdout)
            self.assertFalse(marker.exists())

            completed = subprocess.run(
                ("sh", "scripts/release-check"),
                cwd=checkout,
                env={
                    **base_environment,
                    "HBCB_RELEASE_VERSION": "not-semver",
                    "HBCB_RELEASE_RUN_ID": "runtime",
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn("safe semantic version", completed.stdout)
            self.assertFalse(marker.exists())

            invalid = (
                "a" * 51,
                "-leading",
                "trailing-",
                "trailing_",
                "mixed_-separator",
                "three___underscores",
                "UPPERCASE",
            )
            for run_id in invalid:
                with self.subTest(run_id=run_id):
                    marker.unlink(missing_ok=True)
                    completed = subprocess.run(
                        ("sh", "scripts/release-check"),
                        cwd=checkout,
                        env={**base_environment, "HBCB_RELEASE_RUN_ID": run_id},
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 1, completed.stdout)
                    self.assertIn("1-50 character safe lowercase", completed.stdout)
                    self.assertFalse(marker.exists())

            boundary = "a" * 50
            completed = subprocess.run(
                ("sh", "scripts/release-check"),
                cwd=checkout,
                env={**base_environment, "HBCB_RELEASE_RUN_ID": boundary},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 77, completed.stdout)
            self.assertTrue(marker.exists())

    def test_wrapper_is_non_publishing_syntax_valid_and_complete(self) -> None:
        wrapper = ROOT / "scripts" / "release-check"
        mode = stat.S_IMODE(wrapper.stat().st_mode)
        self.assertTrue(mode & stat.S_IXUSR)
        self.assertFalse(mode & 0o022)
        result = subprocess.run(
            ["sh", "-n", str(wrapper)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = wrapper.read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("git checkout-index"), 2)
        self.assertEqual(text.count("umask 022"), 2)
        self.assertIn('chmod 0700 "$scratch"', text)
        self.assertGreaterEqual(text.count('DOCKER="$docker_bin"'), 7)
        for cleanup_contract in (
            "project_resources()",
            "initial_resources=$(project_resources) ||",
            "pre_service_resources=$(project_resources) ||",
            ': > "$service_ownership"',
            "remaining_resources=$(project_resources 2>/dev/null) ||",
            "remaining_builder=",
            "isolated resource cleanup failed",
            "cleanup_signal_status=0",
            "trap 'record_cleanup_signal 129' 1",
            'status=$cleanup_signal_status',
            "trap 'cancel_summary_publish 143' 15",
            "trap '' 1 2 15",
        ):
            self.assertIn(cleanup_contract, text)
        self.assertNotIn("down --volumes --remove-orphans >/dev/null 2>&1 || true", text)
        cleanup_text = text[text.index("cleanup() {") : text.index("finalize_cleanup() {")]
        self.assertTrue(
            cleanup_text.startswith(
                "cleanup() {\n"
                "  # Disable recursive EXIT cleanup. Record only the first termination signal so\n"
                "  # cleanup can finish, while repeated or different signals cannot replace it.\n"
                "  trap 'record_cleanup_signal 129' 1\n"
                "  trap 'record_cleanup_signal 130' 2\n"
                "  trap 'record_cleanup_signal 143' 15\n"
            )
        )
        self.assertIn("trap 'cleanup $?' 0", text)
        publish_tail = (
            'ln "$summary_stage" "$summary_target" || cancel_summary_publish 1',
            "summary_promoted=1",
            'rm -f -- "$summary_stage" || cancel_summary_publish 1',
            'chmod 0600 "$summary_target" || cancel_summary_publish 1',
            "trap '' 1 2 15",
            "printf 'RELEASE_CHECK: PASS evidence=%s\\n' \"$evidence\"",
        )
        publish_text = text[text.index(publish_tail[0]) :]
        publish_offsets = [publish_text.index(fragment) for fragment in publish_tail]
        self.assertEqual(publish_offsets, sorted(publish_offsets))
        for required in (
            "scripts/release-audit",
            "make check",
            "make demo",
            "make verify-demo",
            "make service-smoke",
            "make minio-security-check",
            "make g8-static",
            "make g8-caddy",
            "make g8-recovery",
            "scripts/dependency-audit",
            "scripts/service-sbom",
            "scripts/fetch-corresponding-source",
            "scripts/release-artifacts",
            "--corresponding-source-dir",
            'MINIO_IMAGE="$HBCB_MINIO_IMAGE"',
            "--demo-artifacts",
            '"builder=$image_dir/builder.json"',
            '"api=$image_dir/api.json"',
            '"worker=$image_dir/worker.json"',
            "down --volumes --remove-orphans",
            'PYTHON="$python_bin"',
            '--tag "$api_release_image"',
            '--tag "$worker_release_image"',
        ):
            self.assertIn(required, text)
        for forbidden in (
            r"\bgit\s+push\b",
            r"\bdocker\s+push\b",
            r"\bgh\s+release\s+create\b",
            r"\bwget\b",
            r"tag\s+hbcb-service-(?:api|worker):dev",
        ):
            self.assertIsNone(re.search(forbidden, text))

    def test_make_and_docker_release_wiring_is_explicit(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in (
            "dependency-check",
            "dependency-audit",
            "dependency-scan",
            "worker-boundary-check",
            "release-static",
            "security-check",
            "release-check",
        ):
            self.assertRegex(makefile, rf"(?m)^{re.escape(target)}:")
        self.assertIn("HBCB_INDEX_AUDITED", makefile)
        self.assertIn("env -u HBCB_COMPOSE_BIN", makefile)
        self.assertIn("service-test-image", makefile)
        self.assertGreaterEqual(
            makefile.count(
                'HBCB_DISTRIBUTION_VERSION=$${HBCB_DISTRIBUTION_VERSION:-0.1.0-local}'
            ),
            4,
        )
        self.assertGreaterEqual(
            makefile.count('HBCB_SOURCE_REVISION=$${HBCB_SOURCE_REVISION:-uncommitted}'),
            4,
        )
        self.assertNotIn("$(DISTRIBUTION_VERSION)", makefile)
        self.assertNotIn("$(SOURCE_REVISION)", makefile)
        self.assertIn("tests/service_unit", makefile)
        self.assertIn("/test-exec:rw,nosuid,nodev,exec", makefile)
        self.assertRegex(
            makefile,
            r"(?m)^check:.*\bworker-boundary-check\b",
        )
        boundary_recipe = makefile[
            makefile.index("worker-boundary-image:") : makefile.index("validate build inspect:")
        ]
        for required in (
            "--target worker",
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges:true",
            "--user 65532:65532",
            "tests/security/worker_process_boundary_gate.py",
        ):
            self.assertIn(required, boundary_recipe)

        builder = (ROOT / "docker" / "builder.Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            builder,
            r"(?s)FROM builder-base AS test.*?COPY \. /opt/builder/source",
        )
        self.assertGreaterEqual(builder.count("chmod -R a+rX,a-w"), 2)
        service = (ROOT / "docker" / "service.Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertGreaterEqual(service.count("THIRD_PARTY_NOTICES.md"), 2)
        self.assertGreaterEqual(service.count("service-dependency-licenses.json"), 2)
        self.assertGreaterEqual(service.count("license-policy.json"), 2)
        self.assertIn("FROM service-dependencies AS service-test-dependencies", service)
        self.assertIn("--no-deps", service)
        self.assertIn("docker/service-test-requirements.lock", service)
        self.assertLess(
            service.index("FROM service-base AS api"),
            service.index("FROM service-dependencies AS service-test-dependencies"),
        )
        test_lock = (ROOT / "docker" / "service-test-requirements.lock").read_text(
            encoding="utf-8"
        )
        for package in ("httpcore2==2.12.0", "httpx2==2.12.0", "truststore==0.10.4"):
            self.assertIn(package, test_lock)
        self.assertEqual(test_lock.count("--hash=sha256:"), 3)

    def test_image_inspection_supports_older_docker_clients(self) -> None:
        inspected = (
            "Makefile",
            "scripts/g8-recovery-drill",
            "scripts/service-compose",
            "scripts/service-smoke",
            "scripts/release-check",
            "tests/deployment/g8_caddy_gate.py",
        )
        for relative in inspected:
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"\bimage\s+inspect(?:[ \t]|\\\n)*--platform\b", text),
                relative,
            )

        for relative in (
            "Makefile",
            "scripts/g8-recovery-drill",
            "scripts/service-compose",
            "scripts/service-smoke",
        ):
            self.assertIn(
                "{{.Os}}/{{.Architecture}}",
                (ROOT / relative).read_text(encoding="utf-8"),
                relative,
            )
        caddy_gate = (ROOT / "tests/deployment/g8_caddy_gate.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('[docker, "image", "inspect", CADDY_REFERENCE]', caddy_gate)
        self.assertIn('CADDY_PLATFORM = "linux/amd64"', caddy_gate)
        self.assertIn('"$CADDY_VERSION"', caddy_gate)
        self.assertIn("caddy version", caddy_gate)
        self.assertIn("uname -s", caddy_gate)
        self.assertIn("uname -m", caddy_gate)
        self.assertIn('"platform": CADDY_PLATFORM', caddy_gate)
        for relative in ("scripts/service-compose", "scripts/service-smoke"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("HBCB_BUILDER_IMAGE=$builder_image", text, relative)
            self.assertNotIn("HBCB_BUILDER_IMAGE=$builder_id", text, relative)
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertRegex(makefile, r"(?m)^\s*\$\(DOCKER\) build .*--platform")
        self.assertIn('--platform "$(PLATFORM)"', makefile)

    def test_preview_provenance_and_required_public_files(self) -> None:
        required = (
            "CHANGELOG.md",
            "GOVERNANCE.md",
            "MAINTAINERS.md",
            "OUTPUT_POLICY.md",
            "THIRD_PARTY_NOTICES.md",
            "VERSION",
            "docs/architecture.md",
            "docs/backlog.md",
            "docs/compatibility.md",
            "docs/dependency-maintenance.md",
            "docs/licensing.md",
            "docs/release-process.md",
            "docs/oci-publication.md",
            "docs/release-notes/v0.1.0-rc.1.md",
            ".github/CODEOWNERS",
            ".github/pull_request_template.md",
            ".github/workflows/dependency-audit.yml",
            "release/dependency-policy.json",
            "release/vulnerability-policy.json",
            "scripts/dependency-audit",
            "scripts/dependency-lock-from-wheels",
            "scripts/dependency-scan",
        )
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)

        manifest_path = ROOT / "docs" / "assets" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("manifest_version"), "docs-assets/v1")
        self.assertEqual(len(manifest.get("assets", [])), 1)
        record = manifest["assets"][0]
        self.assertEqual(record.get("path"), "docs/assets/facet-bot-preview.png")
        self.assertEqual(record.get("license"), "CC0-1.0")
        self.assertEqual(record.get("source", {}).get("build_qa_status"), "passed")
        self.assertEqual(record.get("source", {}).get("smoke_result"), "PASS")
        preview = ROOT / record["path"]
        payload = preview.read_bytes()
        self.assertLess(len(payload), 500_000)
        self.assertEqual(record.get("bytes"), len(payload))
        self.assertEqual(record.get("sha256"), hashlib.sha256(payload).hexdigest())
        self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("![Facet Bot", readme)
        self.assertIn("docs/assets/manifest.json", readme)
        self.assertIn("not a generated illustration", readme)

    def test_relative_markdown_links_resolve(self) -> None:
        link_pattern = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
        failures: list[str] = []
        for document in sorted(ROOT.rglob("*.md")):
            if any(part in {".git", "build"} for part in document.parts):
                continue
            text = document.read_text(encoding="utf-8")
            for raw_target in link_pattern.findall(text):
                target = raw_target.strip().strip("<>").split("#", 1)[0]
                if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                    continue
                resolved = (document.parent / target).resolve()
                try:
                    resolved.relative_to(ROOT)
                except ValueError:
                    failures.append(f"{document.relative_to(ROOT)} -> {raw_target}")
                    continue
                if not resolved.exists():
                    failures.append(f"{document.relative_to(ROOT)} -> {raw_target}")
        self.assertEqual(failures, [])

    def test_base_version_is_consistent(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="ascii").strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        for relative in ("pyproject.toml", "service/pyproject.toml"):
            self.assertIn(
                f'version = "{version}"',
                (ROOT / relative).read_text(encoding="utf-8"),
            )
        for relative in ("docker/builder.Dockerfile", "docker/service.Dockerfile"):
            dockerfile = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(f"HBCB_DISTRIBUTION_VERSION={version}-local", dockerfile)
            self.assertIn(
                'org.opencontainers.image.version="${HBCB_DISTRIBUTION_VERSION}"',
                dockerfile,
            )
            self.assertIn(
                'org.opencontainers.image.revision="${HBCB_SOURCE_REVISION}"',
                dockerfile,
            )
        wrapper = (ROOT / "scripts" / "release-check").read_text(encoding="utf-8")
        self.assertIn('HBCB_DISTRIBUTION_VERSION="$rc_version"', wrapper)
        self.assertIn('HBCB_SOURCE_REVISION="$source_revision"', wrapper)
        self.assertGreaterEqual(
            wrapper.count('--build-arg "HBCB_DISTRIBUTION_VERSION=$rc_version"'),
            2,
        )
        self.assertGreaterEqual(
            wrapper.count('--build-arg "HBCB_SOURCE_REVISION=$source_revision"'),
            2,
        )
        self.assertIn(
            f"[{version}-rc.1]",
            (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
