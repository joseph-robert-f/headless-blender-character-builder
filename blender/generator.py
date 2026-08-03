"""The `geometric-character@1.0.0` generator.

Composes one original character from closed primitives, then boolean-unions
everything into a single watertight shell. The union is not cosmetic: a pile of
intersecting-but-separate solids slices into a mess of internal walls, whereas
one manifold shell is what a slicer actually wants.

Two print rules are enforced here rather than only being measured afterwards:

* every freestanding feature (limb, antenna, horn, tail) is thickened until its
  diameter reaches `min_feature_mm`, so a small model gets chunkier limbs
  instead of failing QA;
* adjacent parts are deliberately overlapped by a weld margin, so the union
  produces one connected shell instead of parts touching at a single face.

Every adjustment made on the user's behalf is recorded and surfaced in the
build report, because silently changing someone's requested proportions would
be worse than the failure it prevents.

The generator makes no random choices. An identical request always produces an
identical structure.
"""

import math

import bpy
from mathutils import Matrix, Vector

from . import materials, primitives, scene
from .materials import SLOT_ACCENT, SLOT_BODY, SLOT_DETAIL

# Fractions of the character's body height (everything above the base).
# head + torso + legs are normalised to 1.0 after the spec's proportion
# multipliers are applied, which is what keeps total height exact.
STYLES = {
    "geometric": {
        "head": 0.30,
        "torso": 0.36,
        "legs": 0.34,
        "segments": 32,
        "faceted": False,
        "bevel_fraction": 0.16,
        "head_shape": "box",
        "roughness": 0.45,
    },
    "low_poly": {
        "head": 0.26,
        "torso": 0.38,
        "legs": 0.36,
        "segments": 8,
        "faceted": True,
        "bevel_fraction": 0.0,
        "head_shape": "faceted",
        "roughness": 0.55,
    },
    "chibi": {
        "head": 0.42,
        "torso": 0.32,
        "legs": 0.26,
        "segments": 32,
        "faceted": False,
        "bevel_fraction": 0.34,
        "head_shape": "sphere",
        "roughness": 0.35,
    },
}

# Extra height reserved above the head for features that stick up, as a
# fraction of total height. Without this reservation an antenna would push the
# model past its requested height.
CROWN_ALLOWANCE = {
    "none": 0.0,
    "antenna": 0.10,
    "short": 0.06,
    "curved": 0.09,
}


class Report:
    """Records what the generator did, including anything it had to change."""

    def __init__(self):
        self.adjustments = []
        self.parts = []

    def adjust(self, message):
        self.adjustments.append(message)

    def part(self, name):
        self.parts.append(name)


