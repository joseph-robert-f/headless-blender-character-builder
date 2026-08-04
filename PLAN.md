# Headless Blender Character Builder — execution plan

Status: **executable. v0.1 builder shipped; this plan covers v0.2.**

Supersedes [`docs/plan-archive-2026-07.md`](docs/plan-archive-2026-07.md).

---

## 0. How to use this document

This is a work queue, not a vision document. Sections 1–4 are context. Section
5 onward is the plan: numbered work packages, each with a stated goal, the
files it touches, and a **gate** — a command whose output decides whether the
package is done.

Rules for anyone (human or agent) executing it:

1. Work packages in order. `W1` blocks `W2` blocks `W3`; after that the
   dependency column tells you what can run in parallel.
2. **A package is done when its gate command passes, not when the code looks
   finished.** Paste the command, run it, keep the output.
3. Section 9 records decisions that are already made. Do not stop to re-ask
   them.
4. If evidence contradicts this plan, the code and `schemas/` win. Fix the
   plan in the same commit and say why in `docs/REVIEW.md`.
5. Never mark a gate passed from a mock, a skipped test, or a doc change.
   Record anything you could not run as unverified, and keep going on
   everything else.

The one-line objective, if you want to hand this to an agent:

```text
Execute PLAN.md work packages W1 through W7 in dependency order. Treat the
gates as binding: a package is done only when its gate command passes on real
Blender output. Use the Section 9 defaults without stopping for reversible
choices. Update CHANGELOG.md and docs/REVIEW.md as contracts change. Do not
build the HTTP service; it is out of scope. Finish with the exact gate
commands run, their results, and any genuine blockers.
```

---

## 1. Where the project actually is

Implemented, tested, and pushed:

- `hbcb/` — dependency-free core: canonical hashing, a JSON Schema subset
  validator, request resolution, print profiles, presets, manifest, Blender
  discovery, CLI.
- `blender/` — scene, primitives, materials, the `geometric-character@1.0.0`
  generator, exporters, Cycles rendering, print QA, independent verifier.
- `schemas/` — four versioned contracts (request, character spec, manifest, QA).
- 42 unit tests, 16 Blender integration tests, CI, container image.

Verified on Blender 4.5.12 LTS / linux-x86_64: all tests pass; three presets
build and verify with the full artifact set; STL re-imports watertight,
manifold, single-shell at exact dimensions; heights exact across 25–250 mm;
generation deterministic.

Known-unverified, carried forward as **W6**: the container image was never
built, the `blender` executable subprocess path was never exercised (all
testing used the `bpy` module), macOS/Windows discovery is untested, and
nothing has been physically printed.

Full detail: [`docs/REVIEW.md`](docs/REVIEW.md).

---

## 2. The problem this plan solves

The builder currently assumes every model is destined for a printer. That
assumption is baked in three places, and none of them is optional:

| Where | What it does | Why it is wrong for a digital user |
|---|---|---|
| `hbcb/print_profiles.py` | `print_profile` defaults to `fdm-0.4-standard` | Silently applies FDM constraints nobody asked for |
| `blender/generator.py` `_thicken` | Raises limb/antenna/horn/tail radii to `min_feature_mm` | Changes the artistic proportions of a model that will never be printed |
| `blender/qa.py` `evaluate` | Fails the build on `minimum_thickness` | A game asset with a 0.4 mm antenna is fine and currently cannot be built |

There is a fourth, subtler one. The generator **always** boolean-unions its
15–25 parts into one shell. That is exactly right for printing and often wrong
for digital work: a union throws away the part hierarchy, the clean per-part
topology, and the ability to move an arm in Blender afterwards. A game or
render asset usually wants the parts kept separate.

So "make print profiles optional" is really two changes: stop *constraining*
geometry for print, and stop *destroying* structure for print.

### Who this serves

