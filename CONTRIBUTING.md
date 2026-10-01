# Contributing

Headless Blender Character Builder has a small v0.1 scope:

- JSON recipes with fixed limits
- One reviewed geometric generator
- Deterministic artifact contracts
- Geometry QA that rejects failures and unknown results
- A trusted-user one-shot Docker builder
- An experimental loopback service
- A VPS design reference that is not in v0.1 support.

Tests for an experimental or future feature do not add it to v0.1 support.

Read the [installation guide](docs/installation.md) first.
Use the [documentation index](docs/README.md) to find the area that you will change.
The full historical plan is not necessary for a small bug fix or guide correction.
For public-contract, security-boundary, release-gate, or adopted-decision changes, read the documents below:

- [`PLAN.md`](PLAN.md)
- [`TEST_PLAN.md`](TEST_PLAN.md)
- [Progress log](docs/progress.md).

## Development setup

Docker tests must pass before release.
For a code change, use this initial test during development:

```sh
./scripts/doctor
make test-unit
```

For a prose-only change, run `./scripts/doctor`.
Then use the Markdown and policy row in the test matrix below.
Large Docker unit-test images are not necessary for prose corrections.
Each change must pass applicable focused checks and a last staged `make release-static` review.

Contributor and release tools use Python 3.11+.
If `python3` is earlier than 3.11, install a current Python version.
Some macOS system Python versions have this limit.
Select the installed version for Make commands:

```sh
export PYTHON=python3.11
"$PYTHON" --version
```

`make release-static` audits the Git index, not unstaged working-tree files.
Before this check, examine the intended files.
Stage only those files.
Then examine the staged snapshot:

```sh
git diff --check
git diff --cached --check
git add path/to/reviewed-file
git diff --cached
make release-static
```

After more changes, repeat `git add` and the staged diff inspection.
Do not use `git add -A` without file inspection.
The checkout can contain generated or unrelated files.

`make test-unit` runs the root tests and service tests independently in pinned containers.
For fast contract checks on the host, you can use this root-only environment:

```sh
PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m unittest \
  tests.unit.test_request_contract \
  tests.contract.test_json_schemas -v
```

Do not run unrestricted `unittest discover -s tests` with only the root project installed.
Service tests use the dependencies in `service/pyproject.toml`.
Use the Docker targets, or install and test each package explicitly.

Native Blender 4.5.12 is a best-effort option for contributors.
Docker `linux/amd64` is the authoritative compatibility and release workflow.
This also applies to Apple Silicon.

<a id="choose-the-relevant-checks"></a>
## Choose the applicable checks

| Change | Minimum focused checks before review |
|---|---|
| Markdown, examples, or policy prose | Command and link checks, `./scripts/check-documentation-language`, and `make release-static` on the reviewed staged snapshot |
| Request, schema, or model code | Focused unit and contract tests, `make test-unit`, and compatibility tests |
| Generator, export, render, or geometry QA | `make test-unit` and `make test-blender` |
| Builder image or launcher | `make test-unit`, `make test-blender`, and a new `make demo && make verify-demo` |
| API, worker, storage, or local Compose | `make test-unit`, `make service-smoke`, then `make service-down` |
| Artifact lifecycle, maintenance deletion, or versioned storage | Service checks and `make orphan-minio-check`. This test uses a random internal disposable project. It must remove that project's volumes before exit. |
| VPS, recovery, or operator tools | `make g8-static` and the affected deployment test. Use full `make g8-gate` if the change affects Docker state. |
| Dependencies, CI, release, trust, or publication | `make dependency-check`, `make release-static`, and full `HBCB_RELEASE_RUN_ID=<unique-safe-id> make release-check` on the intended clean index |

During development, run the smallest useful checks.
Before a review request, run the full applicable set.
Record the commands without changes and summarize their results.
Do not claim a check that did not run.

