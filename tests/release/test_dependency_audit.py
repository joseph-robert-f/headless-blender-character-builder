from __future__ import annotations

import contextlib
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.release.support import ROOT, load_script, write


audit_tool = load_script("dependency_audit_under_test", "dependency-audit")
scan_tool = load_script("dependency_scan_under_test", "dependency-scan")

FIXTURE_FILES = (
    ".github/workflows/ci.yml",
    ".github/workflows/dependency-audit.yml",
    ".github/workflows/release-candidate.yml",
    "THIRD_PARTY_NOTICES.md",
    "compose.yaml",
    "deploy/vps/compose.yaml",
    "deploy/vps/release.lock.env.example",
    "docker/BLENDER_SOURCE_NOTICE.md",
    "docker/blender-download.sha256",
    "docker/builder.Dockerfile",
    "docker/caddy.Dockerfile",
    "docker/minio.Dockerfile",
    "docker/postgres.Dockerfile",
    "docker/service.Dockerfile",
    "docker/service-requirements.lock",
    "docker/service-test-requirements.lock",
    "docker/test-requirements.lock",
    "docs/dependency-maintenance.md",
    "docs/threat-model.md",
    "pyproject.toml",
    "release/dependency-policy.json",
    "release/corresponding-source-policy.json",
    "release/service-dependency-licenses.json",
    "release/vulnerability-policy.json",
    "scripts/fetch-corresponding-source",
    "scripts/g8-recovery-drill",
    "scripts/dependency-scan",
    "scripts/minio-recipe-id",
    "scripts/release-artifacts",
    "scripts/release-check",
    "scripts/release-publication-preflight",
    "scripts/service-compose",
    "service/pyproject.toml",
    "tests/deployment/g8_recovery_compose.yaml",
    "tests/deployment/g8_caddy_gate.py",
    "tests/deployment/test_g8_recovery_drill.py",
    "tests/security/postgres_fixture_gate.py",
    "tests/service_integration/g8_orphan_minio_compose.yaml",
)


def fixture_root(parent: Path) -> Path:
    root = parent / "repository"
    for relative in FIXTURE_FILES:
        source = ROOT / relative
        mode = stat.S_IMODE(source.stat().st_mode)
        write(root / relative, source.read_bytes(), mode)
    return root


