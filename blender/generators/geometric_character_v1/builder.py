"""Bounded procedural composition for geometric-character v1."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

import bpy

from shared.character_spec import BuildRequest, GENERATOR

from ...core.materials import MaterialSet, create_material_set
from ...core.primitives import (
    cone_between,
    cylinder,
    cylinder_between,
    cylinder_dimensions,
    ellipsoid,
    ico_ellipsoid,
    rounded_box,
)
from ...core.scene import COLLECTION_NAMES, derive_printable_shell, factory_scene
from ..types import GenerationResult


DESIGNED_MINIMUM_FEATURE_MM = 3.0
TOP_COMPONENTS = {
    "antenna-pair",
    "long-horns",
    "pointed-ears",
    "round-ears",
    "short-horns",
}


@dataclass
class _Layout:
    target_h: float
    base_h: float
    base_w: float
    base_d: float
    character_h: float
    penetration: float
    top_reserve: float
    head_top: float
    head_h: float
    head_w: float
    head_d: float
    head_center_z: float
    body_h: float
    body_w: float
    body_d: float
    body_center_z: float
    foot_h: float
    limb_radius: float


@dataclass
class _Composer:
    request: BuildRequest
    character: bpy.types.Collection
    materials: MaterialSet
    layout: _Layout
    objects: list[bpy.types.Object] = field(default_factory=list)

    def add(self, obj: bpy.types.Object) -> bpy.types.Object:
        role = str(obj.get("builder_part", "part"))
        preset = "core"
        if role in self.request.spec.components:
            preset = role
        elif role.startswith("antenna"):
            preset = "antenna-pair"
        elif role.startswith("tail"):
            preset = (
                "swept-tail"
                if "swept-tail" in self.request.spec.components
                else "stub-tail"
            )
        elif role == "eye":
            preset = self.request.spec.eye_preset
        elif role in {"arm", "hand", "leg", "foot"}:
            preset = self.request.spec.pose
        elif role in {"head", "body"}:
            preset = self.request.spec.style
        elif role == "base":
            preset = self.request.spec.base.preset
        obj["component_role"] = role
        obj["component_preset"] = preset
        self.objects.append(obj)
        return obj

    def palette(self, index: int) -> bpy.types.Material:
        return self.materials.palette[index % len(self.materials.palette)]


def _bounded(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _layout(request: BuildRequest, voxel_size_mm: float) -> _Layout:
    spec = request.spec
    if "stub-tail" in spec.components and "swept-tail" in spec.components:
        raise ValueError("stub-tail and swept-tail are mutually exclusive")
    target_h = float(spec.height_mm)
    base_h = float(spec.base.height_mm)
    base_w = float(spec.base.width_mm) if spec.base.preset != "none" else min(64.0, target_h * 0.68)
    base_d = float(spec.base.depth_mm) if spec.base.preset != "none" else min(58.0, target_h * 0.62)
    character_h = target_h - base_h
    if character_h < 18.0:
        raise ValueError(
            "the requested base leaves less than 18 mm for reviewed character geometry"
        )

    penetration = max(1.0, voxel_size_mm * 3.0)
    top_components = TOP_COMPONENTS.intersection(spec.components)
    top_reserve = _bounded(character_h * 0.115, 7.0, 16.0) if top_components else 0.0
    head_top = target_h - top_reserve

    style_head_ratio = {"geometric": 0.30, "low_poly": 0.32, "chibi": 0.36}[spec.style]
    head_h = character_h * style_head_ratio * float(spec.proportions.head_scale)
    head_h = _bounded(head_h, character_h * 0.25, character_h * 0.47)
    footprint_w = max(18.0, base_w - 2.0 * penetration)
    footprint_d = max(16.0, base_d - 2.0 * penetration)
    style_width_ratio = {"geometric": 0.35, "low_poly": 0.37, "chibi": 0.40}[spec.style]
    head_w = min(
        footprint_w * 0.88,
        character_h * style_width_ratio * float(spec.proportions.head_scale),
    )
    head_w = max(12.0, head_w)
    head_d = min(footprint_d * 0.86, head_w * (0.74 if spec.style == "geometric" else 0.82))
    head_d = max(10.0, head_d)
    head_center_z = head_top - head_h * 0.5

    style_body_ratio = {"geometric": 0.30, "low_poly": 0.31, "chibi": 0.28}[spec.style]
    body_h = character_h * style_body_ratio * float(spec.proportions.body_scale)
    body_h = _bounded(body_h, character_h * 0.20, character_h * 0.36)
    body_w = min(
        footprint_w * 0.58,
        character_h * 0.27 * float(spec.proportions.body_scale),
    )
    body_w = max(10.0, body_w)
    body_d = min(footprint_d * 0.55, body_w * 0.78)
    body_d = max(9.0, body_d)
    body_top = head_center_z - head_h * 0.5 + penetration
    body_center_z = body_top - body_h * 0.5

    foot_h = _bounded(character_h * 0.065, 4.0, 7.5)
    limb_radius = _bounded(
        character_h * 0.043 * float(spec.proportions.limb_scale),
        DESIGNED_MINIMUM_FEATURE_MM * 0.5,
        5.4,
    )
    if body_center_z - body_h * 0.5 <= base_h + foot_h:
        raise ValueError("the reviewed body proportions do not fit above the requested base")

    return _Layout(
        target_h=target_h,
        base_h=base_h,
        base_w=base_w,
        base_d=base_d,
        character_h=character_h,
        penetration=penetration,
        top_reserve=top_reserve,
        head_top=head_top,
        head_h=head_h,
        head_w=head_w,
        head_d=head_d,
        head_center_z=head_center_z,
        body_h=body_h,
        body_w=body_w,
        body_d=body_d,
        body_center_z=body_center_z,
        foot_h=foot_h,
        limb_radius=limb_radius,
    )


def _base(composer: _Composer) -> None:
    spec = composer.request.spec
    layout = composer.layout
    if spec.base.preset == "none":
        return
    common = {
        "name": "Display_Base",
        "collection": composer.character,
        "center_mm": (0.0, 0.0, layout.base_h * 0.5),
        "dimensions_mm": (layout.base_w, layout.base_d, layout.base_h),
        "material": composer.palette(0),
        "print_source": True,
        "minimum_feature_mm": DESIGNED_MINIMUM_FEATURE_MM,
    }
    if spec.base.preset == "round":
        obj = cylinder_dimensions(**common, vertices=48)
    elif spec.base.preset == "hexagonal":
        obj = cylinder_dimensions(**common, vertices=6, rotation_z=math.pi / 6.0)
    elif spec.base.preset == "square":
        obj = rounded_box(**common, bevel_mm=min(2.0, layout.base_h * 0.28))
    else:
        raise ValueError(f"unsupported base preset: {spec.base.preset!r}")
    obj["builder_part"] = "base"
    obj["requested_width_mm"] = layout.base_w
    obj["requested_depth_mm"] = layout.base_d
    obj["requested_height_mm"] = layout.base_h
    composer.add(obj)


def _styled_volume(
    composer: _Composer,
    *,
    name: str,
    center: Sequence[float],
    dimensions: Sequence[float],
    material: bpy.types.Material,
    role: str,
) -> bpy.types.Object:
    style = composer.request.spec.style
    common = {
        "name": name,
        "collection": composer.character,
        "center_mm": center,
        "dimensions_mm": dimensions,
        "material": material,
        "print_source": True,
        "minimum_feature_mm": DESIGNED_MINIMUM_FEATURE_MM,
    }
    if style == "geometric" and role == "head":
        obj = rounded_box(**common, bevel_mm=min(dimensions) * 0.13)
    elif style == "geometric" and role == "body":
        obj = ellipsoid(**common, segments=24, rings=16)
    elif style == "low_poly":
        obj = ico_ellipsoid(**common, subdivisions=2)
    else:
        obj = ellipsoid(**common, segments=28, rings=18)
    obj["builder_part"] = role
    return composer.add(obj)


def _core(composer: _Composer) -> None:
    layout = composer.layout
    _styled_volume(
        composer,
        name="Display_Body",
        center=(0.0, 0.0, layout.body_center_z),
        dimensions=(layout.body_w, layout.body_d, layout.body_h),
        material=composer.palette(0),
        role="body",
    )
    _styled_volume(
        composer,
        name="Display_Head",
        center=(0.0, 0.0, layout.head_center_z),
        dimensions=(layout.head_w, layout.head_d, layout.head_h),
        material=composer.palette(1),
        role="head",
    )


def _feet_and_legs(composer: _Composer) -> None:
    layout = composer.layout
    foot_w = max(5.0, layout.limb_radius * 2.25)
    foot_d = max(6.0, layout.limb_radius * 2.55)
    foot_bottom = layout.base_h - layout.penetration if layout.base_h > 0 else 0.0
    foot_center_z = foot_bottom + layout.foot_h * 0.5
    leg_x = min(layout.body_w * 0.24, layout.base_w * 0.25)
    body_bottom = layout.body_center_z - layout.body_h * 0.5
    leg_start_z = foot_center_z + layout.foot_h * 0.30
    leg_end_z = body_bottom + layout.penetration
    for side, x in (("L", -leg_x), ("R", leg_x)):
        foot = ellipsoid(
            name=f"Display_Foot_{side}",
            collection=composer.character,
            center_mm=(x, -foot_d * 0.08, foot_center_z),
            dimensions_mm=(foot_w, foot_d, layout.foot_h),
            material=composer.palette(1),
            segments=20,
            rings=12,
            minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
        )
        foot["builder_part"] = "foot"
        composer.add(foot)
        leg = cylinder_between(
            name=f"Display_Leg_{side}",
            collection=composer.character,
            start_mm=(x, 0.0, leg_start_z),
            end_mm=(x, 0.0, leg_end_z),
            radius_mm=layout.limb_radius,
            material=composer.palette(0),
            vertices=20,
            overlap_mm=layout.penetration * 2.0,
            minimum_feature_mm=layout.limb_radius * 2.0,
        )
        leg["builder_part"] = "leg"
        composer.add(leg)


def _limb_segment(
    composer: _Composer,
    name: str,
    start: Sequence[float],
    end: Sequence[float],
) -> None:
    obj = cylinder_between(
        name=name,
        collection=composer.character,
        start_mm=start,
        end_mm=end,
        radius_mm=composer.layout.limb_radius,
        material=composer.palette(0),
        vertices=20,
        overlap_mm=composer.layout.penetration * 2.0,
        minimum_feature_mm=composer.layout.limb_radius * 2.0,
    )
    obj["builder_part"] = "arm"
    composer.add(obj)


def _hand(composer: _Composer, side: str, center: Sequence[float]) -> None:
    diameter = max(DESIGNED_MINIMUM_FEATURE_MM, composer.layout.limb_radius * 2.25)
    obj = ellipsoid(
        name=f"Display_Hand_{side}",
        collection=composer.character,
        center_mm=center,
        dimensions_mm=(diameter, diameter, diameter),
        material=composer.palette(1),
        segments=18,
        rings=12,
        minimum_feature_mm=diameter,
    )
    obj["builder_part"] = "hand"
    composer.add(obj)


def _arms(composer: _Composer) -> None:
    layout = composer.layout
    pose = composer.request.spec.pose
    shoulder_z = layout.body_center_z + layout.body_h * 0.26
    shoulder_x = layout.body_w * 0.46
    lower_z = layout.body_center_z - layout.body_h * 0.24
    max_x = layout.base_w * 0.5 - layout.limb_radius * 1.25
    for side, sign in (("L", -1.0), ("R", 1.0)):
        shoulder = (sign * shoulder_x, 0.0, shoulder_z)
        if pose == "wave" and side == "R":
            elbow = (
                sign * min(max_x * 0.80, shoulder_x + layout.limb_radius * 2.3),
                0.0,
                shoulder_z + layout.body_h * 0.18,
            )
            hand = (
                sign * min(max_x, shoulder_x + layout.limb_radius * 2.0),
                0.0,
                min(layout.head_center_z, shoulder_z + layout.body_h * 0.62),
            )
            _limb_segment(composer, f"Display_Arm_{side}_Upper", shoulder, elbow)
            _limb_segment(composer, f"Display_Arm_{side}_Lower", elbow, hand)
        elif pose == "heroic":
            elbow = (
                sign * min(max_x, shoulder_x + layout.limb_radius * 2.2),
                0.0,
                layout.body_center_z,
            )
            hand = (sign * layout.body_w * 0.42, -layout.body_d * 0.15, lower_z)
            _limb_segment(composer, f"Display_Arm_{side}_Upper", shoulder, elbow)
            _limb_segment(composer, f"Display_Arm_{side}_Lower", elbow, hand)
        else:
            hand = (sign * min(max_x, shoulder_x + layout.limb_radius * 0.55), 0.0, lower_z)
            _limb_segment(composer, f"Display_Arm_{side}", shoulder, hand)
        _hand(composer, side, hand)


def _face(composer: _Composer) -> None:
    layout = composer.layout
    preset = composer.request.spec.eye_preset
    front_y = -layout.head_d * 0.5
    eye_z = layout.head_center_z + layout.head_h * 0.05
    eye_gap = layout.head_w * 0.20
    depth = max(DESIGNED_MINIMUM_FEATURE_MM, layout.head_d * 0.09)
    eye_w = _bounded(layout.head_w * 0.14, 3.2, 7.5)
    eye_h = eye_w
    if preset == "visor":
        obj = rounded_box(
            name="Display_Eyes_Visor",
            collection=composer.character,
            center_mm=(0.0, front_y - depth * 0.20, eye_z),
            dimensions_mm=(layout.head_w * 0.52, depth, max(3.0, eye_h * 0.70)),
            bevel_mm=1.2,
            material=composer.materials.feature,
            minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
        )
        obj["builder_part"] = "eye"
        composer.add(obj)
        return
    for side, x in (("L", -eye_gap), ("R", eye_gap)):
        if preset == "sleepy":
            obj = rounded_box(
                name=f"Display_Eye_{side}_Sleepy",
                collection=composer.character,
                center_mm=(x, front_y - depth * 0.20, eye_z),
                dimensions_mm=(eye_w * 1.35, depth, 3.0),
                bevel_mm=0.75,
                material=composer.materials.feature,
                rotation_euler=(0.0, -0.16 if side == "L" else 0.16, 0.0),
                minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
            )
        else:
            obj = ellipsoid(
                name=f"Display_Eye_{side}_Round",
                collection=composer.character,
                center_mm=(x, front_y - depth * 0.20, eye_z),
                dimensions_mm=(eye_w, depth, eye_h),
                material=composer.materials.feature,
                segments=18,
                rings=12,
                minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
            )
        obj["builder_part"] = "eye"
        composer.add(obj)


def _antennae(composer: _Composer) -> None:
    layout = composer.layout
    ball_d = max(3.2, layout.top_reserve * 0.30)
    top_ball_z = layout.target_h - ball_d * 0.5
    x_offset = layout.head_w * 0.23
    attachment_z = layout.head_top - max(layout.penetration, layout.head_h * 0.20)
    for side, x in (("L", -x_offset), ("R", x_offset)):
        rod = cylinder_between(
            name=f"Display_Antenna_{side}",
            collection=composer.character,
            start_mm=(x, 0.0, attachment_z),
            end_mm=(x, 0.0, top_ball_z),
            radius_mm=DESIGNED_MINIMUM_FEATURE_MM * 0.5,
            material=composer.palette(0),
            vertices=16,
            overlap_mm=layout.penetration,
            minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
        )
        rod["builder_part"] = "antenna"
        composer.add(rod)
        tip = ellipsoid(
            name=f"Display_AntennaTip_{side}",
            collection=composer.character,
            center_mm=(x, 0.0, top_ball_z),
            dimensions_mm=(ball_d, ball_d, ball_d),
            material=composer.palette(1),
            segments=16,
            rings=10,
            minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
        )
        tip["builder_part"] = "antenna-tip"
        composer.add(tip)


def _upright_frustums(composer: _Composer, component: str) -> None:
    layout = composer.layout
    if component == "pointed-ears":
        spread, base_radius, tip_radius = 0.28, max(3.2, layout.head_w * 0.085), 1.5
        label = "PointedEar"
    elif component == "long-horns":
        spread, base_radius, tip_radius = 0.24, max(2.5, layout.head_w * 0.065), 1.5
        label = "LongHorn"
    else:
        spread, base_radius, tip_radius = 0.25, max(2.3, layout.head_w * 0.06), 1.5
        label = "ShortHorn"
    attachment_z = layout.head_top - max(layout.penetration, layout.head_h * 0.20)
    for side, sign in (("L", -1.0), ("R", 1.0)):
        x = sign * layout.head_w * spread
        obj = cone_between(
            name=f"Display_{label}_{side}",
            collection=composer.character,
            start_mm=(x, 0.0, attachment_z),
            end_mm=(x, 0.0, layout.target_h),
            radius_start_mm=base_radius,
            radius_end_mm=tip_radius,
            material=composer.palette(0),
            vertices=20,
            overlap_mm=0.0,
            minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
        )
        obj["builder_part"] = component
        composer.add(obj)


def _round_ears(composer: _Composer) -> None:
    layout = composer.layout
    attachment_depth = max(layout.penetration, layout.head_h * 0.20)
    height = layout.top_reserve + attachment_depth
    width = max(4.0, min(layout.head_w * 0.18, layout.base_w * 0.13))
    center_z = (layout.target_h + layout.head_top - attachment_depth) * 0.5
    x = min(layout.head_w * 0.43, layout.base_w * 0.5 - width * 0.5)
    for side, signed_x in (("L", -x), ("R", x)):
        obj = ellipsoid(
            name=f"Display_RoundEar_{side}",
            collection=composer.character,
            center_mm=(signed_x, 0.0, center_z),
            dimensions_mm=(width, layout.head_d * 0.34, height),
            material=composer.palette(0),
            segments=18,
            rings=12,
            minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
        )
        obj["builder_part"] = "round-ears"
        composer.add(obj)


def _badge(composer: _Composer) -> None:
    layout = composer.layout
    radius = _bounded(layout.body_w * 0.13, 2.4, 5.0)
    depth = DESIGNED_MINIMUM_FEATURE_MM
    obj = cylinder(
        name="Display_ChestBadge",
        collection=composer.character,
        center_mm=(
            0.0,
            -layout.body_d * 0.5 - depth * 0.20,
            layout.body_center_z + layout.body_h * 0.08,
        ),
        radius_mm=radius,
        depth_mm=depth,
        material=composer.palette(1),
        vertices=6,
        rotation_euler=(math.pi / 2.0, 0.0, 0.0),
        minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
    )
    obj["builder_part"] = "chest-badge"
    composer.add(obj)


def _backpack(composer: _Composer) -> None:
    layout = composer.layout
    width = min(layout.body_w * 0.78, layout.base_w * 0.42)
    depth = max(4.0, layout.body_d * 0.42)
    height = layout.body_h * 0.68
    obj = rounded_box(
        name="Display_Backpack",
        collection=composer.character,
        center_mm=(
            0.0,
            layout.body_d * 0.5 + depth * 0.18,
            layout.body_center_z + layout.body_h * 0.02,
        ),
        dimensions_mm=(width, depth, height),
        bevel_mm=min(2.0, depth * 0.22),
        material=composer.palette(2),
        minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
    )
    obj["builder_part"] = "backpack"
    composer.add(obj)


def _tail(composer: _Composer, swept: bool) -> None:
    layout = composer.layout
    radius = max(1.5, layout.limb_radius * 0.62)
    start = (0.0, layout.body_d * 0.38, layout.body_center_z - layout.body_h * 0.14)
    if swept:
        mid = (
            layout.body_w * 0.24,
            min(layout.base_d * 0.32, layout.body_d * 0.92),
            layout.body_center_z - layout.body_h * 0.02,
        )
        end = (
            layout.body_w * 0.38,
            min(layout.base_d * 0.40, layout.body_d * 1.18),
            layout.body_center_z + layout.body_h * 0.14,
        )
        _limb_segment_custom(composer, "Display_Tail_Swept_A", start, mid, radius)
        _limb_segment_custom(composer, "Display_Tail_Swept_B", mid, end, radius)
    else:
        end = (
            0.0,
            min(layout.base_d * 0.40, layout.body_d * 0.92),
            layout.body_center_z - layout.body_h * 0.06,
        )
        _limb_segment_custom(composer, "Display_Tail_Stub", start, end, radius)
    tip_d = max(DESIGNED_MINIMUM_FEATURE_MM, radius * 2.2)
    tip = ellipsoid(
        name="Display_Tail_Tip",
        collection=composer.character,
        center_mm=end,
        dimensions_mm=(tip_d, tip_d, tip_d),
        material=composer.palette(1),
        segments=16,
        rings=10,
        minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
    )
    tip["builder_part"] = "tail-tip"
    composer.add(tip)


def _limb_segment_custom(
    composer: _Composer,
    name: str,
    start: Sequence[float],
    end: Sequence[float],
    radius: float,
) -> None:
    obj = cylinder_between(
        name=name,
        collection=composer.character,
        start_mm=start,
        end_mm=end,
        radius_mm=radius,
        material=composer.palette(0),
        vertices=18,
        overlap_mm=composer.layout.penetration * 2.0,
        minimum_feature_mm=max(DESIGNED_MINIMUM_FEATURE_MM, radius * 2.0),
    )
    obj["builder_part"] = "tail"
    composer.add(obj)


def _components(composer: _Composer) -> None:
    handlers: dict[str, Callable[[_Composer], None]] = {
        "antenna-pair": _antennae,
        "backpack": _backpack,
        "chest-badge": _badge,
        "long-horns": lambda value: _upright_frustums(value, "long-horns"),
        "pointed-ears": lambda value: _upright_frustums(value, "pointed-ears"),
        "round-ears": _round_ears,
        "short-horns": lambda value: _upright_frustums(value, "short-horns"),
        "stub-tail": lambda value: _tail(value, swept=False),
        "swept-tail": lambda value: _tail(value, swept=True),
    }
    for component in composer.request.spec.components:
        try:
            handler = handlers[component]
        except KeyError as exc:
            raise ValueError(f"unimplemented reviewed component: {component!r}") from exc
        handler(composer)


def _assert_scene_limits(display_objects: Sequence[bpy.types.Object]) -> None:
    if len(bpy.context.scene.objects) > 256:
        raise RuntimeError("generated scene exceeds the 256-object limit")
    if len(bpy.data.materials) > 64:
        raise RuntimeError("generated scene exceeds the 64-material limit")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    triangles = 0
    for obj in display_objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            triangles += len(mesh.loop_triangles)
        finally:
            evaluated.to_mesh_clear()
    if triangles > 500_000:
        raise RuntimeError("generated display scene exceeds the 500,000-triangle limit")


def generate(request: BuildRequest) -> GenerationResult:
    """Compile one validated request into display meshes and one print shell."""

    if request.generator != GENERATOR:
        raise ValueError(f"unsupported generator: {request.generator!r}")
    target_h = float(request.spec.height_mm)
    voxel_size_mm = _bounded(target_h / 300.0, 0.26, 0.48)
    layout = _layout(request, voxel_size_mm)
    scene_context = factory_scene()
    materials = create_material_set(request.spec.palette, request.spec.material_preset)
    composer = _Composer(
        request=request,
        character=scene_context.collections["CHARACTER"],
        materials=materials,
        layout=layout,
    )
    _base(composer)
    _feet_and_legs(composer)
    _core(composer)
    _arms(composer)
    _face(composer)
    _components(composer)
    _assert_scene_limits(composer.objects)

    printable = derive_printable_shell(
        display_objects=composer.objects,
        print_collection=scene_context.collections["PRINT"],
        material=materials.printable,
        target_height_mm=target_h,
        voxel_size_mm=voxel_size_mm,
    )
    _assert_scene_limits((*composer.objects, printable))
    bpy.context.view_layer.update()
    return GenerationResult(
        generator_id=GENERATOR,
        display_object_names=tuple(sorted(obj.name for obj in composer.objects)),
        printable_object_name=printable.name,
        designed_minimum_feature_mm=DESIGNED_MINIMUM_FEATURE_MM,
        voxel_size_mm=voxel_size_mm,
        request_sha256=request.request_sha256,
        spec_sha256=request.spec_sha256,
        collection_names=COLLECTION_NAMES,
    )
