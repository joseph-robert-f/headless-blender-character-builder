"""Integration tests that require a real Blender.

Importing bpy here, before any test module loads, is what makes `bmesh` and
`mathutils` importable under the `bpy` PyPI module -- they only appear once bpy
has initialised. Inside the Blender executable this is a no-op.
"""

import bpy  # noqa: F401
