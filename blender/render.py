"""Diagnostic and preview rendering.

Renders are evidence, not decoration: three orthographic views make it obvious
at a glance whether limbs are attached, whether the model sits on its base, and
whether proportions came out as asked -- things a QA number does not convey.

Cycles on the CPU is used rather than EEVEE because EEVEE needs a GPU and an
OpenGL context, neither of which exists in a headless container. Sample counts
are deliberately low and denoising is on; these are inspection images, not
marketing shots.
"""

import math

import bpy
from mathutils import Vector

from . import scene

PREVIEW_SAMPLES = 48
DIAGNOSTIC_SAMPLES = 24
RESOLUTION = 1024

# Orthographic views leave this much empty margin around the model.
FRAMING_MARGIN = 1.18


def configure(samples, resolution=RESOLUTION):
    """Set up Cycles for deterministic, CPU-only rendering."""
    render = bpy.context.scene.render
    render.engine = "CYCLES"
    render.resolution_x = resolution
    render.resolution_y = resolution
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGBA"
    render.film_transparent = False

    cycles = bpy.context.scene.cycles
    cycles.device = "CPU"
    cycles.samples = samples
    # A fixed seed keeps the sampling pattern identical between runs.
    cycles.seed = 0
    cycles.use_denoising = True
    cycles.use_adaptive_sampling = True
    # Bounce counts are low on purpose; these are matte objects on a plain
    # background and extra bounces only cost time.
    cycles.max_bounces = 4
    cycles.diffuse_bounces = 2
    cycles.glossy_bounces = 2
    cycles.transmission_bounces = 2
    return render


# Sun strengths are irradiance in W/m2, independent of distance and of how big
# the model is. Point and area lamps would not be: Cycles computes their falloff
# treating one Blender unit as one metre, but this project's unit is the
# millimetre, so a lamp two hundred units away is treated as two hundred metres
# away and the model renders almost black. Suns avoid that entirely and give the
# same exposure for a 25 mm figure and a 250 mm one.
_SUN_RIG = (
    # (name, elevation degrees, azimuth degrees, strength)
    ("key", 42.0, -35.0, 4.2),
    ("fill", 15.0, 65.0, 1.6),
    ("rim", 55.0, 170.0, 2.4),
)


def build_lighting(target_z, model_size):
    """A three-point sun rig. Exposure does not depend on model size."""
    created = []
    for name, elevation, azimuth, strength in _SUN_RIG:
        data = bpy.data.lights.new(name="hbcb-%s" % name, type="SUN")
        data.energy = strength
        # A small angular diameter keeps shadow edges readable in the
        # diagnostic views without looking harsh.
        data.angle = math.radians(6.0)
        obj = bpy.data.objects.new(name="hbcb-%s" % name, object_data=data)
        # Place the sun on a notional sphere and aim it at the model. Only the
        # rotation affects the result; the location just makes the .blend
        # sensible to open and inspect.
        radius = max(model_size, 1.0) * 3.0
        elevation_r = math.radians(elevation)
        azimuth_r = math.radians(azimuth)
        obj.location = (
            radius * math.cos(elevation_r) * math.sin(azimuth_r),
            -radius * math.cos(elevation_r) * math.cos(azimuth_r),
            target_z + radius * math.sin(elevation_r),
        )
        _aim(obj, Vector((0.0, 0.0, target_z)))
        bpy.context.scene.collection.objects.link(obj)
        created.append(obj)
    return created


def _aim(obj, target):
    """Point an object's -Z axis at `target`, the convention cameras use."""
    direction = target - obj.location
    if direction.length == 0.0:
        return obj
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return obj


def _camera(name):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _render_to(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def render_views(model, output_dir, preview_path, diagnostic_paths):
    """Render one preview plus the orthographic diagnostic set.

    Returns the list of paths written.
    """
    low, high = scene.world_bounds(model)
    size = max(high[i] - low[i] for i in range(3))
    centre = Vector(((low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0, (low[2] + high[2]) / 2.0))

    scene.set_world_background()
    build_lighting(centre.z, size)

    camera = _camera("hbcb-camera")
    bpy.context.scene.camera = camera

    written = []

    # Orthographic technical views: no perspective distortion, so what is
    # measured in QA is what is seen.
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = size * FRAMING_MARGIN
    configure(DIAGNOSTIC_SAMPLES)

    distance = size * 4.0
    views = {
        "front": Vector((0.0, -distance, centre.z)),
        "side": Vector((distance, 0.0, centre.z)),
        "back": Vector((0.0, distance, centre.z)),
    }
    for view_name, location in views.items():
        path = diagnostic_paths[view_name]
        camera.location = location
        _aim(camera, centre)
        written.append(_render_to(path))

    # Perspective three-quarter preview.
    camera.data.type = "PERSP"
    camera.data.lens = 70.0
    camera.location = Vector((-size * 1.5, -size * 2.0, centre.z + size * 0.55))
    _aim(camera, centre)
    configure(PREVIEW_SAMPLES)
    written.append(_render_to(preview_path))

    return written
