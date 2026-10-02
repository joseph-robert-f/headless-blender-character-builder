# `facet-bot` Example Brief

`facet-bot` is an original geometric desk-toy robot.
It demonstrates the character generator with fixed input limits.
It uses no franchise, likeness, uploaded asset, font, texture, or network resource.

The default version has these features:

- A rounded-cube head with two inset circular eyes
- A compact capsule-like torso
- Short cylindrical arms and legs with spherical joints
- A circular pedestal in the derived manufacturing-oriented shell
- A warm orange and cream palette for presentation renders
- A neutral standing pose and friendly proportions
- No text, logo, trademark, or external reference.

Front, side, and back views show the form.
The generator uses only native Blender mesh primitives.
The nominal target height is 95 mm.

## Recorded fixture measurements

The recorded G3 result has one connected, watertight STL shell with consistent orientation and positive volume.
It has 316,172 triangles.
Independent output measurement gives a height of 94.9845 mm.
Conservative lower bounds are 2.3001 mm for walls and 2.3089 mm for freestanding features.
These results permit a success manifest for that fixture.

The `moss-hopper` fixture uses the same generator.
It changes style, proportions, palette, pose, components, topology counts, bounds, and structural fingerprint.
Its G2 generation test passes.
Its conservative G3 wall evidence is not conclusive.
The runner returns `needs_review` and publishes no success artifacts.
This result demonstrates QA rejection of unknown evidence, not a print guarantee.
