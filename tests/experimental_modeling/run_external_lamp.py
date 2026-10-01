"""Replay recorded external-assistant proposals through the isolated request bridge.

Each proposal came from an operator brief. This replay makes no model call.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experimental_modeling.project import initialize
from experimental_modeling.requests import inspect_proposal, prepare, run_proposal
from experimental_modeling.request_contract import (encoded, prompt_text, read_json, source_manifest,
    validate_request, validate_result_binding)
from experimental_modeling.contracts import Policy
from experimental_modeling.requirements import RequirementSet
from experimental_modeling.review_server import ReviewProject, verified_revision
from experimental_modeling.runtime import RuntimeSelection

EXAMPLE = ROOT / "experimental_modeling/examples/external_lamp"
SOURCE_HASHES = {"builder.py": "8d31b470a31f6a18e90fbcdefe3ecb49c08f1cfc111fffc5d02f1f87a1932cc6",
                 "geometry.py": "4104a88f029ea1ced220f0aa1ba3633957e7ed7e9d6210e7bfd1a8ede857cfcb"}
SLIM_HASHES = SOURCE_HASHES | {"geometry.py": "e908a625793974e00b9776f31242ab4b72e73bd611f1a0937b055c1f42b1b277"}
REQUEST_ID = "55a3819fc372c6a56345739bb7f706485f6a87c5ff98f1ec0f1e1948e52441a7"
HEIGHT_REQUEST_ID = "6b7702474c63f5e28409826650628dc775995719b216f2ec3188a28eebd88759"


def validate_examples():
    """Inspect recorded inputs without importing or executing author source."""
    request = validate_request(read_json(EXAMPLE / "handoff/request.json"))
    assert request["request_id"] == REQUEST_ID
    assert source_manifest(EXAMPLE / "proposal/source") == SOURCE_HASHES
    Policy.parse(read_json(EXAMPLE / "policy-initial.json"))
    RequirementSet.parse(read_json(EXAMPLE / "requirements.json"))
    historical = validate_request(read_json(EXAMPLE / "revisions/height/recorded-request.json"))
    assert historical["request_id"] == HEIGHT_REQUEST_ID
    assert historical["parent"] == {"revision": "lamp-r0", "result_hash": "5c4464e87006c0c95e88e3431fdc70bad3cf49ba17b15d39227dfa579a4bffeb"}
    result = {}
    for name, expected_source, width in (("height", SOURCE_HASHES, .16), ("slim-negative", SLIM_HASHES, .17), ("slim-repair", SLIM_HASHES, .16)):
        folder = EXAMPLE / "revisions" / name
        assert source_manifest(folder / "proposal/source") == expected_source, "Recorded author source changed"
        params = read_json(folder / "proposal/params.json")
        assert params == {"height_m": .29, "base_width_m": width, "base_depth_m": .12}
        Policy.parse(read_json(folder / "policy.json"))
        prompt = historical["prompt"] if name == "height" else prompt_text((folder / "request.txt").read_text(encoding="utf-8"))
        result[name] = {"folder": folder, "prompt": prompt, "source_files": expected_source}
    return result


def measurements(observation):
    extents = {}
    all_vertices = []
    for name, part in observation["parts"].items():
        vertices = part["world_vertices"]; all_vertices.extend(vertices)
        extents[name] = [max(v[axis] for v in vertices) - min(v[axis] for v in vertices) for axis in range(3)]
    return {"part_extents_m": extents, "total_height_m": max(v[2] for v in all_vertices) - min(v[2] for v in all_vertices)}


def run(output, image, docker, socket):
    records = validate_examples()
    output = Path(output).absolute()
    if output.exists():
        raise ValueError("Use a new output directory.")
    output.mkdir()
    project = initialize(output / "project", "External author desk lamp")
    selection = RuntimeSelection(docker=Path(docker), socket=Path(socket), image=image)
    rules = EXAMPLE / "requirements.json"
    rows, observations = [], {}
    summary = {"scope": "Recorded external assistant source and refinements, not built-in model execution", "results": rows}
    def save_summary():
        (output / "external-lamp-summary.json").write_bytes(encoded(summary))
    def execute(revision, folder, source_files, expected_status, *, reference=None, prompt=None):
        handoff, proposal = output / (revision + "-handoff"), output / (revision + "-proposal")
        if reference is None:
            shutil.copytree(EXAMPLE / "handoff", handoff)
            policy = EXAMPLE / "policy-initial.json"
        else:
            review = ReviewProject(project.folder("evidence"))
            data = review.revision(reference)
            saved_request = review.request({"csrf_token": review.token, "revision_id": reference,
                "expected_result_hash": data["revision"]["result_hash"], "prompt": prompt})
            prepare(project, handoff, request_id=saved_request["request_id"])
            policy = folder / "policy.json"
        shutil.copytree(folder / "proposal", proposal)
        assert source_manifest(proposal / "source") == source_files
        inspected = inspect_proposal(project, handoff, proposal, policy, selection, requirements_path=rules)[0]
        if reference is None:
            assert inspected["request_id"] == REQUEST_ID
        (output / (revision + "-approval.json")).write_bytes(encoded(inspected))
        result = run_proposal(project, handoff, proposal, policy, selection,
            requirements_path=rules, expected_digest=inspected["inspection_digest"], revision=revision)
        row = {"revision": revision, "status": result["status"], "request_id": inspected["request_id"],
               "reference": inspected["reference"], "execution_parent": inspected["execution_parent"],
               "source_files": source_files, "error": result.get("error"), "failures": result["failures"], "jobs": result["jobs"]}
        rows.append(row); save_summary()
        assert result["status"] == expected_status, json.dumps(row, indent=2)
        directory, saved, result_hash = verified_revision(project.folder("evidence"), revision)
        binding = validate_result_binding(directory, saved)
        assert binding["request"]["request_id"] == inspected["request_id"]
        if prompt is not None:
            assert binding["request"]["prompt"] == prompt
        reviewed = ReviewProject(project.folder("evidence"), read_only=True).revision(revision)
        assert reviewed["report"]["machine_verified"] == (expected_status == "accepted")
        assert not reviewed["state"]["human_accepted"]
        assert all(result["jobs"][job]["exit_code"] == 0 for job in ("author", "inspect", "roundtrip", "reopen"))
        assert len(list((directory / "inspection/views").glob("*.png"))) == 4
        observation = read_json(directory / "inspection/observation.json", 4 * 1024 * 1024)
        observations[revision] = observation
        row.update({"result_hash": result_hash, "machine_verified": reviewed["report"]["machine_verified"],
                    "human_accepted": False, "measured": measurements(observation)})
        assert run_proposal(project, handoff, proposal, policy, selection, requirements_path=rules,
            expected_digest=inspected["inspection_digest"], revision=revision) == result
        save_summary()
        return result
    execute("lamp-r0", EXAMPLE, SOURCE_HASHES, "accepted")
    height = records["height"]
    execute("lamp-r1", height["folder"], SOURCE_HASHES, "accepted", reference="lamp-r0", prompt=height["prompt"])
    pointer_before = (project.folder("evidence") / "last_good.json").read_bytes()
    negative = records["slim-negative"]
    bad = execute("lamp-slim-bad", negative["folder"], SLIM_HASHES, "rejected", reference="lamp-r1", prompt=negative["prompt"])
    assert (project.folder("evidence") / "last_good.json").read_bytes() == pointer_before
    assert any(f.get("part") == "base" or f.get("requirement_id") == "base-preserved" for f in bad["failures"])
    repair = records["slim-repair"]
    execute("lamp-slim-repair", repair["folder"], SLIM_HASHES, "accepted", reference="lamp-slim-bad", prompt=repair["prompt"])
    keys = ("geometry_hash", "transform_hash", "material_hash")
    base_fingerprints = [tuple(observations[name]["parts"]["base"][key] for key in keys) for name in ("lamp-r0", "lamp-r1", "lamp-slim-repair")]
    assert len(set(base_fingerprints)) == 1
    for name in ("lamp-r1", "lamp-slim-bad", "lamp-slim-repair"):
        assert abs(measurements(observations[name])["total_height_m"] - .29) < 1e-6
    assert abs(measurements(observations["lamp-slim-repair"])["part_extents_m"]["stem"][0] - .008) < 1e-6
    summary.update({"status": "passed", "base_fingerprints_equal": True, "negative_control_preserved_last_good": True,
        "historical_height_request_id": HEIGHT_REQUEST_ID,
        "checks": ["initial external source", "30 mm height refinement", "base and material preservation", "source-level stem edit", "170 mm base rejected", "160 mm base repair", "all isolated stages", "request result links", "immutable replay"]})
    save_summary()
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sandbox-image", required=True)
    parser.add_argument("--docker", type=Path, required=True)
    parser.add_argument("--docker-socket", type=Path, default=Path("/run/docker.sock"))
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.sandbox_image, args.docker, args.docker_socket), indent=2))
