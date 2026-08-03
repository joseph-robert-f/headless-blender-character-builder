# Contributing

Thanks for taking a look. Read [docs/architecture.md](docs/architecture.md)
before a first change — it explains the two constraints that are easy to
violate by accident.

## Getting set up

```sh
git clone https://github.com/joseph-robert-f/headless-blender-character-builder.git
cd headless-blender-character-builder
./hbcb-cli doctor
```

If you do not have Blender installed, `pip install -e ".[bundled-blender]"`
gets you a working one. `pip install -e ".[dev]"` adds `ruff` and `jsonschema`.

```sh
make test-unit      # <1s, no Blender needed
make test-blender   # ~45s, needs Blender
make check          # everything CI runs
```

## Two rules that are not negotiable

**`hbcb/` imports nothing outside the standard library.** These modules run
inside Blender's bundled Python, which cannot install packages and which users
must not be asked to modify. A third-party import here breaks the native path
for everyone. That constraint is why the schema validator is hand-written.

**Never let two surfaces be tangent or coplanar in the generator.** The boolean
union turns tangent surfaces into rings of zero-area faces, and Blender's STL
importer strips those, leaving holes in the exported mesh. Overlap parts
properly; do not have them touch. If you are adding a primitive, look at how
`capsule` in `blender/primitives.py` offsets and shrinks its caps, and why.

Relatedly: do not "clean up" a boolean result with merge-by-distance. It has
been measured across a range of thresholds and it tears the manifold every
time. See [docs/REVIEW.md](docs/REVIEW.md).

## Changing a contract

Schemas, artifact layout, exit codes, units, and hashes are versioned
contracts. If you change one, update the schema, the tests, and the docs in the
same commit. Additive changes need a new enum value and a contract test;
breaking changes need a new schema version.

## Adding things

- **A generator** implements `generate(spec, print_profile) -> (object,
  Report)` and adds itself to the `generator` enum. This is the most useful
  contribution available — a second generator is what proves the schema is a
  real contract.
- **A print check** adds a measurement in `qa.py:measure` and a check in
  `qa.py:evaluate`. Mark it `required=False` unless it identifies a defect in
  the geometry rather than a property of the print setup. Overhangs, for
  instance, are printable with supports and so are a warning.
- **An export format** needs a re-import check in `verify.py` in the same
  change. An export nobody re-reads is an export nobody knows is broken.
- **A print profile** goes in `hbcb/print_profiles.py` and must pass the
  coherence rules. Say where the numbers came from.

## Tests

Anything that can be tested without Blender should be, in `tests/unit/` — that
suite is the fast feedback loop and runs on every push across three Python
versions. Geometry claims belong in `tests/blender/`, and should assert on
measurements rather than on golden files.

If you are fixing a geometry bug, add the assertion that would have caught it.
The verifier exists because a mesh can be watertight in memory and not
watertight as a file; that class of bug does not show up in the scene that
produced it.

## Style

`ruff check` and `ruff format` are enforced by CI. The codebase uses
`%`-formatting consistently — please match it rather than mixing in f-strings.

Comments should explain why, not what. Several non-obvious decisions here are
load-bearing (the millimetre unit and its consequences for glTF and for Cycles
lighting; the 1st-percentile thickness check; leaving boolean topology alone),
and each is commented where it happens. If you change one of those, update the
comment.

## Before opening a pull request

- Open or reference an issue for schema fields, new components, or anything
  touching the security boundary.
- Never commit credentials, `.env`, generated models, renders, or material you
  do not have the rights to redistribute.
- Sign off your commits: `git commit -s`, certifying the
  [Developer Certificate of Origin](https://developercertificate.org/).

```text
Signed-off-by: Your Name <your-email@example.com>
```

## Review expectations

Changes to request schemas, the generator's geometry rules, worker isolation,
or the release workflow get focused review and a note on what you did to
convince yourself it is correct. For geometry, "the render looks right" is not
that note — the STL re-import check is.
