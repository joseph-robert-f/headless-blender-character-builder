from __future__ import annotations

import hashlib
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.release.support import ROOT, load_script


lock_tool = load_script(
    "dependency_lock_from_wheels_under_test", "dependency-lock-from-wheels"
)


def make_wheel(directory: Path, filename: str, name: str, version: str) -> Path:
    path = directory / filename
    dist_info = filename.split("-", 2)[0] + "-" + version + ".dist-info"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            dist_info + "/METADATA",
            "Metadata-Version: 2.1\nName: %s\nVersion: %s\n\n" % (name, version),
        )
        archive.writestr(name.replace("-", "_") + "/__init__.py", b"")
    return path


class DependencyLockTests(unittest.TestCase):
    def test_candidate_is_sorted_hashed_and_refuses_overwrite(self) -> None:
        script = ROOT / "scripts" / "dependency-lock-from-wheels"
        mode = stat.S_IMODE(script.stat().st_mode)
        self.assertTrue(mode & stat.S_IXUSR)
        self.assertFalse(mode & 0o022)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheels = root / "wheels"
            wheels.mkdir()
            zeta = make_wheel(wheels, "zeta-2.0-py3-none-any.whl", "zeta", "2.0")
            alpha = make_wheel(
                wheels,
                "alpha_pkg-1.2.3-py3-none-any.whl",
                "Alpha-Pkg",
                "1.2.3",
            )
            rendered = lock_tool.render(wheels)
            self.assertLess(rendered.index("alpha-pkg==1.2.3"), rendered.index("zeta==2.0"))
            self.assertIn(hashlib.sha256(alpha.read_bytes()).hexdigest(), rendered)
            self.assertIn(hashlib.sha256(zeta.read_bytes()).hexdigest(), rendered)

            output = root / "candidate.lock"
            self.assertEqual(
                lock_tool.main(["--wheels", str(wheels), "--output", str(output)]),
                0,
            )
            self.assertEqual(output.read_text(encoding="utf-8"), rendered)
            self.assertEqual(
                lock_tool.main(["--wheels", str(wheels), "--output", str(output)]),
                2,
            )

    def test_invalid_or_duplicate_wheels_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheels = Path(temporary)
            make_wheel(wheels, "demo-1.0-py3-none-any.whl", "demo", "1.0")
            make_wheel(wheels, "demo-1.0-py2-none-any.whl", "demo", "1.0")
            with self.assertRaisesRegex(lock_tool.LockError, "duplicate"):
                lock_tool.render(wheels)

        with tempfile.TemporaryDirectory() as temporary:
            wheels = Path(temporary)
            (wheels / "not-a-wheel.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(lock_tool.LockError, "non-wheel"):
                lock_tool.render(wheels)


if __name__ == "__main__":
    unittest.main()
