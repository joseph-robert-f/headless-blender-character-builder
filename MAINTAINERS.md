<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Maintainers

Maintainers control the project.
This file is the public record of project roles.
`.github/CODEOWNERS` identifies the reviewers.
That file does not give or remove maintainer authority.

## Current maintainers

| GitHub account | Role | Areas |
|---|---|---|
| `@joseph-robert-f` | Lead maintainer, release manager, and initial security responder | Project scope, public contracts, worker boundary, deployment, licensing, governance, and releases |

This initial role assignment uses the repository owner.
GitHub permissions and branch-protection settings control access and enforcement.
Examine those settings independently.
This local file does not prove their current values.

## Contact boundaries

- Use public issues for problems that can be reproduced and proposals without sensitive data.
- For a suspected vulnerability, use the procedure in `SECURITY.md`.
- Before you recommend GitHub private vulnerability reporting to a reporter, make sure that the remote repository setting is enabled.
- Do not put credentials, private references, personal data, exploit details, or signed artifact URLs in a public issue.

There is no guaranteed response time, production support, or emergency service-level agreement (SLA).

## Maintainer expectations

These tasks are recommended for maintainers:

- Examine DCO sign-off, tests, documentation, licensing, and provenance
- Prevent changes that weaken the security boundary for declarative input and the isolated worker
- Identify v0.1 commitments independently from proposed work after v0.1
- Declare conflicts that have an effect on a decision
- Use coordinated disclosure for vulnerabilities
- Keep this file, `GOVERNANCE.md`, and CODEOWNERS in agreement when roles change.

To add or remove a maintainer, use a governance pull request with lead-maintainer approval.
While there is only one maintainer, use an explicit public governance change to manage succession or inactivity.
Do not infer these changes from repository operations.
