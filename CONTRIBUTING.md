# Contributing

Thank you for helping improve Headless Blender Character Builder. The v0.1
scope is intentionally narrow: bounded JSON recipes, one reviewed geometric
generator, deterministic artifact contracts, fail-closed geometry QA, a
loopback development service, and a production-oriented deployment reference.

Start with the [installation guide](docs/installation.md), then use the
[documentation index](docs/README.md) to find the area you are changing. You do
not need to read the complete historical plan to fix a focused bug or improve a
guide. Read [`PLAN.md`](PLAN.md), [`TEST_PLAN.md`](TEST_PLAN.md), and the
[progress log](docs/progress.md) when changing a public contract, security
boundary, release gate, or completed design decision.

## Development setup

Docker is the release-blocking path. From a source checkout:

```sh
./scripts/doctor
make release-static
make test-unit
```

`make test-unit` runs the root and separately packaged service tests in pinned
containers. A focused root-only host environment is also useful for quick
contract edits:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m unittest \
  tests.unit.test_request_contract \
  tests.contract.test_json_schemas -v
```

Do not run unrestricted `unittest discover -s tests` after installing only the
root project: service tests use the separate dependencies in
`service/pyproject.toml`. Use the Docker targets or deliberately install and
test both packages.

Native Blender 4.5.12 is a best-effort contributor convenience. Docker
`linux/amd64` is the authoritative compatibility and release path, including on
Apple Silicon.

## Choose the relevant checks

| Change | Minimum focused checks before review |
|---|---|
| Markdown, examples, or policy prose | `make release-static` and the documented command/link checks affected |
| Request/schema/model code | Focused unit/contract tests, `make test-unit`, and compatibility tests |
| Generator, export, render, or geometry QA | `make test-unit` and `make test-blender` |
| Builder image or launcher | `make test-unit`, `make test-blender`, and a fresh `make demo && make verify-demo` |
| API, worker, storage, or local Compose | `make test-unit`, `make service-smoke`, then `make service-down` |
| VPS, recovery, or operator tooling | `make g8-static` plus the affected deployment gate; full `make g8-gate` when Docker state is involved |
| Dependencies, CI, release, trust, or publication | `make dependency-check`, `make release-static`, and the complete `make release-check` on the intended clean index |

Run the smallest useful checks while iterating, then the full applicable row
before requesting review. Record exact commands and summarized results; never
claim a check that did not run.

## Before opening a change

- Open or reference an issue for new schema fields, generator components,
  deployment behavior, or security-boundary changes.
- Keep work inside the adopted v0.1 scope unless maintainers explicitly approve
  a separately versioned extension.
- Preserve backward meaning for schema IDs, profile names, artifact paths,
  units, hashes, statuses, and exit codes. Breaking contracts need a new version.
- Add or update tests and public documentation with behavior changes.
- Keep generated evidence in ignored test-output directories or release assets,
  not normal source commits.
- Never commit credentials, `.env`, signed URLs, generated Blender backups,
  large generated artifacts, private references, personal data, proprietary
  assets, or material you cannot redistribute.

## Developer Certificate of Origin

Contributions use [Developer Certificate of Origin
1.1](https://developercertificate.org/) sign-off rather than a Contributor
License Agreement. Every commit must include this trailer; `git commit -s` adds
it using your configured identity:

```text
Signed-off-by: Your Name <your-email@example.com>
```

By signing off, you certify that you have the right to submit the contribution
under the project's applicable license. Sign-off is not copyright assignment.
Do not submit code, artwork, model data, fonts, textures, references, or other
material that you do not have the right to contribute and redistribute.

## Security and contract review

Changes affecting request schemas, worker isolation, authentication, storage,
deployment, CI trust, or release behavior require focused maintainer review.
Any change that expands accepted inputs, process execution, network access,
credentials, file parsing, or permissions must update
[`docs/threat-model.md`](docs/threat-model.md) and corresponding tests.

Dependency changes follow the
[dependency-maintenance guide](docs/dependency-maintenance.md). Update
declarations, locks, hashes, reviewed licenses/notices, provenance, recovery
fixtures, and migration evidence as one coherent change; a version-discovery
report is not approval for an isolated pin bump.

Do not claim automatic IP clearance, guaranteed physical printing, or a safe
consumer product. The rights and output boundary is in
[`OUTPUT_POLICY.md`](OUTPUT_POLICY.md); governance and review rules are in
[`GOVERNANCE.md`](GOVERNANCE.md).
