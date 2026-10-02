<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

## Summary

<!-- Describe the change and the user or maintainer problem that it solves. -->

## Scope

<!-- Link the issue or design discussion. State if the change is in v0.1 scope or a future extension. -->

## Security and contract impact

<!--
Identify changes to accepted inputs, schemas, generator versions, profile versions,
paths, execution, networks, credentials, IAM, storage, publication, CI trust, or worker isolation.
If a boundary changes, update docs/threat-model.md and the related tests.
A public-contract change that is not backward compatible needs a new version identifier.
-->

## Verification

<!-- List the commands without changes. Summarize their results. Identify checks that did not run. -->

```text
command:
result:
```

## Contributor checklist

- [ ] Each commit has a DCO `Signed-off-by` trailer (`git commit -s`).
- [ ] The change is in documented v0.1 scope, or it is an identified and isolated future extension.
- [ ] Tests and documentation include the changed behavior and versioned contracts.
- [ ] I did not add credentials, `.env`, signed URLs, private data, proprietary references, generated backups, or large generated artifacts.
- [ ] I have contribution rights for each added character, asset, texture, font, logo, and reference. I recorded the source and license.
- [ ] The public interface rejects arbitrary Python, Blender commands, add-ons, host paths, remote URLs, and uploaded `.blend` files.
      If this pull request changes that boundary, it includes an explicit proposal and review.
- [ ] Documentation and UI claims do not promise legal clearance or physical-print success or safety.
- [ ] Dependency changes update applicable locks, checksums, notices, SBOM expectations, and license and security assessments.
- [ ] I examined maintained prose against the documentation-language guide. A heuristic pass alone does not establish ASD-STE100 conformity.

## Screenshots or artifact evidence

<!-- This section is optional. Remove sensitive data from evidence. Do not attach private references or URLs. -->