class _Builder:
    def __init__(self, spec, print_profile, report):
        self.spec = spec
        self.profile = print_profile
        self.report = report
        self.style = STYLES[spec["style"]]
        self.palette = materials.Palette(spec["palette"])
        self.parts = []

        self.min_feature = print_profile["min_feature_mm"]
        self.min_radius = self.min_feature / 2.0

        self._plan_dimensions()

    # -- planning ----------------------------------------------------------

    def _plan_dimensions(self):
        spec = self.spec
        style = self.style
        total_h = float(spec["height_mm"])
        base = spec["base"]

        base_h = float(base["height_mm"]) if base["enabled"] else 0.0
        # A tall pedestal under a short character leaves nothing to look at, so
        # the base is capped at a quarter of the model.
        if base_h > total_h * 0.25:
            capped = round(total_h * 0.25, 2)
            self.report.adjust(
                "base height reduced from %.1f mm to %.1f mm so the base stays "
                "under a quarter of the model height" % (base_h, capped)
            )
            base_h = capped

        features = spec["features"]
        crown_fraction = max(
            CROWN_ALLOWANCE.get(features["ears"], 0.0),
            CROWN_ALLOWANCE.get(features["horns"], 0.0),
        )
        crown_h = total_h * crown_fraction

        body_h = total_h - base_h - crown_h

        proportions = spec["proportions"]
        head_share = style["head"] * proportions["head_scale"]
        torso_share = style["torso"]
        leg_share = style["legs"] * proportions["leg_length"]
        share_total = head_share + torso_share + leg_share

        self.total_h = total_h
        self.base_h = base_h
        self.crown_h = crown_h
        self.body_h = body_h
        self.head_h = body_h * head_share / share_total
        self.torso_h = body_h * torso_share / share_total
        self.leg_h = body_h * leg_share / share_total

        width = proportions["torso_width"]
        self.torso_w = body_h * 0.40 * width
        self.torso_d = body_h * 0.28 * width

        if style["head_shape"] == "sphere":
            self.head_w = self.head_h
            self.head_d = self.head_h * 0.92
        else:
            self.head_w = self.head_h * 0.98
            self.head_d = self.head_h * 0.88

        limb = proportions["limb_scale"]
        self.leg_r = self._thicken(body_h * 0.075 * limb, "leg")
        self.arm_r = self._thicken(body_h * 0.060 * limb, "arm")

        self.wide = spec["pose"] == "wide_stance"
        self.leg_offset = self.torso_w * (0.34 if self.wide else 0.24)
        # Legs must not float outside the torso they hang from.
        self.leg_offset = min(self.leg_offset, self.torso_w / 2.0 - self.leg_r * 0.2)

        # Weld margin: how far neighbouring parts push into each other so the
        # union yields one connected shell rather than parts kissing at a face.
        self.weld = max(0.6, body_h * 0.015)

        self.ground_z = base_h
        self.torso_bottom = self.ground_z + self.leg_h
        self.torso_top = self.torso_bottom + self.torso_h
        self.head_bottom = self.torso_top
        self.head_top = self.head_bottom + self.head_h

    def _thicken(self, radius, what):
        """Raise a radius to the printable minimum, recording the change."""
        if radius >= self.min_radius:
            return radius
        self.report.adjust(
            "%s diameter raised from %.2f mm to %.2f mm to meet the profile's "
            "%.2f mm minimum feature size" % (what, radius * 2, self.min_feature, self.min_feature)
        )
        return self.min_radius

    # -- parts -------------------------------------------------------------

    def _add(self, obj_or_list, slot, roughness=None):
        objects = obj_or_list if isinstance(obj_or_list, list) else [obj_or_list]
        material = self.palette.material(
            slot, roughness=self.style["roughness"] if roughness is None else roughness
        )
        for obj in objects:
            materials.assign(obj, material)
            self.parts.append(obj)
            self.report.part(obj.name)
        return objects

    def build(self):
        self._build_torso()
        self._build_legs()
        self._build_arms()
        self._build_head()
        self._build_face()
        self._build_ears()
        self._build_horns()
        self._build_tail()
        self._build_backpack()
        self._build_base()
        return self.parts

    def _build_torso(self):
        bevel = min(self.torso_w, self.torso_d) * self.style["bevel_fraction"]
        torso = primitives.rounded_box(
            "torso",
            (self.torso_w, self.torso_d, self.torso_h),
            location=(0.0, 0.0, self.torso_bottom + self.torso_h / 2.0),
            radius=bevel,
        )
        self._add(torso, SLOT_BODY)

    def _build_legs(self):
        segments = self.style["segments"]
        bottom = self.ground_z - (self.weld if self.base_h > 0 else 0.0)
        top = self.torso_bottom + self.weld
        height = top - bottom
        foot_h = max(self.leg_r * 0.7, self.min_feature)
        for side in (-1, 1):
            x = side * self.leg_offset
            self._add(
                primitives.cylinder(
                    "leg-%s" % ("l" if side < 0 else "r"),
                    self.leg_r,
                    height,
                    location=(x, 0.0, bottom + height / 2.0),
                    segments=segments,
                ),
                SLOT_ACCENT,
            )
            # A foot widens the first layer, which is the difference between a
            # model that sticks to the bed and one that pops off mid-print.
            # With a base present the foot is sunk slightly deeper than the leg
            # so their bottom faces are not coplanar inside the union. With no
            # base both sit flat on Z=0, which is what the printer needs.
            foot_bottom = bottom - (self.weld * 0.4 if self.base_h > 0 else 0.0)
            self._add(
                primitives.rounded_box(
                    "foot-%s" % ("l" if side < 0 else "r"),
                    (self.leg_r * 2.4, self.leg_r * 3.2, foot_h),
                    location=(x, -self.leg_r * 0.5, foot_bottom + foot_h / 2.0),
                    radius=foot_h * 0.25,
                ),
                SLOT_ACCENT,
            )

    def _build_arms(self):
        segments = self.style["segments"]
        arm_len = self.torso_h * 0.86
        shoulder_z = self.torso_top - self.torso_h * 0.12
        x_offset = self.torso_w / 2.0 + self.arm_r * 0.35

        # Arms are always built hanging straight down from the shoulder and
        # then rotated about that shoulder point. Translating them instead
        # would move the top of the arm away from the body and leave it as a
        # separate shell after the union.
        tilt = {"t_pose": 90.0, "wide_stance": 18.0}.get(self.spec["pose"], 0.0)

        for side in (-1, 1):
            name = "arm-%s" % ("l" if side < 0 else "r")
            pivot = Vector((side * x_offset, 0.0, shoulder_z))
            parts = primitives.capsule(
                name,
                self.arm_r,
                arm_len,
                location=(pivot.x, pivot.y, shoulder_z - arm_len / 2.0 + self.arm_r),
                segments=segments,
                faceted=self.style["faceted"],
            )
            if tilt:
                # Negative angle for the +X side swings the arm outward.
                rotation = Matrix.Rotation(math.radians(-side * tilt), 4, "Y")
                about_pivot = Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot)
                for part in parts:
                    part.matrix_world = about_pivot @ part.matrix_world
                bpy.context.view_layer.update()
            self._add(parts, SLOT_ACCENT)

        # The shoulders bridge arm to torso so the union cannot leave a hairline
        # contact that later reads as a separate shell. The slight drop keeps
        # the shoulder sphere's equator out of the plane of the arm cap's
        # equator; two coincident equator rings union into zero-area faces.
        for side in (-1, 1):
            self._add(
                primitives.sphere(
                    "shoulder-%s" % ("l" if side < 0 else "r"),
                    self.arm_r * 1.15,
                    location=(
                        side * (self.torso_w / 2.0 - self.arm_r * 0.3),
                        0.0,
                        shoulder_z - self.arm_r * 0.17,
                    ),
                    segments=self.style["segments"],
                    faceted=self.style["faceted"],
                ),
                SLOT_ACCENT,
            )

    def _build_head(self):
        centre_z = self.head_bottom + self.head_h / 2.0
        shape = self.style["head_shape"]
        if shape == "box":
            head = primitives.rounded_box(
                "head",
                (self.head_w, self.head_d, self.head_h),
                location=(0.0, 0.0, centre_z),
                radius=min(self.head_w, self.head_d, self.head_h) * self.style["bevel_fraction"],
            )
        else:
            head = primitives.sphere(
                "head",
                self.head_h / 2.0,
                location=(0.0, 0.0, centre_z),
                segments=self.style["segments"],
                faceted=shape == "faceted",
                scale=(self.head_w / self.head_h, self.head_d / self.head_h, 1.0),
            )
        self._add(head, SLOT_BODY)

        neck_r = max(self.min_radius, min(self.head_w, self.torso_w) * 0.18)
        self._add(
            primitives.cylinder(
                "neck",
                neck_r,
                self.head_h * 0.35 + self.weld * 2,
                location=(0.0, 0.0, self.head_bottom),
                segments=self.style["segments"],
            ),
            SLOT_ACCENT,
        )

    def _build_face(self):
        eyes = self.spec["features"]["eyes"]
        if eyes == "none":
            return
        centre_z = self.head_bottom + self.head_h * 0.60
        front_y = -self.head_d / 2.0
        if eyes == "dot":
            eye_r = max(self.min_radius, self.head_w * 0.10)
            spacing = self.head_w * 0.24
            for side in (-1, 1):
                self._add(
                    primitives.sphere(
                        "eye-%s" % ("l" if side < 0 else "r"),
                        eye_r,
                        location=(side * spacing, front_y + eye_r * 0.45, centre_z),
                        segments=self.style["segments"],
                        faceted=self.style["faceted"],
                    ),
                    SLOT_DETAIL,
                    roughness=0.2,
                )
        else:
            visor_h = max(self.min_feature, self.head_h * 0.20)
            visor_d = max(self.min_feature, self.head_d * 0.16)
            self._add(
                primitives.rounded_box(
                    "visor",
                    (self.head_w * 0.78, visor_d, visor_h),
                    location=(0.0, front_y + visor_d * 0.35, centre_z),
                    radius=visor_h * 0.3,
                ),
                SLOT_DETAIL,
                roughness=0.15,
            )

    def _build_ears(self):
        ears = self.spec["features"]["ears"]
        if ears == "none":
            return
        head_centre_z = self.head_bottom + self.head_h / 2.0
        if ears == "round":
            ear_r = max(self.min_radius, self.head_w * 0.26)
            # Round ears get no reserved crown height, so they are seated far
            # enough down that they cannot poke above the requested height.
            ear_z = min(head_centre_z + self.head_h * 0.30, self.head_top - ear_r)
            for side in (-1, 1):
                self._add(
                    primitives.sphere(
                        "ear-%s" % ("l" if side < 0 else "r"),
                        ear_r,
                        location=(
                            side * (self.head_w / 2.0 - ear_r * 0.35),
                            0.0,
                            ear_z,
                        ),
                        segments=self.style["segments"],
                        faceted=self.style["faceted"],
                    ),
                    SLOT_BODY,
                )
            return

        # Antenna: a mast plus a ball, sized to fill the reserved crown height.
        mast_r = self._thicken(self.head_w * 0.05, "antenna")
        ball_r = max(self.min_radius, mast_r * 2.0)
        mast_h = max(self.crown_h - ball_r, self.crown_h * 0.5)
        mast_centre = self.head_top - self.weld + mast_h / 2.0
        self._add(
            primitives.cylinder(
                "antenna-mast",
                mast_r,
                mast_h + self.weld,
                location=(0.0, 0.0, mast_centre),
                segments=max(8, self.style["segments"] // 2),
            ),
            SLOT_ACCENT,
        )
        self._add(
            primitives.sphere(
                "antenna-tip",
                ball_r,
                location=(0.0, 0.0, self.head_top + self.crown_h - ball_r),
                segments=self.style["segments"],
                faceted=self.style["faceted"],
            ),
            SLOT_DETAIL,
            roughness=0.2,
        )

    def _build_horns(self):
        horns = self.spec["features"]["horns"]
        if horns == "none":
            return
        horn_r = self._thicken(self.head_w * 0.10, "horn")
        horn_h = self.crown_h if self.crown_h > 0 else self.head_h * 0.3
        tilt = math.radians(18.0 if horns == "short" else 34.0)
        for side in (-1, 1):
            self._add(
                primitives.cone(
                    "horn-%s" % ("l" if side < 0 else "r"),
                    horn_r,
                    max(horn_r * 0.25, self.min_radius * 0.6),
                    horn_h + self.weld,
                    location=(
                        side * self.head_w * 0.26,
                        0.0,
                        self.head_top - self.weld + horn_h / 2.0,
                    ),
                    rotation=(0.0, side * tilt, 0.0),
                    segments=max(8, self.style["segments"] // 2),
                ),
                SLOT_BODY,
            )

    def _build_tail(self):
        tail = self.spec["features"]["tail"]
        if tail == "none":
            return
        back_y = self.torso_d / 2.0
        centre_z = self.torso_bottom + self.torso_h * 0.28
        if tail == "stub":
            tail_r = max(self.min_radius, self.torso_w * 0.10)
            self._add(
                primitives.sphere(
                    "tail",
                    tail_r,
                    location=(0.0, back_y + tail_r * 0.4, centre_z),
                    segments=self.style["segments"],
                    faceted=self.style["faceted"],
                ),
                SLOT_BODY,
            )
            return
        tail_r = self._thicken(self.torso_w * 0.07, "tail")
        tail_len = self.torso_h * 0.75
        # Angled up and back so the tip does not need print supports.
        self._add(
            primitives.cone(
                "tail",
                tail_r,
                max(tail_r * 0.4, self.min_radius * 0.6),
                tail_len,
                location=(
                    0.0,
                    back_y + math.sin(math.radians(55.0)) * tail_len / 2.0 - self.weld,
                    centre_z + math.cos(math.radians(55.0)) * tail_len / 2.0,
                ),
                rotation=(math.radians(-55.0), 0.0, 0.0),
                segments=max(8, self.style["segments"] // 2),
            ),
            SLOT_BODY,
        )

    def _build_backpack(self):
        if not self.spec["features"]["backpack"]:
            return
        pack_w = self.torso_w * 0.66
        pack_d = max(self.min_feature, self.torso_d * 0.45)
        pack_h = self.torso_h * 0.55
        self._add(
            primitives.rounded_box(
                "backpack",
                (pack_w, pack_d, pack_h),
                location=(
                    0.0,
                    self.torso_d / 2.0 + pack_d / 2.0 - self.weld * 2,
                    self.torso_bottom + self.torso_h * 0.55,
                ),
                radius=min(pack_w, pack_d, pack_h) * 0.2,
            ),
            SLOT_DETAIL,
        )

    def _build_base(self):
        if self.base_h <= 0:
            return
        margin = float(self.spec["base"]["margin_mm"])
        half_x = max(self.torso_w / 2.0, self.leg_offset + self.leg_r * 1.6) + margin
        half_y = max(self.torso_d / 2.0, self.leg_r * 2.0) + margin
        centre_z = self.base_h / 2.0
        if self.spec["base"]["shape"] == "round":
            base = primitives.cylinder(
                "base",
                max(half_x, half_y),
                self.base_h,
                location=(0.0, 0.0, centre_z),
                segments=max(16, self.style["segments"]),
            )
        else:
            base = primitives.rounded_box(
                "base",
                (half_x * 2.0, half_y * 2.0, self.base_h),
                location=(0.0, 0.0, centre_z),
                radius=self.base_h * 0.18,
            )
        self._add(base, SLOT_ACCENT)


def _union(parts, name):
    """Boolean-union every part into the first one and return the result.

    A single Boolean modifier over a collection is used rather than one
    modifier per part: it is a single Exact-solver evaluation, which is both
    faster and less prone to accumulating tiny numerical seams between steps.
    """
    main = parts[0]
    operands = parts[1:]

    collection = bpy.data.collections.new("hbcb-union-operands")
    bpy.context.scene.collection.children.link(collection)
    for obj in operands:
        bpy.context.scene.collection.objects.unlink(obj)
        collection.objects.link(obj)

    modifier = main.modifiers.new(name="union", type="BOOLEAN")
    modifier.operation = "UNION"
    modifier.operand_type = "COLLECTION"
    modifier.collection = collection
    modifier.solver = "EXACT"
    # Without TRANSFER the result keeps only the first operand's material slots
    # and the model comes out a single flat colour.
    if hasattr(modifier, "material_mode"):
        modifier.material_mode = "TRANSFER"
    scene.apply_modifier(main, "union")

    for obj in list(collection.objects):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    bpy.data.collections.remove(collection)

    main.name = name
    main.data.name = name
    return main


def _orient_normals(obj):
    """Force every face normal outward, and change nothing else.

    It is tempting to also weld vertices and dissolve the zero-area triangles
    the Exact solver leaves along intersection seams. Measured across all three
    bundled presets, every welding threshold tried (1e-5 to 5e-4 mm, with and
    without a degenerate-edge dissolve) turned a watertight manifold mesh into
    one with open boundary edges, because at a seam the "duplicate" vertices
    are genuinely distinct corners of the surface.

    Zero-area triangles enclose no volume and are discarded by every mainstream
    slicer; a torn manifold is not. So the union's topology is left exactly as
    the solver produced it, and QA reports the degenerate count as an advisory.
    """
    import bmesh

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return obj


def _correct_height(obj, target_mm, report, tolerance=0.05):
    """Scale uniformly so the finished height matches the request exactly.

    Bevels and boolean seams can shift the bounding box by a few hundredths of
    a millimetre. The correction is tiny by construction; anything larger means
    the layout maths is wrong and is worth reporting.
    """
    height = scene.dimensions_mm(obj)[2]
    if height <= 0:
        raise RuntimeError("generated model has zero height")
    error = abs(height - target_mm)
    if error <= tolerance:
        return obj
    factor = target_mm / height
    if abs(factor - 1.0) > 0.02:
        report.adjust(
            "model height corrected by %.1f%% (built %.2f mm, requested %.2f mm)"
            % ((factor - 1.0) * 100.0, height, target_mm)
        )
    scene.select_only(obj)
    obj.scale = (factor, factor, factor)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def generate(spec, print_profile):
    """Build the character and return (object, Report)."""
    report = Report()
    builder = _Builder(spec, print_profile, report)
    parts = builder.build()
    if not parts:
        raise RuntimeError("generator produced no geometry")

    model = _union(parts, "character")
    _orient_normals(model)
    scene.center_on_origin_xy(model)
    scene.drop_to_floor(model)
    _correct_height(model, float(spec["height_mm"]), report)
    scene.drop_to_floor(model)

    # Origin at the model's own base makes the .blend pleasant to edit and puts
    # the STL's origin where a slicer expects it.
    scene.select_only(model)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return model, report
