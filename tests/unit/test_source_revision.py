"""Tests for deterministic native/container source provenance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.source_revision import source_revision


class SourceRevisionTests(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        for directory in ("blender", "shared", "builder_cli", "scripts"):
            (root / directory).mkdir()
        (root / "blender" / "a.py").write_text("A = 1\n", encoding="utf-8")
        (root / "shared" / "b.py").write_text("B = 2\n", encoding="utf-8")
        (root / "builder_cli" / "c.py").write_text("C = 3\n", encoding="utf-8")
        (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (root / "scripts" / "builder").write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def test_container_revision_covers_launcher_but_native_does_not(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-source-revision-") as raw:
            root = Path(raw)
            self._tree(root)
            native_before = source_revision(root, include_launcher=False)
            container_before = source_revision(root, include_launcher=True)
            (root / "builder_cli" / "c.py").write_text("C = 4\n", encoding="utf-8")
            self.assertEqual(native_before, source_revision(root, include_launcher=False))
            self.assertNotEqual(container_before, source_revision(root, include_launcher=True))

    def test_revision_is_order_independent_and_content_sensitive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-source-revision-") as raw:
            root = Path(raw)
            self._tree(root)
            first = source_revision(root, include_launcher=True)
            self.assertEqual(first, source_revision(root, include_launcher=True))
            self.assertEqual(len(first), 64)
            (root / "blender" / "z.py").write_text("Z = 9\n", encoding="utf-8")
            self.assertNotEqual(first, source_revision(root, include_launcher=True))

    def test_container_revision_requires_fixed_packaging_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-source-revision-") as raw:
            root = Path(raw)
            self._tree(root)
            (root / "scripts" / "builder").unlink()
            with self.assertRaises(OSError):
                source_revision(root, include_launcher=True)


if __name__ == "__main__":
    unittest.main()
