"""Offline decimal packaging checks. Native smoke tests run on each target."""
from collections import OrderedDict
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CPYTHON_HASH = "f4b1bfb3c79b5bb11b8d228a12504163b4c0dab4d679828d8f5f26b6cb6ab35d"
ARCHIVES = {
    "CPython-decimal-libmpdec-NOTICES.txt": (
        "Python-3.13.16.tar.xz", CPYTHON_HASH),
    "CPython-libmpdec-4.0.0-NOTICES.txt": (
        "cpython-source-deps-mpdecimal-4.0.0.tar.gz",
        "338fac3fb8cdd60f406b6326431338756f58a8af94229ffd9bf1e7c2b1ad71ca"),
    "CPython-libmpdec-4.0.1-NOTICES.txt": (
        "mpdecimal-4.0.1.tar.gz",
        "96d33abb4bb0070c7be0fed4246cd38416188325f820468214471938545b1ac8"),
}


def build_module():
    loader = importlib.machinery.SourceFileLoader("decimal_preview_build_test", str(ROOT / "scripts/build-review-preview"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class DecimalPackagingTests(unittest.TestCase):
    def setUp(self):
        self.build = build_module()

    def import_preview(self, excludes):
        # Use a new process so imports from this test cannot conceal an exclusion.
        code = """
import sys, json
sys.path.insert(0, sys.argv[1])
excludes = json.loads(sys.argv[2])
class ExcludedModules:
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == item or fullname.startswith(item + '.') for item in excludes):
            raise ModuleNotFoundError('Excluded module: ' + fullname)
sys.meta_path.insert(0, ExcludedModules())
import packaging.review_preview_entry
from experimental_modeling.translation_v2 import Fraction
from decimal import Decimal
assert Fraction(Decimal('0.25')) == Fraction(1, 4)
assert {'fractions', 'decimal', '_decimal'} <= sys.modules.keys()
"""
        return subprocess.run([sys.executable, "-S", "-c", code, str(ROOT), json.dumps(excludes)],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)

    def test_exclusions_retain_required_decimal_import_closure(self):
        for name in ("fractions", "decimal", "_decimal"):
            self.assertNotIn(name, self.build.EXCLUDES)
        # Keep the previous exclusions except the two required decimal modules.
        self.assertEqual(set(self.build.EXCLUDES), {
            "experimental_modeling.sandbox", "experimental_modeling.inspect_scene", "bpy",
            "tkinter", "_tkinter", "idlelib", "test", "unittest", "ensurepip", "pip",
            "setuptools", "sqlite3", "_sqlite3", "curses", "_curses", "readline",
            "ssl", "_ssl", "_hashlib", "_bz2", "_lzma", "ctypes", "_ctypes"})
        result = self.import_preview(self.build.EXCLUDES)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_old_decimal_exclusions_reproduce_startup_failure(self):
        result = self.import_preview(self.build.EXCLUDES + ["decimal", "_decimal"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Excluded module: decimal", result.stderr)

    def inventory(self, names, target):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        bundle, work = base / "bundle", base / "work"
        bundle.mkdir()
        (work / self.build.NAME).mkdir(parents=True)
        for name in names:
            (bundle / name).write_bytes(b"synthetic native component")
        (work / self.build.NAME / "Analysis-00.toc").write_text(repr([
            [(name, "synthetic-input/" + name, "EXTENSION") for name in names]]))
        return self.build.native_inventory(bundle, work, target)

    def test_each_target_decimal_component_has_exact_notices(self):
        for target, filename, version in (
            ("windows-x64", "_decimal.pyd", "4.0.0"),
            ("macos-arm64", "_decimal.cpython-313-darwin.so", "4.0.1"),
        ):
            with self.subTest(target=target):
                rows, excluded = self.inventory([filename], target)
                self.assertEqual(excluded, [])
                self.assertEqual(rows[0]["component"], f"CPython _decimal with static libmpdec {version}")
                self.assertEqual(rows[0]["analysis_source"], "synthetic-input/" + filename)
                self.assertEqual(rows[0]["license_files"], self.build.decimal_notices(target))
                self.assertIn("licenses/CPython-decimal-libmpdec-NOTICES.txt", rows[0]["license_files"])
                self.assertIn(f"licenses/CPython-libmpdec-{version}-NOTICES.txt", rows[0]["license_files"])

    def test_unreviewed_separate_libmpdec_stops_target_build(self):
        for target, filename in (("windows-x64", "libmpdec-4.dll"),
                                 ("macos-arm64", "libmpdec.4.dylib")):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "Unmapped native"):
                self.inventory([filename], target)

    def test_linux_components_do_not_claim_target_provenance(self):
        rows, excluded = self.inventory(["_decimal.cpython-312-x86_64-linux-gnu.so", "libmpdec.so.3"],
                                        "linux-validation")
        self.assertEqual(excluded, [])
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("not a distributed target", row["component"])
            self.assertEqual(row["license_files"], [])

    def test_static_component_checks_target_version(self):
        import _decimal
        for target, version in self.build.LIBMPDEC_VERSIONS.items():
            with self.subTest(target=target), patch.object(_decimal, "__libmpdec_version__", version):
                row = self.build.decimal_component(target)
                self.assertTrue(row["applicable"])
                self.assertEqual(row["version"], version)
                self.assertEqual(row["notice_catalog_entry"], f"CPython-libmpdec-{version}-NOTICES.txt")
                self.assertEqual(row["license_files"], self.build.decimal_notices(target))
            with self.subTest(target=target), patch.object(_decimal, "__libmpdec_version__", "0.0.0"):
                with self.assertRaisesRegex(ValueError, "Unreviewed libmpdec version"):
                    self.build.decimal_component(target)

    def test_linux_static_marker_is_not_target_evidence(self):
        row = self.build.decimal_component("linux-validation")
        self.assertFalse(row["applicable"])
        self.assertIn("not asserted", row["incorporation"])
        self.assertIsNone(row["notice_catalog_entry"])
        self.assertEqual(row["license_files"], [])

    def test_linux_builtin_binds_to_actual_libpython_inventory(self):
        import _decimal
        native = [{"file": "_internal/libpython3.12.so.1.0", "sha256": "a" * 64,
                   "component": "CPython", "bundled": True}]
        with patch.object(self.build.sys, "builtin_module_names", ("_decimal",)), patch.object(
                self.build.importlib.util, "find_spec", return_value=SimpleNamespace(origin="built-in")), patch.object(
                _decimal, "__file__", None, create=True):
            row = self.build.bind_decimal_component(self.build.decimal_component("linux-validation"),
                                                    native, "linux-validation")
        self.assertEqual(row["native_file"], native[0]["file"])
        self.assertEqual(row["native_sha256"], native[0]["sha256"])
        self.assertIn("built-in", row["runtime_module_origin"])
        self.assertIn("source identity unverified", row["runtime_module_origin"])
        self.assertFalse(row["applicable"])

    def test_linux_builtin_requires_all_runtime_checks_and_bundled_libpython(self):
        import _decimal
        libpython = {"file": "_internal/libpython3.12.so.1.0", "sha256": "a" * 64,
                     "component": "CPython", "bundled": True}
        cases = [
            (("_decimal",), "built-in", None, []),
            ((), "built-in", None, [libpython]),
            (("_decimal",), "extension", None, [libpython]),
            (("_decimal",), "built-in", "unbundled/_decimal.so", [libpython]),
            (("_decimal",), "built-in", None, [{**libpython, "bundled": False}]),
        ]
        for builtins, origin, filename, native in cases:
            with self.subTest(case=(builtins, origin, filename, native)), patch.object(
                    self.build.sys, "builtin_module_names", builtins), patch.object(
                    self.build.importlib.util, "find_spec", return_value=SimpleNamespace(origin=origin)), patch.object(
                    _decimal, "__file__", filename, create=True):
                with self.assertRaisesRegex(ValueError, "must include the _decimal native module"):
                    self.build.bind_decimal_component({}, native, "linux-validation")

    def test_distributed_targets_still_require_decimal_extension(self):
        native = [{"file": "_internal/libpython3.13.so.1.0", "sha256": "a" * 64,
                   "component": "CPython", "bundled": True}]
        for target in self.build.LIBMPDEC_VERSIONS:
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "must include the _decimal"):
                self.build.bind_decimal_component({}, native, target)
        for target, filename in (("windows-x64", "_internal/_decimal.pyd"),
                                 ("macos-arm64", "_internal/_decimal.cpython-313-darwin.so")):
            with self.subTest(target=target):
                module = {"file": filename, "sha256": "b" * 64}
                row = self.build.bind_decimal_component({}, [module], target)
                self.assertEqual(row["native_file"], filename)
                self.assertEqual(row["native_sha256"], "b" * 64)
                self.assertEqual(row["runtime_module_origin"], "extension")


class DecimalNoticeTests(unittest.TestCase):
    def setUp(self):
        catalog = json.loads((ROOT / "packaging/runtime-notices.json").read_text())
        self.rows = {row["file"]: row for row in catalog["notices"] if row["file"] in ARCHIVES}

    def test_notice_hashes_and_complete_permissions(self):
        self.assertEqual(self.rows.keys(), ARCHIVES.keys())
        for filename, row in self.rows.items():
            with self.subTest(filename=filename):
                data = (ROOT / "packaging/notices" / filename).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
                text = data.decode()
                for required in ("Stefan Krah", "Redistributions in binary form must reproduce",
                                 "SUCH DAMAGE.", "Henry S. Warren", "You are free to use, copy, and distribute"):
                    self.assertIn(required, text)
                self.assertIn("vcdiv64.asm", text)
                if filename == "CPython-decimal-libmpdec-NOTICES.txt":
                    self.assertIn("2008-2012 Stefan Krah", text)
                    self.assertIn("2001-2012 Python Software Foundation", text)

    def test_catalog_binds_target_source_archives_and_files(self):
        for filename, row in self.rows.items():
            with self.subTest(filename=filename):
                self.assertEqual(row["source_archive_sha256"], ARCHIVES[filename][1])
                self.assertTrue(row["source_archive_url"].startswith("https://"))
                self.assertIn("end of file", row["extraction"])
                sources = {item["file"]: item["sha256"] for item in row["sources"]}
                self.assertEqual(len(sources), len(row["sources"]))
                self.assertTrue(all(re.fullmatch("[0-9a-f]{64}", value) for value in sources.values()))
                prefix = "Modules/_decimal/" if filename == "CPython-decimal-libmpdec-NOTICES.txt" else ""
                self.assertIn(prefix + "libmpdec/typearith.h", sources)
                self.assertIn(prefix + "libmpdec/vcdiv64.asm", sources)
                if prefix:
                    self.assertIn("Modules/_decimal/_decimal.c", sources)
                else:
                    self.assertIn("COPYRIGHT.txt", sources)
                    self.assertEqual(row["selection_source"]["source_archive_sha256"], CPYTHON_HASH)
                    self.assertRegex(row["selection_source"]["sha256"], "^[0-9a-f]{64}$")
        self.assertEqual(self.rows["CPython-libmpdec-4.0.0-NOTICES.txt"]["target"], "windows-x64")
        self.assertEqual(self.rows["CPython-libmpdec-4.0.1-NOTICES.txt"]["target"], "macos-arm64")

    def test_cached_upstream_archives_reproduce_notice_text(self):
        """Optional source audit: set DECIMAL_NOTICE_ARCHIVES to a cache directory."""
        cache = os.environ.get("DECIMAL_NOTICE_ARCHIVES")
        if not cache:
            self.skipTest("Set DECIMAL_NOTICE_ARCHIVES for an offline upstream source audit")
        for filename, row in self.rows.items():
            archive = Path(cache) / ARCHIVES[filename][0]
            with self.subTest(filename=filename):
                self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), row["source_archive_sha256"])
                groups = OrderedDict()
                with tarfile.open(archive) as source:
                    prefix = source.getmembers()[0].name.split("/")[0] + "/"
                    for item in row["sources"]:
                        data = source.extractfile(prefix + item["file"]).read()
                        self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
                        text = data.decode()
                        if item["file"] == "COPYRIGHT.txt":
                            comments = [text.rstrip("\n")]
                        elif item["file"].endswith(".asm"):
                            comments = [re.match(r"(?:;[^\n]*\n)+", text).group(0).rstrip("\n")]
                        else:
                            comments = [comment for comment in re.findall(r"/\*.*?\*/", text, re.S)
                                        if re.search("copyright|license|permission|redistribut", comment, re.I)]
                        for comment in comments:
                            names = groups.setdefault(comment, [])
                            if item["file"] not in names:
                                names.append(item["file"])
                expected = row["component"] + "\nComments and copyright files below retain the upstream text.\n\n"
                for comment, names in groups.items():
                    expected += "Sources:\n" + "\n".join(names) + "\n\n" + comment + "\n\n"
                self.assertEqual((ROOT / "packaging/notices" / filename).read_text(), expected)
                if "selection_source" in row:
                    selected = row["selection_source"]
                    with tarfile.open(Path(cache) / "Python-3.13.16.tar.xz") as source:
                        data = source.extractfile("Python-3.13.16/" + selected["file"]).read()
                    self.assertEqual(hashlib.sha256(data).hexdigest(), selected["sha256"])


if __name__ == "__main__":
    unittest.main()
