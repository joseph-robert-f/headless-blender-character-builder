# v0.1 Build Progress

Last updated: 2026-08-02

Overall status: **in progress**

| Work package | Milestone | Status | Gate evidence |
|---|---|---|---|
| G0 | M0 foundation | passed | Baseline verified; defaults, neutral brief, ignores, preservation hashes, and intentional indexed source set audited |
| G1 | M1 contracts | pending | — |
| G2 | M1 generator | pending | — |
| G3 | M1 artifacts and QA | pending | — |
| G4 | M2 one-shot container | pending | — |
| G5 | M3 persistence interfaces | pending | — |
| G6 | M3 API and worker | pending | — |
| G7 | M3 Compose service | pending | — |
| G8 | M4 VPS package | pending | — |
| G9 | M5 release candidate | pending | — |

## Evidence log

### G0 — baseline and foundation

Files and contracts introduced:

- `docs/inventory.md` preserves file hashes, sizes, reusable-code notes, and baseline verification;
- `docs/decisions.md` records Section 17 defaults and execution conditions;
- `docs/facet-bot-brief.md` defines the neutral original example;
- this file establishes the package-by-package gate log.

Verification executed:

| Command | Result |
|---|---|
| Native Blender 4.5.12 fresh reload of `codex_self_portrait.blend` with `verify_codex_avatar.py` | exit `0`; `CODEX_AVATAR_VERIFICATION: PASS` |
| Native Blender 4.5.12 fresh reload of `codex_self_portrait_turntable.blend` with `verify_turntable_animation.py` | exit `0`; `TURN_TABLE_VERIFICATION: PASS` |
| SHA-256 and byte inventory of baseline scripts/models/renders | exit `0`; recorded in `docs/inventory.md` |

Evidence locations:

- ignored baseline artifacts remain in the workspace root;
- temporary smoke/audit renders were written under the operating-system temporary directory;
- source inventory and hashes are durable in `docs/inventory.md`.

Deviation/condition:

- A public `origin` was explicitly authorized and configured before this build goal; see the recorded execution conditions in `docs/decisions.md`. No new remote publication is authorized by this goal.

Gate verification:

| Command | Result |
|---|---|
| `git diff --cached --check` | exit `0` |
| `git ls-files` publication-source inventory | exit `0`; 16 intended text/policy files, no generated model/media or backup |
| `git check-ignore -v` against preserved scripts/models/renders/research | exit `0`; every baseline input remains ignored |
| tracked/intended-source credential and personal-path scan | exit `0`; only the documented regex example matched |
| Markdown fence-count audit | exit `0`; every nonzero count is even |
| baseline SHA-256 recheck | exit `0`; all 16 recorded source/artifact hashes unchanged |

G0 gate result: **passed**. G1 contract implementation may begin.
