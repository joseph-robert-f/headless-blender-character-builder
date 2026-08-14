from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests" / "deployment" / "g8_static_gate.py"
SPEC = importlib.util.spec_from_file_location("g8_static_gate_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


class G8StaticFixtureTests(unittest.TestCase):
    def test_fixture_supplies_digest_pinned_derived_postgres_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            environment_file = gate._fixture_environment(Path(temporary))
            values = dict(
                line.split("=", 1)
                for line in environment_file.read_text(encoding="utf-8").splitlines()
            )

        self.assertEqual(
            values.get("HBCB_POSTGRES_IMAGE"),
            "ghcr.io/example/headless-blender-character-builder-postgres@sha256:"
            + "5" * 64,
        )


if __name__ == "__main__":
    unittest.main()
