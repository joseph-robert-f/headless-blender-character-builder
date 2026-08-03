"""Blender-side implementation.

Modules in this package import `bpy` and only run inside Blender (either the
`blender` executable or the `bpy` PyPI module). Anything that must also run on
the host lives in the `hbcb` package instead.

The whole package works in a millimetre coordinate space: one Blender unit is
one millimetre, Z is up, and a finished model rests on the Z=0 plane. That
matches how slicers read STL files and removes a class of scale mistakes.
"""

# Importing bpy here, before any submodule loads, is load-bearing under the
# `bpy` PyPI module: sibling modules such as `bmesh` and `mathutils` only become
# importable once bpy has initialised. Inside the Blender executable they are
# always present, so this is a no-op there.
import bpy  # noqa: F401

MM = 1.0