- **Print user (today's default).** Wants an STL that slices. Wants the
  thickening. Wants a failed build when a wall is too thin.
- **Digital user (not currently served).** Wants a `.blend` and a `.glb` for a
  game engine, a render, a VTuber model, an asset pack. Wants exact requested
  proportions, editable separate parts, smooth shading, and UVs. Does not want
  an STL and must not be blocked by print checks.
- **Both.** Wants a display model rendered nicely *and* a printable variant.
  Should be two requests differing by one field, not two tools.

---

## 3. The contract change

One new field decides everything else.

```json
{
  "request_version": "build/v1",
  "generator": "geometric-character@1.0.0",
  "intent": "digital",
  "mesh": { "union": false, "shade_smooth": true, "uv": true },
  "spec": { "...": "unchanged" }
}
```

### `intent`

| | `print` (default) | `digital` |
|---|---|---|
| `print_profile` | defaults to `fdm-0.4-standard` | optional; advisory only if given |
| Minimum-feature thickening | enforced, reported | **never applied** |
| Boolean union | forced on | `mesh.union`, default **false** |
| Required QA checks | topology + `minimum_thickness` | topology only |
| Thickness / overhang | measured **and judged** | measured and reported |
| Default outputs | `.stl`, `.blend`, `.glb`, renders, QA, manifest | `.blend`, `.glb`, renders, QA, manifest — **no STL** |

The important property: `intent: "digital"` never fails a build for a reason
that only matters to a printer, and never silently alters requested
proportions.

### `mesh`

| Field | Type | Default | Effect |
|---|---|---|---|
| `union` | boolean | `true` when `intent: print`, `false` when `digital` | Union all parts into one shell, or keep them as separate named objects |
| `shade_smooth` | boolean | `false` for print, `true` for digital | Smooth-shade with a sharp-edge angle threshold |
| `uv` | boolean | `false` for print, `true` for digital | Generate UVs so the GLB is texturable |

`mesh.union: false` with `intent: print` is a contradiction — an STL of loose
overlapping solids is not printable — and is rejected at validation with that
explanation.

### Backward compatibility

Both fields are additive with defaults, so every existing request stays valid
and produces **identical geometry**. `request_version` stays `build/v1`.

One real consequence, called out because it will otherwise look like a bug:
filling the new defaults changes the resolved document, so `resolved_sha256`
in manifests will differ from any recorded before this change.
`request_sha256` is unaffected. Nothing is released, so no migration is
needed — but W1's gate asserts the geometry is unchanged, which is the part
that matters.

---

## 4. Not in this plan

Explicitly deferred, so nobody starts them by accident:

- **The HTTP service** — FastAPI, Postgres, Redis, MinIO, Compose, the VPS
  package. Design unchanged in
  [`docs/plan-archive-2026-07.md`](docs/plan-archive-2026-07.md) §6, §7, §13.
  It is a deployment topology for a builder that has to be good first.
- **OpenAI planner and MCP adapter.**
- **Rigging, animation, turntables.** `mesh.union: false` is the prerequisite
  for rigging, and this plan delivers that; the rig itself is later.
- **Texture painting and material libraries.** UVs (W3) come first.
- **3MF, USD, FBX export.**

---

## 5. Work packages

Dependency graph:

```
W1 ──► W2 ──► W3 ──► W4 ──► W5
                            
W6 (independent, needs a real machine)
W7 (independent)
W8, W9 (after W5)
```

---

### W1 — Build intent, optional print profile

**Depends on:** nothing. **Risk:** low. **Touches:**
`schemas/build-request-v1.schema.json`, `hbcb/spec.py`,
`hbcb/print_profiles.py`, `blender/generator.py`, `blender/qa.py`,
`blender/build.py`.

Make the printer optional without changing anything for existing requests.

1. Add `intent` to the request schema (`enum: ["print","digital"]`, default
   `"print"`).
2. `hbcb/spec.py`: expose `ResolvedRequest.intent`. Resolve `print_profile`
   only when `intent == "print"` **or** an explicit profile was supplied;
   otherwise set it to `None`. Add `ResolvedRequest.enforces_print`, true only
   for `intent == "print"`.
3. `blender/generator.py`: `_Builder._thicken` becomes a no-op returning its
   input when the profile is absent or `enforces_print` is false. Set
   `self.min_feature = self.min_radius = 0.0` when there is no profile.
   That is safe, and it is worth checking rather than trusting: those two
   attributes are read at **11 sites** outside `_thicken` (foot height, neck,
   eye, visor height and depth, ear, antenna ball, horn tip, tail radius, tail
   tip, backpack depth), and every one of them is a `max()` against a
   geometry-derived term such as `max(self.min_radius, self.head_w * 0.26)`.
   With zero, the geometric term simply wins. Do not substitute an arbitrary
   millimetre fallback — that would reintroduce print bias under another name.
4. `blender/qa.py`: `measure(obj, print_profile=None)`. Topology, volume,
   dimensions, and thickness are always measured. Overhang analysis needs a
   threshold — when there is no profile, report `steepest_overhang_deg` and
   `bed_contact_area_mm2` but leave `unsupported_area_mm2` null. Skip the mass
   estimate when there is no density. `evaluate(...)` marks
   `minimum_thickness` `required=False` whenever the profile is absent or
   intent is digital.
5. `qa-v1.schema.json`: the fields that can now be absent become nullable.
6. `blender/build.py`: pass the intent through; the QA summary must not
   crash on a null profile.

**Gate**

```sh
make test-unit && ./hbcb-cli selftest
./hbcb-cli build --preset facet-bot --no-renders -o /tmp/g1-print
./hbcb-cli verify /tmp/g1-print
```

Plus a new test asserting the geometry is unchanged for existing requests —
this is the whole point of the package:

```python
# tests/blender/test_intent.py
def test_default_intent_reproduces_the_shipped_geometry(self):
    """Adding `intent` must not move a single vertex for an existing request."""
    request = _request("facet-bot")            # no intent field
    self.assertEqual(request.intent, "print")
    model, report = generator.generate(...)
    self.assertEqual(_topology(model), EXPECTED_FACET_BOT_TOPOLOGY)
```

Passes when: unit + Blender suites green, `facet-bot` still produces 5054
triangles and a single watertight shell, and a `digital` request with no
`print_profile` builds without error.

---

### W2 — Digital output profile, no STL

**Depends on:** W1. **Risk:** low. **Touches:** `hbcb/layout.py`,
`schemas/build-request-v1.schema.json`, `blender/build.py`,
`blender/verify.py`.

1. Add `digital-v1` to the `output_profile` enum.
2. `layout.expected()` currently takes `(output_profile, render_profile)`.
   Give it the intent too, or resolve the effective profile before calling it —
   `intent: digital` with no explicit `output_profile` must select
   `digital-v1`. Prefer resolving in `hbcb/spec.py` so `layout` stays a pure
   function of its arguments.
3. `digital-v1` publishes `model.blend`, `model.glb`, `preview.png`,
   `diagnostics/*`, `qa.json`, `manifest.json`. **No `model.stl`.**
4. `blender/verify.py` must not fail on a missing STL — it already guards with
   `os.path.isfile`, so confirm rather than assume, and add the case to the
   verifier tests.

**Gate**

```sh
./hbcb-cli build --preset facet-bot --digital -o /tmp/g2-digital
test ! -e /tmp/g2-digital/model.stl && echo "no STL: correct"
./hbcb-cli verify /tmp/g2-digital
```

Passes when: verify exits 0 against a build with no STL, and
`layout.expected("digital-v1", ...)` is asserted in `tests/unit/`.

---

### W3 — Separate parts, smooth shading, UVs

**Depends on:** W2. **Risk:** medium — this is the substantive geometry work.
**Touches:** `blender/generator.py`, `blender/exporters.py`, `blender/qa.py`,
`schemas/`, `hbcb/spec.py`.

The union is currently unconditional in `generator.generate`:

```python
model = _union(parts, "character")
_orient_normals(model)
```

1. Add the `mesh` object to the request schema with the defaults in §3.
2. When `mesh.union` is false, skip `_union`. Return the part list in a named
   collection instead of one object. `generate()` returns a single object
   today — introduce a small result type carrying `objects`, `primary`, and
   the `Report`, and update `build.py`, `qa.py`, and `exporters.py` together.
   Do not special-case with `isinstance` checks scattered around.
3. Parts must keep meaningful names. `arm-l-shaft`, `arm-l-cap-top`,
   `arm-l-cap-bottom` are union operands, not a hierarchy a human wants. Join
   each logical part (arm, leg, head) into one object before returning, and
   parent them under an empty named after the character.
4. `shade_smooth`: set smooth shading with a sharp-edge angle around 30–40°
   so bevels stay crisp. Blender 4.1+ removed `use_auto_smooth`; use the
   "Smooth by Angle" modifier or set sharp edges directly, and put the version
   handling in `blender/compat.py` where the other renamed operators live.
5. `uv`: Smart UV Project per object. Bounded — cap the island margin and
   angle limit; never call an operator whose runtime scales with user input.
6. QA with `union: false`: `single_shell` **must not** fail. Expected shell
   count becomes the number of parts. Report `connected_shells` and
   `object_count`, and require `shells == objects` rather than `shells == 1`.
   Per-object watertightness is still checked — a non-manifold arm is a defect
   in any pipeline.
7. `exporters.export_stl` with separate parts: STL has no hierarchy. Either
   refuse (consistent with §3, since `union: false` + `print` is rejected) or
   join a temporary copy. Refusing is simpler and honest.

**Gate**

```sh
./hbcb-cli build --preset crystal-scout --digital -o /tmp/g3
python - <<'PY'
import json; m = json.load(open("/tmp/g3/manifest.json"))
assert m["model"]["object_count"] > 1, m["model"]
assert m["status"] == "succeeded"
print("objects:", m["model"]["object_count"])
PY
./hbcb-cli verify /tmp/g3
```

Passes when: the GLB re-imports with more than one mesh object, every object
is individually watertight, names are human-readable (`head`, `arm-l`, `base`
— not `arm-l-cap-top`), and `intent: print` still produces exactly one shell.

**Watch for:** the coplanarity rule in
[`CONTRIBUTING.md`](CONTRIBUTING.md) applies to the *union* path only. With
`union: false` the parts legitimately interpenetrate and that is fine — do not
"fix" it.

---

### W4 — CLI and presets

**Depends on:** W3. **Risk:** low. **Touches:** `hbcb/cli.py`,
`hbcb/presets.py`, `examples/`.

1. Flags: `--digital` (sets `intent`), `--print` (explicit opposite),
   `--union` / `--no-union`, `--smooth` / `--flat`, `--uv` / `--no-uv`.
   `--print-profile` implies `intent: print`.
2. `hbcb profiles` must say that profiles are optional and are ignored for
   digital builds. Right now its output implies a profile is always in play.
3. `hbcb doctor` and `hbcb build` output should name the intent, so a user
   never has to guess which mode they got.
4. Add one digital example: `examples/requests/facet-bot-digital.json`.
   `tests/unit/test_validation.py::test_examples_match_presets` asserts
   examples track presets — either add a matching preset or relax that test
   deliberately, with a comment.

**Gate**

```sh
./hbcb-cli build --preset cocoa-cub --digital --no-uv -o /tmp/g4 && \
./hbcb-cli validate examples/requests/facet-bot-digital.json && \
make test-unit
```

---

### W5 — Documentation

**Depends on:** W4. **Risk:** low. **Touches:** `README.md`,
`docs/character-spec.md`, `docs/architecture.md`, `CHANGELOG.md`.

The README currently opens on printing. It should open on "make a character",
then split into the two intents. Concretely:

- README: a "Digital or printable?" section immediately after the quickstart,
  with the §3 table. Remove the implication that a print profile is always
  required.
- `docs/character-spec.md`: document `intent` and `mesh`; mark the print
  profile section as applying to `intent: print`.
- `docs/architecture.md`: the "Why the boolean union" section is now
  conditional. Say when it applies and what happens when it does not.
- `CHANGELOG.md`: an `Added` entry for digital intent.

**Gate:** every command shown in the README runs successfully, checked by
hand. No automated gate — do not pretend otherwise.

---

### W6 — Close the unverified paths

**Depends on:** nothing. **Risk:** low, but **requires a machine this repo has
never run on.** Cannot be completed in a sandbox without Docker registry
access and a real Blender install.

From [`docs/REVIEW.md`](docs/REVIEW.md#verification-status):

1. `make docker-demo` — first real build of `docker/builder.Dockerfile`.
2. `hbcb doctor` and a full build on a machine with the **Blender
   application** installed, exercising the subprocess path in `hbcb/cli.py`:
   the flag set, the output filtering, and the `__HBCB_EXIT__` sentinel. The
   sentinel exists because Blender's handling of a script's `sys.exit` is
   inconsistent; confirm it or delete it.
3. macOS and Windows discovery paths in `hbcb/blender_finder.py`.

**Gate**

```sh
make docker-demo && ./hbcb-cli verify build/demo
# On a machine with the Blender application, not the bpy module:
./hbcb-cli doctor           # must report the executable, not the module
./hbcb-cli build --preset facet-bot -o /tmp/g6 -v
echo "exit=$?"              # must be 0
./hbcb-cli build --request examples/rejected/script-injection.json -o /tmp/g6b
echo "exit=$?"              # must be 3, proving the sentinel works
```

Update `docs/REVIEW.md` with the result either way. **If a path cannot be
tested, say so there — do not quietly drop the caveat.**

---

### W7 — Slicer-backed print QA

**Depends on:** nothing (independent of W1–W5). **Risk:** medium.
**Applies to:** `intent: print` only.

This is the highest-value remaining print work. Everything measured today is
geometric inference; a slicer is ground truth.

1. Add PrusaSlicer or CuraEngine CLI to `docker/builder.Dockerfile`.
2. New module `blender/slicer.py`, invoked only for `intent: print`, only when
   the binary exists. Absence is a skipped check, never a build failure — the
   native path must keep working without a slicer installed.
3. Parse and record: layer count, estimated print time, filament/resin volume,
   support volume, and any slicer warnings.
4. Extend `qa-v1.schema.json` with a nullable `slicer` block; extend
   `manifest.json`'s QA summary with estimated time and material.

**Gate**

```sh
make docker-build
docker run --rm --network none -v "$PWD/out:/output" hbcb:dev \
  build --preset facet-bot --no-renders -o /output
python -c "import json;q=json.load(open('out/qa.json'));print(q['slicer'])"
# On a host with no slicer: the same build must still succeed with slicer=null
./hbcb-cli build --preset facet-bot --no-renders -o /tmp/g7 && \
  python -c "import json;assert json.load(open('/tmp/g7/qa.json'))['slicer'] is None"
```

---

### W8 — A second generator

**Depends on:** W5. **Risk:** medium.

One generator cannot prove a schema is a contract. A second one — a modular
creature, a vehicle, a low-poly prop set — is what turns
`geometric-character@1.0.0` from "the code" into "an implementation".

Add it behind the existing `generator` enum, implementing
`generate(spec, print_profile) -> result` and honouring `intent` and `mesh`
from day one. If any part of `blender/build.py` needs to change to accommodate
it, that is the finding: the seam is in the wrong place, and fixing it is part
of this package.

**Gate:** both generators build under both intents, all four combinations
verify, and `blender/build.py` has no generator-specific branches.

---

### W9 — Physical print validation

**Depends on:** W7. **Risk:** none technically; needs a printer and time.

Print one `facet-bot` at 95 mm on FDM and one at 40 mm on resin. Measure
height, limb diameter, and base diameter with calipers. Record measured
against `manifest.json` in `docs/print-log.md`.

Until this is done, every print claim in this repository is an inference. This
is the package that changes "watertight and 1.2 mm minimum wall" from
plausible to evidenced. If the measurements disagree with the manifest, that
is a finding, and the thresholds in `hbcb/print_profiles.py` move.

---

## 6. Milestones

| Milestone | Packages | Means |
|---|---|---|
| **M1 — Digital models are first class** | W1–W5 | A user can generate a game-ready `.blend`/`.glb` with separate parts, smooth shading, and UVs, and is never blocked by a print check |
| **M2 — Claims are evidenced** | W6, W7 | The container and native Blender paths are proven; print QA is backed by a real slicer |
| **M3 — The architecture is proven** | W8, W9 | A second generator proves the seam; a physical print proves the numbers |

M1 is the release-worthy one. M2 and M3 remove the caveats currently in
`docs/REVIEW.md`.

---

## 7. Contract versioning

| Change | Version impact |
|---|---|
| Adding `intent`, `mesh` with defaults | Additive. `build/v1` unchanged. |
| Adding `digital-v1` to `output_profile` | Additive enum value. |
| `print_profile` nullable in the manifest | Additive. `manifest/v1` unchanged. |
| Nullable QA fields | Additive. `qa/v1` unchanged. |
| Removing a field or changing a default's meaning | **New schema version.** Not in this plan. |

Rule, unchanged from the original plan and still right: schemas, artifact
layout, exit codes, units, and hashes are versioned contracts. Change one and
you update the schema, the tests, and the docs in the same commit.

---

## 8. Risks

| Risk | Package | Mitigation |
|---|---|---|
| Making the print profile optional silently changes print geometry | W1 | The gate asserts `facet-bot` topology is byte-identical to today's |
| `None` profile crashes code that assumes a dict | W1 | `min_feature`/`min_radius` are read at **11 sites** beyond `_thicken`. Every one is a `max()` floor against a geometry-derived term, so setting both to `0.0` degrades correctly — see W1 step 3 |
| Non-union path produces junk hierarchies | W3 | Gate requires human-readable object names, not operand names |
| UV unwrap is slow or unbounded on dense meshes | W3 | Cap island margin and angle limit; measure runtime in the gate |
| `single_shell` check silently weakened for everyone | W3 | Keep it required for `intent: print`; assert both branches in tests |
| Slicer absence breaks the native path | W7 | Slicer is skipped-if-missing, never required |
| Scope creep back into the service | all | §4 |

---

## 9. Adopted defaults

Already decided. Do not stop to ask.

| Decision | Value |
|---|---|
| Default `intent` | `print` — preserves current behaviour for every existing request |
| Default `mesh.union` | `true` for print, `false` for digital |
| Default `mesh.shade_smooth` / `mesh.uv` | `false` for print, `true` for digital |
| `print_profile` with `intent: digital` | Allowed, advisory only, never constrains geometry |
| `mesh.union: false` with `intent: print` | Rejected at validation, exit code 3 |
| Digital default outputs | No STL |
| Request version | Stays `build/v1`; all changes additive |
| Slicer | Skipped when absent, never a hard dependency |
| Minimum Blender | 4.2, unchanged |
| `hbcb/` dependencies | Still zero. Non-negotiable — these modules run inside Blender's bundled Python |
| Licence | GPL-3.0-or-later, unchanged |

---

## 10. Definition of done for M1

- [ ] W1–W5 gates pass, with the commands and their output recorded.
- [ ] `make check` green.
- [ ] `intent: print` produces byte-identical geometry to the current release
      for all three presets — asserted by a test, not by inspection.
- [ ] A digital build with no `print_profile` produces a `.blend` and `.glb`
      with separate, human-readably named, individually watertight objects.
- [ ] No print check can fail a digital build.
- [ ] README, `docs/character-spec.md`, and `docs/architecture.md` describe
      both intents; no doc claims a print profile is mandatory.
- [ ] `CHANGELOG.md` updated.
- [ ] `docs/REVIEW.md`'s verification table updated — including anything that
      still could not be run.
