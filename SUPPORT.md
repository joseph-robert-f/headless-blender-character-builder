# Support

Maintainers try to give community support.
No response time is guaranteed.
The project has no hosted production service, paid support plan, or service-level agreement (SLA).

<a id="before-opening-an-issue"></a>
## Before you open an issue

1. Enter `./scripts/doctor` from the repository root.
   Use `--service` or `--native` for the applicable workflow.
2. Read the applicable procedure in [Installation](docs/installation.md).
   Read [Troubleshooting](docs/troubleshooting.md).
3. Examine [existing issues](https://github.com/joseph-robert-f/headless-blender-character-builder/issues) for the same error.
4. If possible, reproduce the problem with the supplied `facet-bot` request.
   This test helps identify a problem in the environment or in a custom character specification.

For local-service problems, use `make service-ps` and `make service-logs`.
Do not use raw Compose commands for these checks.
The wrappers select the project for the checkout and supply the necessary image provenance again.
They limit the output to the last 100 API lines and the last 100 worker lines.
If `python3` is older than 3.11, use the same explicit override as the command that gave the error.
For example, use `PYTHON=python3.11 make service-ps`.

Use the [GitHub issue chooser](https://github.com/joseph-robert-f/headless-blender-character-builder/issues/new/choose) for a defect without sensitive data or a feature proposal with specified limits.

## What to include

Include these data in the report:

- Source version, tag, or full commit SHA
- Operating system and CPU architecture
- Docker, Compose, Python, and Blender versions for the selected workflow
- `./scripts/doctor` output with sensitive data removed
- Command as entered, shell exit status, and smallest request that reproduces the problem
- For a Make target with an error, the preceding `HBCB_MAKE: FAIL[...]`, `BUILDER: FAIL[n]`, or `Error n` diagnostic
- Expected behavior and actual behavior
- Applicable `qa.json` or `manifest.json` fields
- If available, a short part of the log with sensitive data removed.

For the local service, identify the Compose project name.
Tell the maintainer if the checkout uses a generated `HBCB_COMPOSE_PROJECT_NAME` or the legacy `hbcb-local` identity.
Tell the maintainer if you selected nondefault `HBCB_API_HOST_PORT` or `HBCB_STORAGE_HOST_PORT` values.
Give only names and port numbers.
Do not include `.env` values.

Do not attach credentials, `.env` files, role-secret files, signed artifact URLs, private model references, or personal data.
Do not attach content that you do not have permission to supply to other persons.
Remove private hostnames and infrastructure identifiers.

## Security reports

Do not open a public issue for a suspected vulnerability.
Use the procedure in [SECURITY.md](SECURITY.md).
Use [GitHub private vulnerability reporting](https://github.com/joseph-robert-f/headless-blender-character-builder/security/advisories/new).

## Support boundary

| Scope | Paths |
|---|---|
| Community defect review with no response guarantee | Defects that can be reproduced in the source-built `linux/amd64` one-shot Docker builder and request/manifest contracts with specified limits |
| No response guarantee | Repository tests, Docker Desktop emulation on Apple Silicon, exact-Blender native contributor use, Linux `arm64` emulation, and project/release tools |
| Experimental defect review with no response guarantee | Local Compose service on loopback for one trusted operator |
| Experimental | Windows with WSL2 |
| Documentation review only | The VPS design and validation reference, which is not in the supported scope |
| Not in the supported scope | Internet-facing, hostile-input, hosted, multi-tenant, or VPS operation, arbitrary prompt-to-3D, custom commissions, private deployments, and unchecked third-party Blender files or scripts |

The v0.1 support boundary is for one trusted user.
This user controls the machine and makes or examines the JSON request before use.
The request must obey the specified limits.
The word "supported" identifies workflows that maintainers can examine from a reproduction.
It does not promise a response time, compatibility with each host, or production support.
Questions can help make the VPS reference better, but do not cause a commitment to operate a VPS.

Maintainers do not give these services or guarantees:

- Uptime guarantees
- Private deployment or incident response
- Emergency response
- Model-design commissions
- Intellectual-property clearance
- Slicer profiles or physical printing
- Print-success warranties.

Read [OUTPUT_POLICY.md](OUTPUT_POLICY.md) for output rights and the responsibilities for physical use.
