# M0 Workspace Inventory

Recorded: 2026-08-02

This inventory preserves the pre-refactor Blender proof of concept as baseline evidence. Paths are relative to the workspace root. The files in this document remain ignored unless a later gate explicitly introduces a generalized replacement.

## Preserved generated artifacts

| File | Bytes | SHA-256 | Role |
|---|---:|---|---|
| `codex_self_portrait.blend` | 5,670,054 | `b5ec3be820e32d419bf865053b2e7db201dd8212e48ac2b83bbc412d8d0d3b87` | Editable static baseline |
| `codex_self_portrait.blend1` | 5,670,054 | `d5469fc2b93076f517889d1c15169d3efb73662ea8bc0fb474366a045e977385` | Local Blender backup; never publication source |
| `codex_self_portrait.glb` | 2,521,760 | `782e886e48ee4ddf6064f8393d49cfb8db3be88a6be56f108cb93df7982a4f0e` | Portable model baseline |
| `codex_self_portrait_beauty.png` | 1,308,550 | `5b5be1eab211510539877329b1d645055456bca6d40861702b0a16157d24f8e2` | Front presentation render |
| `codex_self_portrait_alt.png` | 1,354,711 | `f37745fc97518620870a54af736199b62404fe4991066a2412d8810716fdc438` | Alternate presentation render |
| `codex_model_wireframe_front.png` | 1,124,494 | `3ab8ce4f28a9a28950bbf21e6bb7b0ee340b76b9fcf9d55fbc9fff028f27aecf` | Front geometry proof |
| `codex_model_wireframe_side.png` | 1,048,592 | `21eb8953ee5644c2872094e0d385b25184a1ec693f26f7f29b0a195a300f2c49` | Side geometry proof |
| `codex_model_wireframe_back.png` | 1,067,304 | `3365766ebef59d2992eb4ffc8d716e8d17b7bc0a990ae5d6e9c660bf21c1baf8` | Back geometry proof |
| `codex_self_portrait_turntable.blend` | 553,424 | `8351439634da4aee300d05f52d70e0fbc2ebb2796ca50067c56bb94ad8d0a8fa` | Animated baseline |
| `codex_self_portrait_turntable.blend1` | 553,412 | `4ccd63e5b00f6e01edf2e94e5f43f304dca0e30178708a09c5764e6785f3c44b` | Local Blender backup; never publication source |
| `codex_self_portrait_turntable.mp4` | 627,112 | `5c143add83328a804c2f0e07ccb9434af8764cdf917bf836ee5ddf10e714df24` | Optional animation baseline; animation is outside v0.1 |

## Preserved prototype sources

| File | Bytes | SHA-256 | Reusable material | Required generalization |
|---|---:|---|---|---|
| `create_codex_avatar.py` | 31,466 | `579e3ea3b1202153a252608f19b30c0f8a3ff936248f6b3996b09e0441c9648b` | Primitive, material, camera, light, save, render, and GLB patterns | Remove global paths, branding, text objects, fixed proportions, and scene-specific assertions |
| `prove_model_geometry.py` | 9,891 | `ff70afbc85981a6b162e4b8b237a8c83a4223fb204c2e17fda568856b46f45f0` | Evaluated topology, bounds, external-image, and diagnostic-view checks | Accept a build context and emit versioned JSON |
| `verify_codex_avatar.py` | 9,017 | `3837eade5ef2e6bdee8914c1743a5a401b4b8a37b48c12e3c28d321fdda347fc` | Fresh-process reload, GLB header, mesh/material, render-statistics checks | Replace signature-name/count checks with generic contracts |
| `create_turntable_animation.py` | 6,622 | `5c3898de5609d376dc95858118f5ba1269660a11b1ed40fd94b0aa367c56715c` | Parent-root rotation and linear animation pattern | Post-v0.1 only; remove hardcoded names and output paths |
| `verify_turntable_animation.py` | 6,105 | `49f2daa6d0b994aa55bc85c1103c808c887ece10456fcbf62a42c007e12a0d76` | Fresh-process motion/framing checks | Post-v0.1 only |

Business-report files and `queries/` are preserved locally and ignored. They are not technical release inputs.

## Baseline verification

The installed native tool is Blender 4.5.12 LTS on macOS Apple Silicon. Blender is installed as an application rather than on `PATH`.

The following fresh-process checks passed on 2026-08-02. Both loaded existing files read-only and wrote audit images only to the operating-system temporary directory.

```sh
BLENDER_BIN="/Applications/Blender.app/Contents/MacOS/Blender"
"$BLENDER_BIN" --background --factory-startup --offline-mode --disable-autoexec \
  codex_self_portrait.blend --python-exit-code 1 --python verify_codex_avatar.py

"$BLENDER_BIN" --background --factory-startup --offline-mode --disable-autoexec \
  codex_self_portrait_turntable.blend --python-exit-code 1 \
  --python verify_turntable_animation.py
```

Observed results:

- `CODEX_AVATAR_VERIFICATION: PASS`;
- saved-model camera bounds `x=0.084..0.884`, `y=0.016..0.926`;
- fresh-reload 256 × 256 smoke render succeeded;
- `TURN_TABLE_VERIFICATION: PASS`;
- MP4 decoded as 640 × 640, 144 frames, 24 fps;
- all five sampled turntable angles and framing checks passed.

The sandboxed first launch could not initialize the macOS Metal backend and exited `139`; the same headless command passed with normal application access. This is an execution-environment note, not a model failure.

## Preservation rule

The baseline files above must not be deleted, renamed, regenerated in place, or staged. New implementation output belongs under ignored `build/`. Generalized source is written as new tracked modules; the branded scripts remain historical local evidence.