For prose, use [Documentation language](docs/documentation-language.md).
The language checker finds only selected problems.
A pass is not ASD-STE100 certification.
A human must examine vocabulary, meaning, technical terms, and safety instructions.

## Submit a pull request

1. If you do not have branch access, fork the repository.
2. Clone the fork or repository.
3. Make a branch from current `main` for the change.
4. Make the change.
5. Run the applicable checks above.
6. Examine `git diff` and the files that you intend to stage.
7. Stage only those files.
8. Examine `git diff --cached`.
9. Run `make release-static` on that staged snapshot.
10. Commit with DCO sign-off, for example, `git commit -s -m "Describe the focused change"`.
11. Push the branch.
12. Open a pull request against `main`.
13. Complete the template with the checks that ran.
14. Identify tests that did not run and any blockers.
15. Wait for mandatory CI and review.

Do not bypass a failed check to merge a change.
If you update the branch after review, repeat the applicable checks and staged diff inspection.
Do not add generated evidence, secrets, or unrelated workspace files to make the working tree clean.

## Before opening a change

- Open or reference an issue for new schema fields, generator components, deployment behavior, or security-boundary changes.
- Keep work in the adopted v0.1 scope unless maintainers approve an independently versioned extension.
- Keep the meaning of schema IDs, profile names, artifact paths, units, hashes, statuses, and exit codes.
- Use a new version for a contract change that is not backward compatible.
- Update tests and public documentation when behavior changes.
- Keep generated evidence in ignored test-output directories or release assets.
- Do not put generated evidence in ordinary source commits.
- Do not commit credentials, `.env`, signed URLs, Blender backups, large generated artifacts, private references, personal data, or proprietary assets.
- Do not commit material that you cannot redistribute.

## Developer Certificate of Origin

Contributions use [Developer Certificate of Origin 1.1](https://developercertificate.org/) sign-off, not a Contributor License Agreement.
Each commit must include this trailer.
`git commit -s` adds it with your configured identity:

```text
Signed-off-by: Your Name <your-email@example.com>
```

The value must match the commit author or committer identity without changes.
The name and email spelling must agree.

Use the key `Signed-off-by`.
Put the line in Git's terminal trailer block, not in the message body.
Each commit unique to the pull-request head must have one or more matching trailers.
This also applies to merge commits.
A pull-request description or subsequent aggregate sign-off does not replace a commit trailer.

After you fetch the target branch, run the same check locally:

```sh
dco_base=$(git merge-base origin/main HEAD)
dco_head=$(git rev-parse HEAD)
./scripts/dco-check "$dco_base" "$dco_head"
```

The checker accepts only lowercase 40-character commit IDs.
It examines a maximum of 500 commits and rejects commit objects larger than 1 MiB.
It does not fetch a remote.
For a sign-off failure, it reports only a commit ID with a fixed length limit.

If the last commit is incorrect, examine it.
Then run `git commit --amend --signoff`.
Before a history change on a shared branch, coordinate with its contributors.

DCO sign-off certifies that you have the right to submit the contribution under the applicable project license.
It is not copyright assignment.
Do not submit code, artwork, model data, fonts, textures, references, or other material without contribution and redistribution rights.

## Security and contract review

Maintainers must examine changes to request schemas, worker isolation, authentication, storage, deployment, CI trust, or release behavior.
For changes that expand inputs, execution, networks, credentials, file parsing, or permissions, update [`docs/threat-model.md`](docs/threat-model.md).
Update the related tests.

Use the [dependency-maintenance guide](docs/dependency-maintenance.md) for dependency changes.
Update declarations, locks, hashes, reviewed licenses, notices, provenance, recovery fixtures, and migration evidence together.
A version-discovery report does not give approval for a pin-only update.

Do not claim automatic IP clearance, guaranteed physical printing, or a safe consumer product.
Read [`OUTPUT_POLICY.md`](OUTPUT_POLICY.md) for rights and output limits.
Read [`GOVERNANCE.md`](GOVERNANCE.md) for governance and review rules.
