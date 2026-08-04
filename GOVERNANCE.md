<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Project governance

Headless Blender Character Builder v0.1 uses a maintainer-led governance
model. The goal is to keep the public contracts, Blender execution boundary,
and release evidence coherent while the contributor community is small.

## Roles

### Contributors

Anyone may report reproducible problems, propose bounded improvements, review
changes, or submit a pull request. Contributions require Developer Certificate
of Origin sign-off as described in `CONTRIBUTING.md`.

### Maintainers

Maintainers may triage issues, approve and merge changes, manage labels and
milestones, cut releases, and enforce project policies. They are responsible
for protecting versioned contracts, reviewing security-sensitive changes, and
recording material decisions. Current maintainers and areas are listed in
`MAINTAINERS.md`; review routing is encoded in `.github/CODEOWNERS`.

### Security responders and release managers

Security responder and release manager are maintainer responsibilities that
may be delegated explicitly in `MAINTAINERS.md`. Security responders coordinate
private vulnerability reports. Release managers verify the release checklist,
notices, SBOM, provenance, tests, and publication record. Neither role creates
an uptime or response-time guarantee.

## Decision process

1. Ordinary fixes and documentation changes are decided through reviewed pull
   requests and the evidence attached to them.
2. New schema fields, generators, profiles, output formats, API behavior, or
   deployment permissions should begin with an issue describing compatibility,
   tests, documentation, and security impact.
3. A change that expands accepted inputs, code execution, network access,
   credentials, file parsing, storage privileges, or public ingress must update
   `docs/threat-model.md` in the same pull request.
4. Breaking changes to a public schema, artifact layout, exit code, hash,
   status mapping, or units require a new versioned contract. An old contract
   must not silently acquire new meaning.
5. License changes, weakening a security invariant, changing contribution
   attestation, or materially expanding v0.1 scope require explicit approval
   from the lead maintainer and a recorded rationale. A license change may also
   require permission from all relevant copyright holders.

At least one CODEOWNER/maintainer approval and passing required checks are
expected before merge. While the project has only one maintainer, that
maintainer may merge their own change only after recording the validation and
security/licensing considerations that an independent reviewer would need.
High-risk changes should wait for independent review whenever practical.

Maintainers may decline a change that is correct in isolation but exceeds the
adopted scope, destabilizes a public contract, creates an unsupported operating
promise, or lacks maintainable tests and documentation.

## Proposed issue labels

The following are proposed taxonomy for the public repository; this document
does not assert that the labels have been created:

- `bug`, `enhancement`, `documentation`, `dependencies`, `security`;
- `generator`, `component`, `exporter`, `qa`, `deployment`;
- `contract-change`, `needs-triage`, `help wanted`, `good first issue`;
- `post-v0.1`, `blocked`, and `needs-reproduction`.

Security vulnerabilities must not be described in a public labeled issue.
Follow `SECURITY.md` instead.

## Releases and support

- Releases follow semantic versioning for the application and explicit
  independent identifiers for schemas, generator versions, and profiles.
- A tag or package is not a supported release until the release manager has
  run the documented release gate from a clean publication tree and retained
  the resulting provenance and SBOM.
- Published release notes must distinguish verified local gates from external
  operator actions such as GitHub publication, image publication, DNS/TLS, or
  live VPS deployment.
- Support is best effort and bounded by `SUPPORT.md`. Self-hosting operators
  own availability, backups, retention, abuse prevention, legal compliance,
  and print/manufacturing decisions.

## Conduct and enforcement

Maintainers enforce `CODE_OF_CONDUCT.md` and may moderate or restrict
participation proportionately. Sensitive reports should use a private route;
do not post private evidence publicly.

## Changing governance

Governance changes use the same public pull-request process and require lead
maintainer approval. As the maintainer group grows, this file should be updated
with nomination, removal, voting, inactivity, succession, and conflict-of-
interest rules before those processes are needed.
