"""Replay recorded external-assistant source through the isolated request bridge.

The source came from a real exported brief. This replay makes no model call.
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
from experimental_modeling.requests import inspect_proposal, run_proposal
from experimental_modeling.request_contract import encoded, read_json, source_manifest, validate_result_binding
from experimental_modeling.review_server import ReviewProject, verified_revision
from experimental_modeling.runtime import RuntimeSelection

EXAMPLE = ROOT / "experimental_modeling/examples/external_lamp"
SOURCE_HASHES = {"builder.py": "8d31b470a31f6a18e90fbcdefe3ecb49c08f1cfc111fffc5d02f1f87a1932cc6",
                 "geometry.py": "4104a88f029ea1ced220f0aa1ba3633957e7ed7e9d6210e7bfd1a8ede857cfcb"}
REQUEST_ID = "55a3819fc372c6a56345739bb7f706485f6a87c5ff98f1ec0f1e1948e52441a7"


def run(output, image, docker, socket):
    output = Path(output).absolute()
    if output.exists():
        raise ValueError("Use a new output directory.")
    assert source_manifest(EXAMPLE / "proposal/source") == SOURCE_HASHES, "Original author source changed"
    output.mkdir()
    project = initialize(output / "project", "External author desk lamp")
    handoff, proposal = output / "handoff", output / "proposal"
    shutil.copytree(EXAMPLE / "handoff", handoff)
    shutil.copytree(EXAMPLE / "proposal", proposal)
    selection = RuntimeSelection(docker=Path(docker), socket=Path(socket), image=image)
    policy, rules = EXAMPLE / "policy-initial.json", EXAMPLE / "requirements.json"
    inspected = inspect_proposal(project, handoff, proposal, policy, selection, requirements_path=rules)[0]
    assert inspected["request_id"] == REQUEST_ID
    (output / "inspection-approval.json").write_bytes(encoded(inspected))
    result = run_proposal(project, handoff, proposal, policy, selection,
        requirements_path=rules, expected_digest=inspected["inspection_digest"], revision="lamp-r0")
    # Preserve diagnostics before asserting the independent acceptance result.
    summary = {"scope": "Recorded external assistant source, not built-in model execution", "status": result["status"],
               "request_id": REQUEST_ID, "source_files": SOURCE_HASHES, "revision": "lamp-r0",
               "error": result.get("error"), "failures": result["failures"], "jobs": result["jobs"]}
    (output / "external-lamp-summary.json").write_bytes(encoded(summary))
    assert result["status"] == "accepted", json.dumps(summary, indent=2)
    directory, saved, result_hash = verified_revision(project.folder("evidence"), "lamp-r0")
    assert validate_result_binding(directory, saved)["request"]["request_id"] == REQUEST_ID
    review = ReviewProject(project.folder("evidence"), read_only=True).revision("lamp-r0")
    assert review["report"]["machine_verified"] and not review["state"]["human_accepted"]
    assert len(list((directory / "inspection/views").glob("*.png"))) == 4
    observation = read_json(directory / "inspection/observation.json", 4 * 1024 * 1024)
    extents = {}
    for name, part in observation["parts"].items():
        vertices = part["world_vertices"]
        extents[name] = [max(v[axis] for v in vertices) - min(v[axis] for v in vertices) for axis in range(3)]
    summary.update({"result_hash": result_hash, "machine_verified": True, "human_accepted": False,
                    "measured_extents_m": extents})
    (output / "external-lamp-summary.json").write_bytes(encoded(summary))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sandbox-image", required=True)
    parser.add_argument("--docker", type=Path, required=True)
    parser.add_argument("--docker-socket", type=Path, default=Path("/run/docker.sock"))
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.sandbox_image, args.docker, args.docker_socket), indent=2))
