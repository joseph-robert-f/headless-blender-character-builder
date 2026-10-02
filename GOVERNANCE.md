<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Project governance

Maintainers control Headless Blender Character Builder v0.1.
The project has a small contributor community.
The governance model keeps the public contracts, Blender execution boundary, and release evidence in agreement.

## Roles

### Contributors

Anyone can report a problem that can be reproduced.
Anyone can propose an improvement with specified limits, examine changes, or send a pull request.
Each contribution must include Developer Certificate of Origin sign-off.
Read `CONTRIBUTING.md` for the procedure.

### Maintainers

Maintainers can examine issues, approve and merge changes, and manage labels and milestones.
They can make releases and apply project policies.
They are responsible for preservation of versioned contracts and their compatibility.
They must examine changes that have an effect on security and record important decisions.
`MAINTAINERS.md` identifies the current maintainers and their areas.
`.github/CODEOWNERS` identifies the reviewers.

### Security responders and release managers

Security responder and release manager are maintainer responsibilities.
`MAINTAINERS.md` can explicitly assign these responsibilities to other persons.
Security responders manage private vulnerability reports.
Release managers examine the release checklist, notices, SBOM, provenance, tests, and publication record.
These roles give no uptime or response-time guarantee.

## Decision process

1. Use reviewed pull requests and their attached evidence to make decisions on usual corrections and documentation changes.
2. For new interfaces or permissions, first prepare an issue that describes compatibility, tests, documentation, and security effects.
   This recommendation applies to schema fields, generators, profiles, output formats, API behavior, and deployment permissions.
3. Update `docs/threat-model.md` in the same pull request when a change increases the security scope.
   This requirement applies to accepted inputs, code execution, network access, credentials, file parsing, storage privileges, and public ingress.
4. Use a new versioned contract for a change that is not compatible with a public contract already in use.
   This includes a schema, artifact layout, exit code, hash, status mapping, or units.
   Do not change the meaning of a contract without a new version.
5. Get explicit lead-maintainer approval for license changes, contribution-attestation changes, or a substantial increase in v0.1 scope.
   Get this approval for a change that makes a security invariant weaker.
   Record the reason for each such change.
   Permission from all applicable copyright holders can also be necessary for a license change.

Before a merge, the project calls for one or more CODEOWNER/maintainer approvals and all required checks to pass.
While there is only one maintainer, that person can merge their own change after they record the necessary review data.
The record must include validation, security, and licensing information that lets a reviewer examine the change independently.
If practical, wait for review of a high-risk change by a person who works independently.
The temporary self-review exception ends when the one-review/no-bypass protection below becomes active.
Approval from a different reviewer is mandatory with that protection.

## Repository enforcement settings

Repository files specify policy and checks.
They cannot activate GitHub branch protection.
An administrator must apply these settings to `main` and examine them at intervals:

- Make a pull request and one approving review mandatory.
- Dismiss stale approvals.
  Make CODEOWNER review mandatory.
  Make approval by a different person mandatory for the most recent reviewable push.
- Make conversation resolution and a current branch mandatory.
- Make these specified checks mandatory: `DCO sign-off`, `source`, `builder`, and `service`.
- Apply the rules to administrators.
  Do not allow force pushes or deletion.
  Do not allow a user, team, or app to bypass the rules.
- Keep linear history optional because the project permits reviewed merge commits.
- DCO trailers and GitHub's cryptographic verified-signature feature are different.

The equivalent [GitHub branch-protection REST request](https://docs.github.com/en/rest/branches/branch-protection#update-branch-protection) body for `PUT /repos/{owner}/{repo}/branches/main/protection` is:

```json
{
  "required_status_checks": {
    "strict": true,
    "contexts": [],
    "checks": [
      {"context": "DCO sign-off"},
      {"context": "source"},
      {"context": "builder"},
      {"context": "service"}
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "require_last_push_approval": true,
    "required_approving_review_count": 1,
    "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []}
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
```

A personal account owns this repository.
Thus, the request does not include `dismissal_restrictions`.
GitHub documents user/team dismissal restrictions only for organizations.
`restrictions` stays `null` because personal repositories cannot configure user/team/app push restrictions.
The current request contract uses an empty legacy `contexts` list and the preferred `checks` array.

Before you apply that request, the `DCO sign-off` job must complete one time.
GitHub must show all four specified check names.
The one-review/no-bypass policy also makes a second trusted reviewer necessary.
The lead maintainer cannot approve their own pull request.
Fill that reviewer role before you apply the protection.
Do not report the protection as active before it is active.

Use `GET /repos/{owner}/{repo}/branches/main/protection` to examine the active configuration.
Do not record a planned setting as enforced evidence.

Maintainers can reject a change that is correct on its own.
Reasons include too much scope, problems with a public contract, or unsupported operating promises.
Tests and documentation that cannot be maintained are also a reason.

## Proposed issue labels

These labels are proposed for the public repository.
This list does not show that the labels are configured:

- `bug`, `enhancement`, `documentation`, `dependencies`, `security`
- `generator`, `component`, `exporter`, `qa`, `deployment`
- `contract-change`, `needs-triage`, `help wanted`, `good first issue`
- `post-v0.1`, `blocked`, and `needs-reproduction`.

Do not describe a security vulnerability in a public issue with these labels.
Use the procedure in `SECURITY.md`.

## Releases and support

- Use semantic versioning for the application.
  Use explicit different identifiers for schemas, generator versions, and profiles.
- Before a tag or package becomes a supported release, the release manager must complete the documented release gate.
  Use a clean publication tree.
  Keep the provenance and SBOM from that test.
- In published release notes, identify verified local gates independently from external operator actions.
  External actions include GitHub publication, image publication, DNS/TLS, and live VPS deployment.
- Maintainers try to give support with the limits in `SUPPORT.md`.
  Self-hosting operators are responsible for availability, backups, retention, abuse prevention, legal compliance, and print/manufacturing decisions.

## Conduct and enforcement

Maintainers apply `CODE_OF_CONDUCT.md`.
They can moderate participation or limit it in proportion to the problem.
The project recommends a private route for sensitive reports.
Do not publish private evidence.

<a id="changing-governance"></a>
## Change governance

Use the same public pull-request process for governance changes.
Get lead-maintainer approval.
The project recommends more governance rules as the maintainer group increases.
Recommended topics are nomination, removal, voting, inactivity, succession, and conflicts of interest.
The recommended time for these additions is before those processes become necessary.