def replace_once(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise AssertionError("fixture mutation target is not unique: " + relative)
    mode = stat.S_IMODE(path.stat().st_mode)
    path.chmod(mode | stat.S_IWUSR)
    try:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
    finally:
        path.chmod(mode)


def checks_by_id(report: dict[str, object]) -> dict[str, dict[str, object]]:
    checks = report.get("checks")
    if not isinstance(checks, list):
        raise AssertionError("dependency report has no checks")
    return {
        str(item["id"]): item
        for item in checks
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


class DependencyAuditTests(unittest.TestCase):
    def assert_check_failure(
        self, report: dict[str, object], identifier: str, detail: str
    ) -> None:
        self.assertEqual(report.get("status"), "findings")
        checks = checks_by_id(report)
        self.assertIn(identifier, checks)
        self.assertEqual(checks[identifier].get("status"), "failure")
        details = checks[identifier].get("details")
        self.assertIsInstance(details, list)
        self.assertTrue(
            any(detail in str(item) for item in details),
            "%s did not report %r: %r" % (identifier, detail, details),
        )
        self.assertFalse(
            any(item.get("status") == "error" for item in checks.values())
        )

    def assert_input_error(self, report: dict[str, object], detail: str) -> None:
        self.assertEqual(report.get("status"), "incomplete")
        checks = checks_by_id(report)
        self.assertIn("audit-input", checks)
        self.assertEqual(checks["audit-input"].get("status"), "error")
        details = checks["audit-input"].get("details")
        self.assertIsInstance(details, list)
        self.assertTrue(
            any(detail in str(item) for item in details),
            "audit-input did not report %r: %r" % (detail, details),
        )

    def test_offline_audit_is_deterministic_complete_and_network_free(self) -> None:
        with mock.patch.object(
            audit_tool.urllib.request,
            "urlopen",
            side_effect=AssertionError("offline audit attempted network access"),
        ):
            first = audit_tool.run_audit(ROOT, online=False)
            second = audit_tool.run_audit(ROOT, online=False)

        self.assertEqual(first, second)
        self.assertEqual(first.get("format"), "hbcb-dependency-audit/v1")
        self.assertEqual(first.get("mode"), "offline")
        self.assertEqual(first.get("status"), "pass")
        self.assertEqual(first.get("updates"), [])
        checks = checks_by_id(first)
        self.assertEqual(
            set(checks),
            {
                "compose-postgres",
                "compose-redis-server",
                "docker-base",
                "dockerfile-frontend",
                "literal-image-caddy",
                "manual-review-inventory",
                "python-builder-runtime",
                "python-builder-test",
                "python-service-runtime",
                "python-service-test",
            },
        )
        self.assertTrue(all(item.get("status") == "pass" for item in checks.values()))
        images = first.get("images")
        self.assertIsInstance(images, list)
        self.assertEqual(
            {item.get("id") for item in images if isinstance(item, dict)},
            {"caddy", "docker-base", "postgres", "redis-server"},
        )
        caddy = next(item for item in images if item.get("id") == "caddy")
        self.assertEqual(caddy["scan_mode"], "local-build")
        gate_constants = audit_tool.python_string_assignments(
            (ROOT / "tests/deployment/g8_caddy_gate.py").read_text(encoding="utf-8"),
            "tests/deployment/g8_caddy_gate.py",
        )
        self.assertEqual(caddy["reference"], gate_constants["CADDY_REFERENCE"])
        manual = first.get("manual_review")
        self.assertIsInstance(manual, list)
        self.assertEqual(
            {item.get("id") for item in manual if isinstance(item, dict)},
            audit_tool.EXPECTED_MANUAL_REVIEW_IDS,
        )
        manual_by_id = {
            str(item["id"]): item
            for item in manual
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        self.assertEqual(set(manual_by_id), set(audit_tool.EXPECTED_MANUAL_REVIEW_FILES))
        self.assertEqual(set(manual_by_id), set(audit_tool.EXPECTED_MANUAL_REVIEW_NAMES))
        for identifier, item in manual_by_id.items():
            self.assertEqual(
                set(item["files"]), audit_tool.EXPECTED_MANUAL_REVIEW_FILES[identifier]
            )
            self.assertEqual(
                item["name"], audit_tool.EXPECTED_MANUAL_REVIEW_NAMES[identifier]
            )
        json.dumps(first, sort_keys=True)
        rendered = audit_tool.markdown(first)
        self.assertIn("Status: **pass**", rendered)
        self.assertIn("Mode: `offline`", rendered)

    def test_custom_caddy_source_and_operator_example_cannot_drift(self) -> None:
        mutations = (
            (
                "docker/caddy.Dockerfile",
                "releases/download/v2.11.4/caddy_2.11.4_buildable-artifact.tar.gz",
                "releases/download/v2.11.3/caddy_2.11.3_buildable-artifact.tar.gz",
                "custom Caddy recipe source or version is stale",
            ),
            (
                "deploy/vps/release.lock.env.example",
                "ghcr.io/joseph-robert-f/hbcb-caddy:v2.11.4-hbcb.1@sha256:",
                "caddy:2.11.4-alpine@sha256:",
                "does not preserve the reviewed tag",
            ),
        )
        for relative, old, new, detail in mutations:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = fixture_root(Path(temporary))
                replace_once(root, relative, old, new)
                self.assert_check_failure(
                    audit_tool.run_audit(root, online=False),
                    "literal-image-caddy",
                    detail,
                )

    def test_service_runtime_parser_covers_all_six_direct_dependencies(self) -> None:
        values = audit_tool.parse_toml_string_array(
            (ROOT / "service" / "pyproject.toml").read_text(encoding="utf-8"),
            "project",
            "dependencies",
        )
        parsed = [audit_tool.parse_exact_requirement(value) for value in values]
        self.assertEqual(
            [item["name"] for item in parsed],
            ["async-timeout", "fastapi", "minio", "psycopg", "redis", "uvicorn"],
        )
        self.assertEqual(parsed[3]["display"], "psycopg[binary]")

    def test_notice_versions_are_matched_as_complete_tokens(self) -> None:
        self.assertFalse(
            audit_tool.table_row_has_version(
                "| redis-py | 18.1.0 | MIT |", "redis-py", "8.1.0"
            )
        )
        self.assertFalse(
            audit_tool.table_row_has_version(
                "| redis-py | 8.1.00 | MIT |", "redis-py", "8.1.0"
            )
        )

    def test_networked_scan_is_checksum_pinned_bounded_and_fail_closed(self) -> None:
        script = ROOT / "scripts" / "dependency-scan"
        mode = stat.S_IMODE(script.stat().st_mode)
        self.assertTrue(mode & stat.S_IXUSR)
        self.assertFalse(mode & 0o022)
        text = script.read_text(encoding="utf-8")
        self.assertEqual(scan_tool.SCANNER_VERSION, "2.3.8")
        self.assertIn("https://github.com/google/osv-scanner/releases/download/", text)
        self.assertIn(
            "bc98e15319ed0d515e3f9235287ba53cdc5535d576d24fd573978ecfe9ab92dc",
            text,
        )
        self.assertIn("MAX_SCANNER_BYTES", text)
        self.assertNotIn("shell=True", text)
        self.assertNotIn("git push", text)
        self.assertEqual(scan_tool.scanner_status(0), "pass")
        self.assertEqual(scan_tool.scanner_status(1), "findings")
        for code in (2, 127, 128, 255):
            self.assertEqual(scan_tool.scanner_status(code), "incomplete")
        self.assertEqual(
            scan_tool.final_status([{"status": "pass"}], []), "pass"
        )
        self.assertEqual(
            scan_tool.final_status([{"status": "findings"}], []), "findings"
        )
        self.assertEqual(
            scan_tool.final_status([{"status": "pass"}], ["network"]),
            "incomplete",
        )
        timed_out = mock.Mock(pid=12345)
        timed_out.poll.return_value = 0

        def process_group_signal(_process_group, selected_signal):
            if selected_signal == 0:
                raise ProcessLookupError

        with mock.patch.object(
            scan_tool.subprocess,
            "Popen",
            return_value=timed_out,
        ), mock.patch.object(
            scan_tool.os,
            "killpg",
            side_effect=process_group_signal,
        ) as kill_group:
            self.assertEqual(scan_tool.run(["scan"], timeout=0), 124)
        self.assertEqual(
            kill_group.call_args_list,
            [
                mock.call(12345, scan_tool.signal.SIGTERM),
                mock.call(12345, 0),
            ],
        )
        with mock.patch.object(scan_tool.subprocess, "Popen", side_effect=OSError):
            self.assertEqual(scan_tool.run(["scan"]), 127)

        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "osv.json"
            report.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "packages": [],
                                "source": str(ROOT / "docker"),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            code, name = scan_tool.validate_scan_report(report, 0)
            self.assertEqual((code, name), (0, "osv.json"))
            self.assertNotIn(str(ROOT), report.read_text(encoding="utf-8"))

            invalid = Path(temporary) / "invalid.json"
            invalid.write_text("not json", encoding="utf-8")
            self.assertEqual(
                scan_tool.validate_scan_report(invalid, 0), (127, None)
            )
            self.assertFalse(invalid.exists())

    def test_report_output_refuses_existing_files_and_symlinks(self) -> None:
        with self.subTest(surface="existing file"), tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.json"
            report.write_text("operator-owned\n", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = audit_tool.main(["--root", str(ROOT), "--json", str(report)])
            self.assertEqual(code, 2)
            self.assertEqual(report.read_text(encoding="utf-8"), "operator-owned\n")
            self.assertIn("DEPENDENCY_AUDIT: output failed:", stderr.getvalue())
            self.assertLessEqual(len(stderr.getvalue()), 550)
            self.assertEqual(stdout.getvalue(), "")

        with self.subTest(surface="symlink"), tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target.json"
            target.write_text("target-owned\n", encoding="utf-8")
            report = Path(temporary) / "report.json"
            report.symlink_to(target)
            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                code = audit_tool.main(["--root", str(ROOT), "--json", str(report)])
            self.assertEqual(code, 2)
            self.assertTrue(report.is_symlink())
            self.assertEqual(target.read_text(encoding="utf-8"), "target-owned\n")
            self.assertIn("DEPENDENCY_AUDIT: output failed:", stderr.getvalue())

    def test_python_declaration_and_reviewed_lock_mutations_are_detected(self) -> None:
        with self.subTest(surface="direct declaration"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "service/pyproject.toml",
                '"fastapi==0.141.1"',
                '"fastapi==0.141.2"',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(report, "python-service-runtime", "fastapi")

        with self.subTest(surface="reviewed lock hash"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            lock = root / "docker" / "service-requirements.lock"
            lock.write_bytes(lock.read_bytes() + b"# mutation fixture\n")
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "python-service-runtime", "license inventory hash is stale"
            )

        with self.subTest(surface="dependency-free builder runtime"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "pyproject.toml",
                "dependencies = []",
                'dependencies = ["requests==9.9.9"]',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "python-builder-runtime", "must keep this dependency array empty"
            )

        with self.subTest(surface="httpx2/httpcore2 coupling"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "docker/service-test-requirements.lock",
                "httpcore2==2.12.0",
                "httpcore2==9.9.9",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(report, "python-service-test", "httpcore2")

        with self.subTest(surface="complete test-lock notices"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "docker/service-test-requirements.lock",
                "truststore==0.10.4",
                "truststore==0.10.5",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "python-service-test", "stale for locked truststore"
            )

    def test_dockerfile_frontend_mutations_are_detected(self) -> None:
        reviewed = (
            "docker/dockerfile:1.25@sha256:"
            "0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12"
        )
        with self.subTest(surface="mismatched directive"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            changed = reviewed[:-1] + "0"
            replace_once(root, "docker/minio.Dockerfile", reviewed, changed)
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "dockerfile-frontend", "does not use the reviewed"
            )

        with self.subTest(surface="missing digest"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            unpinned = "docker/dockerfile:1.25"
            for relative in ("docker/minio.Dockerfile", "docker/service.Dockerfile"):
                replace_once(root, relative, reviewed, unpinned)
            policy_path = root / "release" / "dependency-policy.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["dockerfile_frontend"]["reference"] = unpinned
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "dockerfile-frontend", "not digest pinned"
            )

        with self.subTest(surface="floating major tag"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            floating = reviewed.replace("docker/dockerfile:1.25@", "docker/dockerfile:1@")
            for relative in ("docker/minio.Dockerfile", "docker/service.Dockerfile"):
                replace_once(root, relative, reviewed, floating)
            policy_path = root / "release" / "dependency-policy.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["dockerfile_frontend"]["reference"] = floating
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "dockerfile-frontend", "not an exact version"
            )

    def test_manual_review_inventory_cannot_be_empty_missing_or_duplicated(self) -> None:
        with self.subTest(surface="empty inventory"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            path = root / "release" / "dependency-policy.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["manual_review"] = []
            path.write_text(json.dumps(document), encoding="utf-8")
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "manual-review-inventory", "inventory is empty"
            )

        with self.subTest(surface="missing expected entry"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            path = root / "release" / "dependency-policy.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["manual_review"] = document["manual_review"][1:]
            path.write_text(json.dumps(document), encoding="utf-8")
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "manual-review-inventory", "missing expected manual-review"
            )

        with self.subTest(surface="duplicate identifier"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            path = root / "release" / "dependency-policy.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["manual_review"].append(dict(document["manual_review"][0]))
            path.write_text(json.dumps(document), encoding="utf-8")
            report = audit_tool.run_audit(root, online=False)
            self.assert_input_error(
                report, "duplicate manual review policy identifier"
            )

        for identifier in sorted(audit_tool.EXPECTED_MANUAL_REVIEW_FILES):
            with self.subTest(surface="review files", identifier=identifier), tempfile.TemporaryDirectory() as temporary:
                root = fixture_root(Path(temporary))
                path = root / "release" / "dependency-policy.json"
                document = json.loads(path.read_text(encoding="utf-8"))
                entry = next(
                    item for item in document["manual_review"] if item["id"] == identifier
                )
                entry["files"] = entry["files"][1:]
                path.write_text(json.dumps(document), encoding="utf-8")
                report = audit_tool.run_audit(root, online=False)
                self.assert_check_failure(
                    report,
                    "manual-review-inventory",
                    "expected inventory for " + identifier,
                )

        with self.subTest(surface="review name"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            path = root / "release" / "dependency-policy.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["manual_review"][0]["name"] = "Unreviewed label"
            identifier = document["manual_review"][0]["id"]
            path.write_text(json.dumps(document), encoding="utf-8")
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report,
                "manual-review-inventory",
                "expected inventory for " + identifier,
            )

    def test_policy_identifiers_must_be_safe_and_globally_unique(self) -> None:
        with self.subTest(surface="unsafe identifier"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            path = root / "release" / "dependency-policy.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["python_groups"][0]["id"] = "Unsafe_ID"
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assert_input_error(
                audit_tool.run_audit(root, online=False), "policy identifier is unsafe"
            )

        with self.subTest(surface="duplicate within namespace"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            path = root / "release" / "dependency-policy.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["python_groups"][1]["id"] = document["python_groups"][0]["id"]
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assert_input_error(
                audit_tool.run_audit(root, online=False),
                "duplicate Python policy identifier",
            )

        with self.subTest(surface="duplicate across namespaces"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            path = root / "release" / "dependency-policy.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["literal_images"][0]["id"] = document["compose_images"][0]["id"]
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assert_input_error(
                audit_tool.run_audit(root, online=False),
                "reused across Compose and literal image namespaces",
            )

    def test_input_io_and_recursion_fail_closed(self) -> None:
        for failure in (OSError("fixture I/O failure"), RecursionError("fixture recursion")):
            with self.subTest(failure=type(failure).__name__), mock.patch.object(
                audit_tool, "load_policy", side_effect=failure
            ):
                self.assert_input_error(
                    audit_tool.run_audit(ROOT, online=False), str(failure)
                )

    def test_caddy_version_evidence_and_platform_mutations_are_detected(self) -> None:
        source = (ROOT / "tests" / "deployment" / "g8_caddy_gate.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('"inspect",\n        "--platform"', source)

        with self.subTest(surface="emitted version evidence"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                '"version": CADDY_VERSION',
                '"version": "2.11.3"',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "emitted evidence"
            )

        with self.subTest(surface="pull platform"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                '[docker, "pull", "--platform", CADDY_PLATFORM, CADDY_REFERENCE]',
                '[docker, "pull", "--platform", "linux/arm64", CADDY_REFERENCE]',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "pull command"
            )

        with self.subTest(surface="pull executable"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                '[docker, "pull", "--platform", CADDY_PLATFORM, CADDY_REFERENCE]',
                '["podman", "pull", "--platform", CADDY_PLATFORM, CADDY_REFERENCE]',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "pull command"
            )

        with self.subTest(surface="pull platform ordering"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                '[docker, "pull", "--platform", CADDY_PLATFORM, CADDY_REFERENCE]',
                '[docker, "pull", CADDY_REFERENCE, "--platform", CADDY_PLATFORM]',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "pull command"
            )

        with self.subTest(surface="runtime identity command"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                "'printf \\'%s\\\\n\\' \"$CADDY_VERSION\"\\ncaddy version\\nuname -s\\nuname -m'",
                "'caddy version'",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "fixed runtime identity probe"
            )

        with self.subTest(surface="unused runtime identity decoy"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                "'printf \\'%s\\\\n\\' \"$CADDY_VERSION\"\\ncaddy version\\nuname -s\\nuname -m'",
                "'caddy version'",
            )
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                "\n\nclass GateFailure",
                "\n\nUNUSED_PROBE = [\n"
                '    "/bin/sh",\n'
                '    "-eu",\n'
                '    "-c",\n'
                "    'printf \\'%s\\\\n\\' \"$CADDY_VERSION\"\\ncaddy version\\nuname -s\\nuname -m',\n"
                "]\n\n\nclass GateFailure",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "fixed runtime identity probe"
            )

        with self.subTest(surface="inspect platform flag"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                '[docker, "image", "inspect", CADDY_REFERENCE]',
                '[docker, "image", "inspect", "--platform", "linux/amd64", CADDY_REFERENCE]',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "legacy-compatible image inspection"
            )

        with self.subTest(surface="inspected digest"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                'f"sha256:{CADDY_DIGEST}" not in digest_candidates',
                '"sha256:" + "0" * 64 not in digest_candidates',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "inspected digest identity"
            )

        with self.subTest(surface="inspected digest decoy"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                '    if f"sha256:{CADDY_DIGEST}" not in digest_candidates:\n',
                '    if CADDY_DIGEST == "":\n'
                '        pass\n'
                '    if "sha256:" + "0" * 64 not in digest_candidates:\n',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "inspected digest identity"
            )

        with self.subTest(surface="runtime platform"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                'or runtime_identity[3] != "x86_64"',
                'or runtime_identity[3] != "aarch64"',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "runtime Linux/x86_64 platform"
            )

        with self.subTest(surface="permissive runtime platform operator"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                'or runtime_identity[3] != "x86_64"',
                'or runtime_identity[3] not in ("x86_64", "aarch64")',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "runtime Linux/x86_64 platform"
            )

        with self.subTest(surface="runtime command platform"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                '        "--platform",\n        CADDY_PLATFORM,',
                '        "--platform",\n        "linux/arm64",',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "run command"
            )

        with self.subTest(surface="duplicate runtime platform"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                '        CADDY_PLATFORM,\n        "--network",',
                '        CADDY_PLATFORM,\n        "--platform=linux/arm64",\n        "--network",',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "run command"
            )

        with self.subTest(surface="runtime reference ordering"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                '        CADDY_PLATFORM,\n        "--network",',
                '        CADDY_PLATFORM,\n        CADDY_REFERENCE,\n        "--network",',
            )
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                "        CADDY_REFERENCE,\n        *command,",
                "        *command,",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "run command"
            )

        with self.subTest(surface="main identity orchestration"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                "    _inspect_digest(docker)\n    _runtime_identity(docker)",
                "    pass",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "identity gates from main"
            )

        with self.subTest(surface="runtime environment version"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                "or runtime_identity[0] != CADDY_OCI_VERSION",
                'or runtime_identity[0] != "v2.11.3"',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "runtime binary identity"
            )

        with self.subTest(surface="permissive runtime environment version"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                "or runtime_identity[0] != CADDY_OCI_VERSION",
                "or runtime_identity[0] not in (CADDY_OCI_VERSION,)",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "runtime binary identity"
            )

        with self.subTest(surface="runtime binary version"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                "or runtime_identity[1].split()[0] != CADDY_OCI_VERSION",
                'or runtime_identity[1].split()[0] != "v2.11.3"',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "runtime binary identity"
            )

        with self.subTest(surface="permissive runtime binary version"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                "or runtime_identity[1].split()[0] != CADDY_OCI_VERSION",
                "or runtime_identity[1].split()[0] not in (CADDY_OCI_VERSION,)",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "runtime binary identity"
            )

        with self.subTest(surface="emitted platform evidence"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "tests/deployment/g8_caddy_gate.py",
                '"platform": CADDY_PLATFORM',
                '"platform": "linux/arm64"',
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "literal-image-caddy", "emitted evidence"
            )

    def test_compose_and_docker_provenance_mutations_are_detected(self) -> None:
        with self.subTest(surface="PostgreSQL gosu removal"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "docker/postgres.Dockerfile",
                "rm -f /usr/local/bin/gosu",
                "test ! -e /usr/local/bin/gosu",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "compose-postgres", "does not remove gosu exactly once"
            )

        with self.subTest(surface="PostgreSQL VPS build reset"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            replace_once(
                root,
                "deploy/vps/compose.yaml",
                "services:\n  postgres:\n    <<: *vps-service\n    build: !reset null",
                "services:\n  postgres:\n    <<: *vps-service\n    build:\n      context: ../..",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "compose-postgres", "does not disable local image builds"
            )

        with self.subTest(surface="recovery Compose"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            relative = "tests/deployment/g8_recovery_compose.yaml"
            reference = audit_tool.compose_service_image(
                (root / relative).read_text(encoding="utf-8"), "postgres"
            )
            changed = reference.replace("HBCB_G8_POSTGRES_IMAGE", "HBCB_G8_OTHER_IMAGE")
            replace_once(
                root,
                relative,
                reference,
                changed,
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "compose-postgres", "local image expression is stale"
            )

        with self.subTest(surface="orphan Compose"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            relative = "tests/service_integration/g8_orphan_minio_compose.yaml"
            reference = audit_tool.compose_service_image(
                (root / relative).read_text(encoding="utf-8"), "postgres"
            )
            changed = reference.replace(
                "HBCB_ORPHAN_POSTGRES_IMAGE_ID", "HBCB_ORPHAN_OTHER_IMAGE_ID"
            )
            replace_once(
                root,
                relative,
                reference,
                changed,
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "compose-postgres", "local image expression is stale"
            )

        with self.subTest(surface="PostgreSQL runtime gate"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            policy = json.loads(
                (root / "release/dependency-policy.json").read_text(encoding="utf-8")
            )
            reference = next(
                item["base_reference"]
                for item in policy["compose_images"]
                if item["id"] == "postgres"
            )
            replace_once(
                root,
                "tests/security/postgres_fixture_gate.py",
                reference[-64:],
                "d" * 64,
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "compose-postgres", "lacks the exact base image assertion"
            )

        with self.subTest(surface="Compose policy inventory"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            policy_path = root / "release" / "dependency-policy.json"
            document = json.loads(policy_path.read_text(encoding="utf-8"))
            postgres = next(
                item for item in document["compose_images"] if item["id"] == "postgres"
            )
            postgres["assertion_files"].remove(
                "tests/security/postgres_fixture_gate.py"
            )
            policy_path.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(
                report, "compose-postgres", "expected inventory"
            )

        with self.subTest(surface="builder OCI provenance"), tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            report = audit_tool.run_audit(root, online=False)
            images = report.get("images")
            self.assertIsInstance(images, list)
            base = next(
                item
                for item in images
                if isinstance(item, dict) and item.get("id") == "docker-base"
            )
            digest = str(base["digest"])
            replace_once(
                root,
                "docker/builder.Dockerfile",
                'org.opencontainers.image.base.digest="sha256:%s"' % digest,
                'org.opencontainers.image.base.digest="sha256:%s"' % ("e" * 64),
            )
            report = audit_tool.run_audit(root, online=False)
            self.assert_check_failure(report, "docker-base", "OCI base digest is stale")

    def test_local_build_missing_or_non_string_target_fails_closed(self) -> None:
        for surface, mutate in (
            ("missing target", lambda postgres: postgres.pop("target")),
            ("non-string target", lambda postgres: postgres.__setitem__("target", 7)),
        ):
            with self.subTest(surface=surface), tempfile.TemporaryDirectory() as temporary:
                root = fixture_root(Path(temporary))
                policy_path = root / "release" / "dependency-policy.json"
                document = json.loads(policy_path.read_text(encoding="utf-8"))
                postgres = next(
                    item
                    for item in document["compose_images"]
                    if item["id"] == "postgres"
                )
                mutate(postgres)
                policy_path.write_text(
                    json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                report = audit_tool.run_audit(root, online=False)
                self.assert_check_failure(
                    report,
                    "compose-postgres",
                    "Local-build Compose image recipe is incomplete",
                )


if __name__ == "__main__":
    unittest.main()
