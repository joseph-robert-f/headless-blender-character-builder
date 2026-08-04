<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Maintainers

The project is maintainer-led. This file is the public source of truth for
project roles; `.github/CODEOWNERS` routes review but does not grant or remove
maintainer authority by itself.

## Current maintainers

| GitHub account | Role | Areas |
|---|---|---|
| `@joseph-robert-f` | Lead maintainer, release manager, and initial security responder | Project scope, public contracts, worker boundary, deployment, licensing, governance, and releases |

This initial assignment matches the repository owner. GitHub permissions and
branch-protection settings remain the authoritative enforcement layer and must
be verified separately from this local file.

## Contact boundaries

- Reproducible non-sensitive bugs and proposals may use public issues.
- Suspected vulnerabilities must follow `SECURITY.md`. GitHub private
  vulnerability reporting is a remote repository setting and must be verified
  before reporters are directed to it.
- Never put credentials, private reference material, personal data, exploit
  details, or signed artifact URLs in a public issue.
- There is no guaranteed response time, production support, or emergency SLA.

## Maintainer expectations

Maintainers should:

- review DCO sign-off, tests, documentation, licensing, and provenance;
- protect the declarative-input and isolated-worker security boundary;
- distinguish v0.1 commitments from proposed post-v0.1 work;
- disclose conflicts relevant to a decision;
- use coordinated disclosure for vulnerabilities; and
- keep this file, `GOVERNANCE.md`, and CODEOWNERS aligned when roles change.

Adding or removing a maintainer requires a governance pull request approved by
the lead maintainer. Before the project has multiple maintainers, succession
or inactivity must be handled by an explicit public governance change rather
than inferred from repository activity.
