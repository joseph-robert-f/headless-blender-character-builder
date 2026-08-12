from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from tests.release.support import ROOT, load_script


RECIPE = load_script("minio_recipe_id_under_test", "minio-recipe-id")


class MinioRecipeIdentityTests(unittest.TestCase):
    def _fixture(self, parent: Path) -> Path:
        root = parent / "repository"
        for relative in RECIPE.RECIPE_FILES:
            source = ROOT / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            destination.chmod(0o644)
        return root

    def test_checked_in_recipe_is_canonical_and_every_input_changes_it(self) -> None:
        current = RECIPE.recipe_id(ROOT)
        self.assertRegex(current, r"^sha256:[0-9a-f]{64}$")
        with tempfile.TemporaryDirectory(prefix="hbcb-minio-recipe-") as temporary:
            root = self._fixture(Path(temporary))
            baseline = RECIPE.recipe_id(root)
            self.assertEqual(baseline, current)
            for relative in RECIPE.RECIPE_FILES:
                with self.subTest(relative=relative):
                    path = root / relative
                    original = path.read_bytes()
                    path.write_bytes(original + b"\n# recipe mutation\n")
                    self.assertNotEqual(RECIPE.recipe_id(root), baseline)
                    path.write_bytes(original)

    def test_missing_symlinked_and_changed_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-minio-recipe-") as temporary:
            parent = Path(temporary)
            root = self._fixture(parent)
            target = root / RECIPE.RECIPE_FILES[0]
            original = target.read_bytes()
            target.unlink()
            with self.assertRaises(RECIPE.RecipeFailure):
                RECIPE.recipe_id(root)
            outside = parent / "outside"
            outside.write_bytes(original)
            target.symlink_to(outside)
            with self.assertRaises(RECIPE.RecipeFailure):
                RECIPE.recipe_id(root)

    def test_script_is_executable_and_not_group_or_world_writable(self) -> None:
        mode = stat.S_IMODE((ROOT / "scripts" / "minio-recipe-id").stat().st_mode)
        self.assertTrue(mode & stat.S_IXUSR)
        self.assertFalse(mode & 0o022)


if __name__ == "__main__":
    unittest.main()
