# Contributing

This project is a v0.1 release candidate with a deliberately narrow supported
scope. Start with the [documentation index](docs/README.md), then review
`PLAN.md`, `TEST_PLAN.md`, and `docs/progress.md` before proposing contract,
generator, service, deployment, or security-boundary work.

## Before opening a change

- Open or reference an issue for new schema fields, generator components, deployment behavior, or security-boundary changes.
- Keep changes inside the adopted v0.1 scope unless maintainers explicitly approve an extension.
- Never commit credentials, `.env`, generated Blender backups, large generated artifacts, proprietary references, or material you are not permitted to redistribute.
- Add or update tests and documentation whenever a versioned contract changes.

## Contributions

Contributions use [Developer Certificate of Origin
1.1](https://developercertificate.org/) sign-off rather than a Contributor
License Agreement. Every commit must include the following trailer; `git
commit -s` adds it using your configured identity:

```text
Signed-off-by: Your Name <your-email@example.com>
```

By signing off, you certify that you have the right to submit the contribution
under the project's applicable license. Sign-off is not copyright assignment.
Do not submit code, artwork, model data, fonts, textures, references, or other
material that you do not have the right to contribute and redistribute.

## Review expectations

Changes affecting request schemas, worker isolation, authentication, storage,
deployment, CI trust, or release behavior require focused maintainer review.
Any change that expands accepted inputs, process execution, network access,
credentials, file parsing, or permissions must update `docs/threat-model.md`
and the corresponding tests. Generated evidence belongs in ignored
test-output directories or release assets rather than normal source commits.

Dependency changes follow
[`docs/dependency-maintenance.md`](docs/dependency-maintenance.md). Update the
declaration, hashes, reviewed licenses/notices, provenance, recovery fixtures,
and migration evidence as one coherent change; a version-discovery report is
not approval to merge an isolated pin bump.

Do not add claims of automatic IP clearance or guaranteed physical printing.
The required output and rights boundary is documented in `OUTPUT_POLICY.md`;
governance and review rules are in `GOVERNANCE.md`.
