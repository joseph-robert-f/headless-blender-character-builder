from __future__ import annotations

import contextlib
import io
import json
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from tests.release.support import export_index, git, load_script, make_audit_repository, write
from tests.release.support import ROOT


audit_tool = load_script("release_audit_under_test", "release-audit")


class ReleaseAuditTests(unittest.TestCase):
    def _fixture(self, temporary: str) -> tuple[Path, Path]:
        repository = make_audit_repository(Path(temporary))
        export = Path(temporary) / "export"
        export_index(repository, export)
        return repository, export

    def test_clean_index_export_passes_with_deterministic_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, export = self._fixture(temporary)
            first = audit_tool.audit(repository, export)
            second = audit_tool.audit(repository, export)
        self.assertEqual(first, second)
        self.assertEqual(first["format"], "hbcb-release-audit/v1")
        self.assertEqual(first["source_license"], "GPL-3.0-or-later")
        self.assertEqual(first["asset_license"], "CC0-1.0")
        self.assertEqual(first["file_count"], len(first["files"]))
        self.assertRegex(first["source_tree_sha256"], r"^[0-9a-f]{64}$")

    def test_release_tools_are_executable_and_not_publicly_writable(self) -> None:
        for name in (
            "fetch-corresponding-source",
            "release-audit",
            "service-sbom",
            "release-artifacts",
        ):
            mode = stat.S_IMODE((ROOT / "scripts" / name).stat().st_mode)
            self.assertEqual(mode & 0o100, 0o100, name)
            self.assertEqual(mode & 0o022, 0, name)

    def test_index_rejects_environment_files_personal_paths_and_symlinks(self) -> None:
        cases = (
            ("environment_file_tracked", ".env", b"TOKEN=not-for-publication\n", False),
            (
                "personal_path_tracked",
                "notes.txt",
                ("/Users/" + "fixture-person/work/project\n").encode("utf-8"),
                False,
            ),
            ("unsafe_index_mode", "linked.txt", b"README.md", True),
        )
        for expected, name, payload, symlink in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                repository = make_audit_repository(Path(temporary))
                target = repository / name
                if symlink:
                    target.symlink_to(payload.decode("ascii"))
                else:
                    write(target, payload)
                git(repository, "add", "--all")
                export = Path(temporary) / "export"
                export_index(repository, export)
                with self.assertRaises(audit_tool.AuditFailure) as raised:
                    audit_tool.audit(repository, export)
                self.assertEqual(raised.exception.code, expected)

    def test_known_secret_and_credential_url_fail_without_echoing_value(self) -> None:
        secret = "sk-" + "A" * 32
        credential = "postgresql://user:" + "HighEntropy987654321" + "@database/hbcb"
        for expected, payload in (
            ("secret_detected", ("token=" + secret + "\n").encode("ascii")),
            ("credential_url_detected", (credential + "\n").encode("ascii")),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                repository = make_audit_repository(Path(temporary))
                write(repository / "credential-fixture.txt", payload)
                git(repository, "add", "--all")
                export = Path(temporary) / "export"
                export_index(repository, export)
                with self.assertRaises(audit_tool.AuditFailure) as raised:
                    audit_tool.audit(repository, export)
                self.assertEqual(raised.exception.code, expected)
                self.assertNotIn(secret, str(raised.exception))
                self.assertNotIn("HighEntropy987654321", str(raised.exception))

    def test_export_must_exactly_match_index_and_use_safe_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, export = self._fixture(temporary)
            (export / "README.md").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(audit_tool.AuditFailure) as changed:
                audit_tool.audit(repository, export)
            self.assertEqual(changed.exception.code, "export_content_mismatch")

            shutil.rmtree(export)
            export_index(repository, export)
            write(export / "extra.txt", b"extra\n")
            with self.assertRaises(audit_tool.AuditFailure) as extra:
                audit_tool.audit(repository, export)
            self.assertEqual(extra.exception.code, "export_file_set_mismatch")

            (export / "extra.txt").unlink()
            (export / "README.md").chmod(0o666)
            with self.assertRaises(audit_tool.AuditFailure) as mode:
                audit_tool.audit(repository, export)
            self.assertEqual(mode.exception.code, "unsafe_export_mode")

    def test_root_license_hash_and_spdx_metadata_are_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = make_audit_repository(Path(temporary))
            write(repository / "LICENSE", b"not the GPL text\n")
            git(repository, "add", "LICENSE")
            export = Path(temporary) / "export"
            export_index(repository, export)
            with self.assertRaises(audit_tool.AuditFailure) as raised:
                audit_tool.audit(repository, export)
            self.assertEqual(raised.exception.code, "root_license_mismatch")

    def test_cli_report_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, export = self._fixture(temporary)
            report = Path(temporary) / "audit.json"
            output = io.StringIO()
            errors = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                first = audit_tool.main(
                    ["--repo", str(repository), "--export", str(export), "--report", str(report)]
                )
            self.assertEqual(first, 0)
            parsed = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(parsed["format"], "hbcb-release-audit/v1")
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                second = audit_tool.main(
                    ["--repo", str(repository), "--export", str(export), "--report", str(report)]
                )
            self.assertEqual(second, 1)
            self.assertIn("FAIL[report_exists]", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
