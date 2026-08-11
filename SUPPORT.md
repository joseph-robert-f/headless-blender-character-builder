# Support

Community support is best effort. There is no hosted production service, paid
support plan, or SLA.

## Before opening an issue

1. Run `./scripts/doctor` from the repository root. Use `--service` or
   `--native` for those paths.
2. Follow the relevant section of [Installation](docs/installation.md) and
   review [Troubleshooting](docs/troubleshooting.md).
3. Search [existing issues](https://github.com/joseph-robert-f/headless-blender-character-builder/issues)
   for the same failure.
4. Reproduce with the bundled `facet-bot` request when possible. This helps
   separate environment problems from a custom character specification.

For a non-sensitive defect or bounded feature proposal, use the
[GitHub issue chooser](https://github.com/joseph-robert-f/headless-blender-character-builder/issues/new/choose).

## What to include

- source version, tag, or full commit SHA;
- operating system and CPU architecture;
- Docker, Compose, Python, and Blender versions relevant to the selected path;
- sanitized `./scripts/doctor` output;
- the exact command, exit code, and smallest reproducible request;
- expected behavior and actual behavior; and
- relevant `qa.json` or `manifest.json` fields and a short sanitized log
  excerpt when available.

Do not attach credentials, `.env` files, role-secret files, signed artifact
URLs, private model references, personal data, or content you cannot
redistribute. Redact private hostnames and infrastructure identifiers.

## Security reports

Do not open a public issue for a suspected vulnerability. Follow
[SECURITY.md](SECURITY.md) and use
[GitHub private vulnerability reporting](https://github.com/joseph-robert-f/headless-blender-character-builder/security/advisories/new).

## Support boundary

| Scope | Paths |
|---|---|
| Supported for best-effort community issue triage | Reproducible defects in the source-built `linux/amd64` one-shot Docker builder, bounded request/manifest contracts, local Compose service, and repository tests |
| Best effort | Docker Desktop emulation on Apple Silicon, exact-Blender native contributor use, Linux `arm64` emulation, and project/release tooling questions |
| Experimental | Windows with WSL2 |
| Documentation review only | The production-oriented VPS reference until a matching source release, image set, and digest lock are published |
| Out of scope | A hosted or multi-tenant service, arbitrary prompt-to-3D, custom commissions, private deployment operations, and unreviewed third-party Blender files or scripts |

“Supported” here identifies the paths maintainers can triage from a
reproduction; it does not promise response time, compatibility with every host,
or production support. Questions can improve the VPS reference, but they do not
create an operational commitment.

Maintainers do not provide uptime guarantees, private deployment or incident
response, emergency response, model-design commissions, intellectual-property
clearance, slicer profiles, physical printing, or print-success warranties.
See [OUTPUT_POLICY.md](OUTPUT_POLICY.md) for output, rights, and physical-use
responsibilities.
