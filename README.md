# Headless Blender Character Builder

An open-source, self-hostable pipeline for turning a bounded JSON character request into real Blender geometry, portable 3D exports, diagnostic renders, and machine-readable QA.

> **Status: contract layer implemented; generator pending.** The strict v0.1 request, QA, and manifest contracts are tested. The generic Blender generator, Docker quickstart, API, Compose service, and VPS package described below are not implemented yet. Do not treat this repository as production-ready or advertise `make demo` as available until its milestone gate passes.

The planned public contract is deliberately narrow: original geometric, low-poly, or chibi characters compiled from reviewed Blender primitives—not unrestricted text-to-3D, customer-authored Python, exact likenesses, protected-character replication, or guaranteed physical prints.

## Start here

- [PLAN.md](PLAN.md) is the authoritative product scope and implementation sequence.
- [TEST_PLAN.md](TEST_PLAN.md) explains how an owner or reviewer will prove each feature and records what input is still needed.
- [docs/character-spec.md](docs/character-spec.md) documents the implemented bounded JSON contracts and test command.
- [SECURITY.md](SECURITY.md) describes the current security status and reporting path.
- [CONTRIBUTING.md](CONTRIBUTING.md) explains how to propose changes safely.

## Intended v0.1 experience

The primary quickstart will be synchronous, keyless, and single-container:

```sh
make demo
make verify-demo
```

That path will require Git, Docker, and Make, but no Compose stack, `.env`, third-party account, API key, or host Blender installation. These commands are a target contract and will be marked runnable only after work package G4 in `PLAN.md` passes.

The secondary path will add an asynchronous self-hosted service through Docker Compose. OpenAI planning and MCP support remain optional post-v0.1 adapters and will never be required by the deterministic Blender builder.

## Repository state

The repository now contains four Draft 2020-12 schemas, pure-standard-library runtime validation/canonicalization, two original example requests, hostile rejection fixtures, and schema/policy tests. The local research workspace also contains a hardcoded Blender proof-of-concept, but it remains excluded from publication because it is branded, writes generated files beside source, and some generated assets contain local filesystem metadata. Reusable geometry code will be generalized through the remaining G2–G4 gates.

## Safety and limitations

- The normal worker will accept declarative, schema-validated requests only. Arbitrary Python, Blender flags, add-ons, remote URLs, and host paths are out of scope.
- Geometry checks and later slicer checks are diagnostic evidence, not a warranty that a model will print safely or successfully.
- Users remain responsible for rights to names, designs, references, logos, and generated outputs. The project grants no rights to third-party characters or brands.
- No currently published release is supported for production use.

## License

Project source is licensed under GPL-3.0-or-later. Original sample assets will use the separate policy in [ASSET_LICENSE.md](ASSET_LICENSE.md). No sample model or render is included in the initial planning commit.
