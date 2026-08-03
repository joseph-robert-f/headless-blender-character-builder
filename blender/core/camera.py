"""Deterministic cameras and native lights fitted from generated bounds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import bpy
from mathutils import Vector

from .primitives import MM_PER_METER, mesh_bounds_mm


RENDER_SIZE = 512
RENDER_SAMPLES = 32


@dataclass(frozen=True)
class RenderScene:
    camera_names: tuple[str, ...]
    light_names: tuple[str, ...]
    resolution: int
    samples: int


def _aim(camera: bpy.types.Object, target: Vector) -> None:
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _camera(
    *,
    name: str,
    collection: bpy.types.Collection,
    location: Vector,
    target: Vector,
    orthographic_scale: float,
) -> bpy.types.Object:
    data = bpy.data.cameras.new(f"DATA_{name}")
    data.type = "ORTHO"
    data.ortho_scale = orthographic_scale
    data.lens = 50.0
    data.clip_start = 0.0001
    data.clip_end = max(10.0, location.length * 20.0)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = location
    _aim(obj, target)
    obj["builder_role"] = "camera"
    return obj


def _area_light(
    *,
    name: str,
    collection: bpy.types.Collection,
    location: Vector,
    target: Vector,
    energy: float,
    size: float,
) -> bpy.types.Object:
    data = bpy.data.lights.new(f"DATA_{name}", type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    # Overlapping display solids are intentional because the same reviewed
    # components feed the voxel union.  Eevee shadow maps can stipple at those
    # intersections, so diagnostic lighting stays shadow-free; topology and
    # printable-shell evidence are verified independently.
    data.use_shadow = False
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = location
    _aim(obj, target)
    obj["builder_role"] = "light"
    return obj


def setup_render_scene(display_objects: Iterable[bpy.types.Object]) -> RenderScene:
    """Create four fitted cameras and three native procedural lights."""

    objects = tuple(display_objects)
    bpy.context.view_layer.update()
    minimum_mm, maximum_mm = mesh_bounds_mm(objects)
    minimum = minimum_mm / MM_PER_METER
    maximum = maximum_mm / MM_PER_METER
    center = (minimum + maximum) * 0.5
    dimensions = maximum - minimum
    largest = max(dimensions)
    distance = max(0.25, largest * 3.0)
    margin = 1.20
    front_scale = max(dimensions.z, dimensions.x) * margin
    side_scale = max(dimensions.z, dimensions.y) * margin
    preview_scale = max(dimensions.z, dimensions.x, dimensions.y) * 1.38

    cameras_collection = bpy.data.collections["CAMERAS"]
    lights_collection = bpy.data.collections["LIGHTS"]
    camera_specs = (
        (
            "Camera_Preview",
            center + Vector((distance * 0.72, -distance, distance * 0.46)),
            preview_scale,
        ),
        ("Camera_Front", center + Vector((0.0, -distance, 0.0)), front_scale),
        ("Camera_Side", center + Vector((distance, 0.0, 0.0)), side_scale),
        ("Camera_Back", center + Vector((0.0, distance, 0.0)), front_scale),
    )
    cameras = tuple(
        _camera(
            name=name,
            collection=cameras_collection,
            location=location,
            target=center,
            orthographic_scale=scale,
        )
        for name, location, scale in camera_specs
    )
    light_specs = (
        ("Light_Key", center + Vector((-distance, -distance, distance)), 12.0),
        ("Light_Fill", center + Vector((distance, -distance * 0.55, distance * 0.40)), 5.5),
        ("Light_Rim", center + Vector((0.0, distance, distance * 0.80)), 8.5),
    )
    lights = tuple(
        _area_light(
            name=name,
            collection=lights_collection,
            location=location,
            target=center,
            energy=energy,
            size=max(0.08, largest * 1.6),
        )
        for name, location, energy in light_specs
    )

    scene = bpy.context.scene
    scene.camera = cameras[0]
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = RENDER_SIZE
    scene.render.resolution_y = RENDER_SIZE
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    scene.render.filepath = "//preview.png"
    scene.render.use_file_extension = True
    scene.render.use_freestyle = False
    if hasattr(scene, "eevee"):
        for attribute in ("taa_render_samples", "taa_samples"):
            if hasattr(scene.eevee, attribute):
                setattr(scene.eevee, attribute, RENDER_SAMPLES)
    scene.view_settings.look = "AgX - Medium High Contrast"

    if scene.world is None:
        scene.world = bpy.data.worlds.new("BuilderWorld")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.055, 0.065, 0.085, 1.0)
        background.inputs["Strength"].default_value = 0.07
    return RenderScene(
        camera_names=tuple(camera.name for camera in cameras),
        light_names=tuple(light.name for light in lights),
        resolution=RENDER_SIZE,
        samples=RENDER_SAMPLES,
    )


__all__ = ["RENDER_SAMPLES", "RENDER_SIZE", "RenderScene", "setup_render_scene"]
