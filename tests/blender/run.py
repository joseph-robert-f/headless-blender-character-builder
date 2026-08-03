"""Launcher that runs the Blender integration tests inside Blender.

    blender --background --factory-startup --python tests/blender/run.py

Blender executes this as a plain script, so the repository root has to be put
on sys.path before anything can be imported, and the exit code has to be set
explicitly from the test result.
"""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def main():
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=os.path.join(_REPO_ROOT, "tests", "blender"),
        top_level_dir=_REPO_ROOT,
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(code)
