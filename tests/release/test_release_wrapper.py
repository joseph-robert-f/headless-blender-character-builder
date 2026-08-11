from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ReleaseWrapperTests(unittest.TestCase):
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
        for required in (
            "scripts/release-audit",
            "make check",
            "make demo",
            "make verify-demo",
            "make service-smoke",
            "make g8-static",
            "make g8-caddy",
            "make g8-recovery",
            "scripts/dependency-audit",
            "scripts/service-sbom",
            "scripts/release-artifacts",
            "--demo-artifacts",
            '"builder=$image_dir/builder.json"',
            '"api=$image_dir/api.json"',
            '"worker=$image_dir/worker.json"',
            "down --volumes --remove-orphans",
        ):
            self.assertIn(required, text)
        for forbidden in (
            r"\bgit\s+push\b",
            r"\bdocker\s+push\b",
            r"\bgh\s+release\s+create\b",
            r"\bcurl\b",
            r"\bwget\b",
        ):
            self.assertIsNone(re.search(forbidden, text))

    def test_make_and_docker_release_wiring_is_explicit(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in (
            "dependency-check",
            "dependency-audit",
            "dependency-scan",
            "release-static",
            "security-check",
            "release-check",
        ):
            self.assertRegex(makefile, rf"(?m)^{re.escape(target)}:")
        self.assertIn("HBCB_INDEX_AUDITED", makefile)
        self.assertIn("env -u HBCB_COMPOSE_BIN", makefile)
        self.assertIn("service-test-image", makefile)
        self.assertIn("tests/service_unit", makefile)
        self.assertIn("/test-exec:rw,nosuid,nodev,exec", makefile)

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
        for package in ("httpcore2==2.7.0", "httpx2==2.7.0", "truststore==0.10.4"):
            self.assertIn(package, test_lock)
        self.assertEqual(test_lock.count("--hash=sha256:"), 3)

    def test_image_inspection_supports_older_docker_clients(self) -> None:
        inspected = (
            "Makefile",
            "scripts/service-compose",
            "scripts/service-smoke",
            "scripts/release-check",
        )
        for relative in inspected:
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"\bimage\s+inspect(?:[ \t]|\\\n)*--platform\b", text),
                relative,
            )

        for relative in ("Makefile", "scripts/service-compose", "scripts/service-smoke"):
            self.assertIn(
                "{{.Os}}/{{.Architecture}}",
                (ROOT / relative).read_text(encoding="utf-8"),
                relative,
            )
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
            "docs/release-notes/v0.1.0-rc.1.md",
            ".github/CODEOWNERS",
            ".github/pull_request_template.md",
            ".github/workflows/dependency-audit.yml",
            "release/dependency-policy.json",
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
            self.assertIn(
                f'org.opencontainers.image.version="{version}"',
                (ROOT / relative).read_text(encoding="utf-8"),
            )
        self.assertIn(
            f"[{version}-rc.1]",
            (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
