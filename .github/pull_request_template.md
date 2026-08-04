<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

## Summary

<!-- What changes, and what user or maintainer problem does it solve? -->

## Scope

<!-- Link the issue/design discussion. State whether this is v0.1 scope or post-v0.1. -->

## Security and contract impact

<!--
Does this change accepted inputs, schemas, generator/profile versions, paths,
process execution, network access, credentials, IAM, persistence, artifact
publication, CI trust, or the worker boundary? If yes, explain and update
docs/threat-model.md plus tests. Breaking public-contract changes require a new
version identifier.
-->

## Verification

<!-- List exact commands and summarized results. Do not claim checks not run. -->

```text
command:
result:
```

## Contributor checklist

- [ ] Every commit has a DCO `Signed-off-by` trailer (`git commit -s`).
- [ ] The change stays within the documented v0.1 scope, or is clearly marked
      and isolated as post-v0.1.
- [ ] Tests and documentation cover changed behavior and versioned contracts.
- [ ] I did not add credentials, `.env`, signed URLs, private data, proprietary
      references, generated backups, or large generated artifacts.
- [ ] Any character, asset, texture, font, logo, or reference I added is
      original or rights-cleared, with its source/license recorded.
- [ ] The public interface still rejects arbitrary Python, Blender commands,
      add-ons, host paths, remote URLs, and uploaded `.blend` files unless this
      pull request explicitly proposes and reviews a new security boundary.
- [ ] Documentation and UI claims do not promise legal clearance or a
      successful/safe physical print.
- [ ] Dependency changes update locks, checksums, notices, SBOM expectations,
      and license/security review as applicable.

## Screenshots or artifact evidence

<!-- Optional. Use sanitized evidence; never attach private references or URLs. -->
