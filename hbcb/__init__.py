"""Headless Blender Character Builder -- shared, dependency-free core.

Everything in this package is importable both from ordinary CPython and from
inside Blender's bundled Python, so the host CLI and the in-Blender runner
share one implementation of validation, hashing, and the manifest format.

Stdlib only. Do not add a third-party import to this package.
"""

__version__ = "0.1.0"

GENERATOR_VERSION = "1.0.0"
GENERATOR_ID = "geometric-character@1.0.0"

# Blender versions the runner is tested against. Older releases are rejected
# because the 4.2+ exporter operators (`wm.stl_export`) do not exist in them.
MINIMUM_BLENDER = (4, 2, 0)
