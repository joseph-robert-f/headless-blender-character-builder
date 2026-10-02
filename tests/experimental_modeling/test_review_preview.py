"""Offline packaging contracts; native executable evidence uses the smoke script."""
import json
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from experimental_modeling.preview_manifest import MANIFEST, inventory, sha256, verify
from experimental_modeling.project import initialize
from experimental_modeling.review_preview import main, serve

ROOT = Path(__file__).resolve().parents[2]


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "program").write_bytes(b"synthetic binary")
        (self.root / MANIFEST).write_text(json.dumps({"schema_version": 1, "files": inventory(self.root)}))

    def test_verifies_bytes_then_rejects_tamper_missing_extra(self):
        self.assertTrue(verify(self.root)["verified"])
        (self.root / "program").write_bytes(b"tampered binary")
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            verify(self.root)
        (self.root / "program").write_bytes(b"synthetic binary")
        (self.root / "extra").write_bytes(b"extra")
        with self.assertRaises(ValueError):
            verify(self.root)
        (self.root / "extra").unlink()
        (self.root / "program").unlink()
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_external_link_rejected(self):
        try:
            (self.root / "redirect").symlink_to(self.root.parent, target_is_directory=True)
        except OSError:
            self.skipTest("Unprivileged symlink creation is unavailable")
        with self.assertRaisesRegex(ValueError, "escapes"):
            inventory(self.root)

    def test_reviewed_notice_hashes(self):
        data = json.loads((ROOT / "packaging/runtime-notices.json").read_text())
        self.assertTrue(data["notices"])
        for row in data["notices"]:
            self.assertEqual(sha256(ROOT / "packaging/notices" / row["file"]), row["sha256"])
            self.assertEqual(urlsplit(row["url"]).scheme, "https")
            self.assertIn(urlsplit(row["url"]).hostname, {"raw.githubusercontent.com", "www.python.org", "www.apache.org"})


class PreviewTests(unittest.TestCase):
    def test_build_tool_notices_keep_vendored_paths_without_overwriting(self):
        loader = importlib.machinery.SourceFileLoader("preview_notices_test", str(ROOT / "scripts/build-review-preview"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        build = importlib.util.module_from_spec(spec)
        loader.exec_module(build)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            bundle = base / "bundle"
            bundle.mkdir()
            files = [Path("example.dist-info/licenses/first/LICENSE"), Path("example.dist-info/licenses/second/LICENSE")]
            for index, member in enumerate(files):
                path = base / member
                path.parent.mkdir(parents=True)
                path.write_text(f"notice {index}", encoding="utf-8")
            class Distribution:
                def locate_file(self, item):
                    return base / item
            distribution = Distribution()
            distribution.files = files
            with patch.object(build, "dependencies", return_value={"example": "1"}), patch.object(
                    build.importlib.metadata, "distribution", return_value=distribution):
                build.collect_notices(bundle)
            copied = bundle / "licenses/build-tools/example"
            self.assertEqual((copied / files[0]).read_text(), "notice 0")
            self.assertEqual((copied / files[1]).read_text(), "notice 1")

    def test_source_mode_never_pretends_to_verify_a_bundle(self):
        self.assertEqual(main(["--verify"]), 2)

    def test_backend_read_only_is_unconditional(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = initialize(Path(temporary).resolve() / "project")
            before = sorted(str(p.relative_to(project.root)) for p in project.root.rglob("*"))
            with patch("experimental_modeling.review_preview.LocalReviewServer") as constructor:
                constructor.return_value.handle_request.side_effect = KeyboardInterrupt
                with self.assertRaises(KeyboardInterrupt):
                    serve(project, 0)
                review = constructor.call_args.args[0]
                self.assertTrue(review.read_only)
                self.assertIn("REVIEW PREVIEW", review.read_only_reason)
                with self.assertRaises(PermissionError):
                    review.accept("r0", {})
                with self.assertRaises(PermissionError):
                    review.request({})
                constructor.return_value.server_close.assert_called_once()
            self.assertEqual(before, sorted(str(p.relative_to(project.root)) for p in project.root.rglob("*")))

    def test_native_inventory_omits_os_api_stubs_but_fails_unknown_components(self):
        loader = importlib.machinery.SourceFileLoader("preview_build_test", str(ROOT / "scripts/build-review-preview"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        build = importlib.util.module_from_spec(spec)
        loader.exec_module(build)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            bundle, work = base / "bundle", base / "work"
            bundle.mkdir()
            (work / build.NAME).mkdir(parents=True)
            names = ["python313.dll", "VCRUNTIME140.dll", "api-ms-win-core-console-l1-1-0.dll",
                     "ext-ms-win-kernel32-package-current-l1-1-0.dll"]
            for name in names:
                (bundle / name).write_bytes(b"synthetic test component")
            (work / build.NAME / "Analysis-00.toc").write_text(repr([
                [(name, "official-python-input/" + name, "BINARY") for name in names]]))
            rows, excluded = build.native_inventory(bundle, work, "windows-x64")
            self.assertEqual([row["file"] for row in rows], ["python313.dll"])
            self.assertEqual({row["name"] for row in excluded}, set(names[1:]))
            self.assertTrue(all(row["bundled"] is False for row in excluded))
            self.assertEqual({path.name for path in bundle.iterdir()}, {"python313.dll"})
            (bundle / "unknown_vendor.dll").write_bytes(b"unreviewed")
            with self.assertRaisesRegex(ValueError, "Unmapped native"):
                build.native_inventory(bundle, work, "windows-x64")
            self.assertTrue((bundle / "unknown_vendor.dll").exists())
            report = json.loads((base / "native-review-needed.json").read_text())
            self.assertEqual(report["unmapped"][0]["name"], "unknown_vendor.dll")


if __name__ == "__main__":
    unittest.main()
