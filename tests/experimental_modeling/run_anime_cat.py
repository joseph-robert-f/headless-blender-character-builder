# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the reviewed three-stage cat fixture through the experimental controller.

This is a deterministic local fixture, not a model-provider request. Native mode
requires an explicit reviewed-source opt-in; Docker mode uses an explicit image.
All Blender products and evidence are written to a new external store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experimental_modeling.controller import build
from experimental_modeling.contracts import read_json
from verify_anime_cat import fingerprints, verify

FIXTURE = ROOT / "experimental_modeling" / "examples" / "anime_cat"
INTENTS = (
    "Create a cute, anime-styled 3D cat.",
    "Add a hat to the same cat.",
    "Remove the hat and add sunglasses to the same cat.",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checkout_head() -> str | None:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    value = process.stdout.strip()
    return value if process.returncode == 0 and len(value) == 40 else None


def _checkout_tree() -> str | None:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    value = process.stdout.strip()
    return value if process.returncode == 0 and len(value) == 40 else None


def _checkout_dirty() -> bool | None:
    process = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return bool(process.stdout) if process.returncode == 0 else None


def _assert_accepted(result: dict) -> None:
    assert result["status"] == "accepted", json.dumps(
        {key: result.get(key) for key in ("revision", "status", "error", "failures", "jobs")}, indent=2
    )
    assert all(result["jobs"][job]["exit_code"] == 0 for job in ("author", "inspect", "roundtrip", "reopen"))


def run(
    store: Path, *, trusted_reviewed_source: bool = False,
    sandbox_image: str | None = None, blender: str = "blender",
) -> dict:
    if trusted_reviewed_source == bool(sandbox_image):
        raise ValueError("Select exactly one reviewed native or explicit sandbox mode")
    store = Path(store).absolute()
    if store.exists() and any(store.iterdir()):
        raise ValueError("Use a fresh empty store")
    for revision in ("r0", "r1", "r2", "bad"):
        for path in (FIXTURE / "params" / f"{revision}.json", FIXTURE / "policies" / f"{revision}.policy.json"):
            if not path.is_file():
                raise FileNotFoundError(path)

    primary = store / "primary"
    observations: list[dict] = []
    results: list[dict] = []
    for i, intent in enumerate(INTENTS):
        revision = f"r{i}"
        result = build(
            source=FIXTURE / "source",
            params=FIXTURE / "params" / f"{revision}.json",
            policy_path=FIXTURE / "policies" / f"{revision}.policy.json",
            store=primary,
            revision=revision,
            parent=f"r{i-1}" if i else None,
            renders=True,
            intent=intent,
            trusted_reviewed_source=trusted_reviewed_source,
            sandbox_image=sandbox_image,
            blender=blender,
        )
        _assert_accepted(result)
        directory = primary / "accepted" / revision
        observations.append(read_json(directory / "inspection" / "observation.json"))
        views = sorted((directory / "inspection" / "views").glob("*.png"))
        assert len(views) >= 4, (revision, "four inspection views required")
        assert read_json(directory / "roundtrip" / "roundtrip.json")["passed"], revision
        assert read_json(directory / "reopened" / "reopen.json")["passed"], revision
        results.append({
            "revision": revision,
            "intent": intent,
            "status": result["status"],
            "params_sha256": _sha(FIXTURE / "params" / f"{revision}.json"),
            "policy_sha256": _sha(FIXTURE / "policies" / f"{revision}.policy.json"),
            "source_files": result["source_files"],
            "controller_files": result["controller_files"],
            "runtime_hash": result["runtime_hash"],
            "result_hash": read_json(primary / "last_good.json")["result_hash"],
            "renders": [str(path.relative_to(store)) for path in views],
            "jobs": result["jobs"],
        })

    geometry = verify(observations)

    # The reviewed bad parameter state changes a protected cat part while the
    # policy permits only an accessory change. It should complete inspection
    # and export, then fail controller acceptance without moving last_good.
    pointer_before = (primary / "last_good.json").read_bytes()
    bad = build(
        source=FIXTURE / "source",
        params=FIXTURE / "params" / "bad.json",
        policy_path=FIXTURE / "policies" / "bad.policy.json",
        store=primary,
        revision="bad-base",
        parent="r2",
        renders=False,
        intent="Deliberate invalid edit: alter protected cat geometry while requesting an accessory-only change",
        trusted_reviewed_source=trusted_reviewed_source,
        sandbox_image=sandbox_image,
        blender=blender,
    )
    assert bad["status"] == "rejected", bad
    assert all(bad["jobs"][job]["exit_code"] == 0 for job in ("author", "inspect", "roundtrip", "reopen")), bad
    assert any(f.get("check") == "unchanged" and f.get("part") in observations[0]["parts"] for f in bad["failures"]), bad
    assert (primary / "last_good.json").read_bytes() == pointer_before
    assert (primary / "attempts" / "bad-base" / "result.json").is_file()
    assert not (primary / "accepted" / "bad-base").exists()

    clean = store / "clean-rebuild"
    rebuild = build(
        source=FIXTURE / "source",
        params=FIXTURE / "params" / "r2.json",
        policy_path=FIXTURE / "policies" / "r2.policy.json",
        store=clean,
        revision="rebuild",
        renders=False,
        intent="Clean rebuild of final cat with sunglasses",
        trusted_reviewed_source=trusted_reviewed_source,
        sandbox_image=sandbox_image,
        blender=blender,
    )
    _assert_accepted(rebuild)
    clean_observation = read_json(clean / "accepted" / "rebuild" / "inspection" / "observation.json")
    assert fingerprints(clean_observation) == fingerprints(observations[-1]), "Final clean rebuild differs"

    summary = {
        "status": "passed",
        "scope": "Reviewed deterministic cat fixture; three local edits, one rejected invalid edit, clean rebuild",
        "checkout_head": _checkout_head(),
        "checkout_tree": _checkout_tree(),
        "checkout_dirty": _checkout_dirty(),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_head_ref": os.environ.get("GITHUB_HEAD_REF"),
        "execution_mode": rebuild["execution_mode"],
        "security_boundary": rebuild["security_boundary"],
        "geometry": geometry,
        "last_good_preserved_after_rejection": True,
        "bad_edit_failures": bad["failures"],
        "bad_edit_params_sha256": _sha(FIXTURE / "params" / "bad.json"),
        "bad_edit_policy_sha256": _sha(FIXTURE / "policies" / "bad.policy.json"),
        "clean_rebuild_fingerprints_equal": True,
        "results": results,
    }
    store.mkdir(parents=True, exist_ok=True)
    (store / "anime-cat-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--trusted-reviewed-source", action="store_true")
    mode.add_argument("--sandbox-image")
    parser.add_argument("--blender", default="blender", help="reviewed local Blender binary (native mode only)")
    args = parser.parse_args()
    print(json.dumps(run(
        args.store, trusted_reviewed_source=args.trusted_reviewed_source,
        sandbox_image=args.sandbox_image, blender=args.blender,
    ), indent=2))
