# Contributing

This project is currently at the planning/prototype stage. Please read `PLAN.md` and `TEST_PLAN.md` before proposing implementation work.

## Before opening a change

- Open or reference an issue for new schema fields, generator components, deployment behavior, or security-boundary changes.
- Keep changes inside the adopted v0.1 scope unless maintainers explicitly approve an extension.
- Never commit credentials, `.env`, generated Blender backups, large generated artifacts, proprietary references, or material you are not permitted to redistribute.
- Add or update tests and documentation whenever a versioned contract changes.

## Contributions

Contributions use Developer Certificate of Origin sign-off. Add the following to each commit with `git commit -s`:

```text
Signed-off-by: Your Name <your-email@example.com>
```

By signing off, you certify that you have the right to submit the contribution under the project's license.

## Review expectations

Changes affecting request schemas, worker isolation, authentication, storage, deployment, or release workflows require focused maintainer review and a threat-model note. Generated evidence belongs in ignored test-output directories or release assets rather than normal source commits.
