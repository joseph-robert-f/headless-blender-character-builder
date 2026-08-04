"""Render four bounded PNG views and strip host-specific PNG metadata."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Mapping

import bpy


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
REMOVED_CHUNKS = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}
RENDER_TARGETS = (
    ("preview.png", "Camera_Preview"),
    ("diagnostics/front.png", "Camera_Front"),
    ("diagnostics/side.png", "Camera_Side"),
    ("diagnostics/back.png", "Camera_Back"),
)


def _sanitize_png(path: Path) -> None:
    payload = path.read_bytes()
    if not payload.startswith(PNG_SIGNATURE):
        raise RuntimeError(f"render is not a PNG: {path.name}")
    output = bytearray(PNG_SIGNATURE)
    offset = len(PNG_SIGNATURE)
    saw_ihdr = False
    saw_idat = False
    saw_iend = False
    while offset < len(payload):
        if offset + 12 > len(payload):
            raise RuntimeError("PNG chunk header is truncated")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(payload):
            raise RuntimeError("PNG chunk payload is truncated")
        kind = payload[offset + 4 : offset + 8]
        if kind == b"IHDR":
            saw_ihdr = True
        elif kind == b"IDAT":
            saw_idat = True
        elif kind == b"IEND":
            saw_iend = True
        if kind not in REMOVED_CHUNKS:
            output.extend(payload[offset:end])
        offset = end
        if kind == b"IEND":
            if offset != len(payload):
                raise RuntimeError("PNG contains trailing bytes after IEND")
            break
    if not (saw_ihdr and saw_idat and saw_iend):
        raise RuntimeError("PNG is missing a required chunk")
    path.write_bytes(bytes(output))


def _image_statistics(path: Path) -> dict[str, object]:
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = (int(value) for value in image.size)
        if width <= 0 or height <= 0:
            raise RuntimeError("render has invalid dimensions")
        pixels = image.pixels
        pixel_count = width * height
        step = max(1, pixel_count // 4096)
        values = []
        visible = 0
        for pixel_index in range(0, pixel_count, step):
            offset = pixel_index * 4
            red, green, blue, alpha = (
                float(pixels[offset + channel]) for channel in range(4)
            )
            values.append(red * 0.2126 + green * 0.7152 + blue * 0.0722)
            if alpha > 0.01:
                visible += 1
        if not values:
            raise RuntimeError("render contains no sampled pixels")
        minimum = min(values)
        maximum = max(values)
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        if maximum - minimum < 0.015 or variance < 0.00001 or visible == 0:
            raise RuntimeError("render lacks nonempty image variation")
        return {
            "width": width,
            "height": height,
            "sample_count": len(values),
            "luminance_min": round(minimum, 6),
            "luminance_max": round(maximum, 6),
            "luminance_variance": round(variance, 8),
        }
    finally:
        bpy.data.images.remove(image)


def render_diagnostics(output_root: Path) -> Mapping[str, Mapping[str, object]]:
    """Render the exact complete-v1 PNG set from saved-scene cameras."""

    scene = bpy.context.scene
    evidence = {}
    for relative_name, camera_name in RENDER_TARGETS:
        camera = bpy.data.objects.get(camera_name)
        if camera is None or camera.type != "CAMERA":
            raise RuntimeError(f"saved diagnostic camera is missing: {camera_name}")
        destination = output_root / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        scene.camera = camera
        scene.render.filepath = str(destination)
        result = bpy.ops.render.render(write_still=True)
        if "FINISHED" not in result or not destination.is_file():
            raise RuntimeError(f"Blender did not render {relative_name}")
        _sanitize_png(destination)
        stats = _image_statistics(destination)
        if stats["width"] > 1024 or stats["height"] > 1024:
            raise RuntimeError("render exceeds the v0.1 resolution cap")
        evidence[relative_name] = stats
    return evidence


__all__ = ["RENDER_TARGETS", "render_diagnostics"]
