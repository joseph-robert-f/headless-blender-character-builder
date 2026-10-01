"""Exercise the request bridge with a handwritten fixture in real Docker jobs.

This is execution evidence, not a natural-language generation demonstration.
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
from experimental_modeling.requests import prepare, inspect_proposal, run_proposal
from experimental_modeling.request_contract import encoded, validate_result_binding
from experimental_modeling.review_server import ReviewProject, verified_revision
from experimental_modeling.runtime import RuntimeSelection

FIXTURE = ROOT / "experimental_modeling/examples/robot"


def run(root, image, docker, socket):
    root = Path(root).absolute()
    if root.exists():
        raise ValueError("Use a new output directory.")
    root.mkdir()
    project = initialize(root / "project", "Request bridge fixture")
    for name in ("handoffs", "proposals", "policies"):
        (root / name).mkdir()
    selection = RuntimeSelection(docker=Path(docker), socket=Path(socket), image=image)
    summary = []
    def execute(revision, params, policy, prompt, reference=None):
        handoff = root / "handoffs" / revision
        if reference is None:
            brief = root / "brief.txt"; brief.write_text(prompt, encoding="utf-8")
            prepare(project, handoff, brief_file=brief)
        else:
            review = ReviewProject(project.folder("evidence"))
            data = review.revision(reference)
            request = review.request({"csrf_token": review.token, "revision_id": reference,
                "expected_result_hash": data["revision"]["result_hash"], "prompt": prompt})
            prepare(project, handoff, request_id=request["request_id"])
        proposal = root / "proposals" / revision
        shutil.copytree(FIXTURE / "source", proposal / "source", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (proposal / "params.json").write_bytes(encoded(params))
        policy_path = root / "policies" / (revision + ".json"); policy_path.write_bytes(encoded(policy))
        inspected = inspect_proposal(project, handoff, proposal, policy_path, selection)[0]
        result = run_proposal(project, handoff, proposal, policy_path, selection,
                              expected_digest=inspected["inspection_digest"], revision=revision)
        directory, saved, result_hash = verified_revision(project.folder("evidence"), revision)
        binding = validate_result_binding(directory, saved)
        assert binding["request"]["prompt"] == prompt
        assert all(result["jobs"][job]["exit_code"] == 0 for job in ("author", "inspect", "roundtrip", "reopen")), result
        assert len(list((directory / "inspection/views").glob("*.png"))) == 4
        assert run_proposal(project, handoff, proposal, policy_path, selection,
            expected_digest=inspected["inspection_digest"], revision=revision) == result
        summary.append({"revision": revision, "status": result["status"], "result_hash": result_hash,
                        "request_id": binding["request"]["request_id"], "inspection_digest": binding["inspection_digest"]})
        return result
    initial = json.loads((FIXTURE / "initial.json").read_text())
    initial_policy = json.loads((FIXTURE / "initial.policy.json").read_text())
    moved = json.loads((FIXTURE / "revision_1_mast.json").read_text())
    moved_policy = json.loads((FIXTURE / "revision_1_mast.policy.json").read_text())
    assert execute("r0", initial, initial_policy, "Build the handwritten robot fixture for bridge verification.")["status"] == "accepted"
    assert execute("r1", moved, moved_policy, "Translate only the mast by 0.25 m on X and -0.1 m on Y.", "r0")["status"] == "accepted"
    repair_policy = json.loads(json.dumps(moved_policy))
    for constraint in repair_policy["constraints"]:
        if constraint["kind"] == "translated":
            constraint["data"]["delta"] = [0, 0, 0]
    before = (project.folder("evidence") / "last_good.json").read_bytes()
    assert execute("bad", moved | {"bad_body_shift": .08}, repair_policy,
                   "Keep the model geometry unchanged. This is a deliberate negative control.", "r1")["status"] == "rejected"
    assert (project.folder("evidence") / "last_good.json").read_bytes() == before
    assert execute("repair", moved, repair_policy, "Restore the protected body and keep the accepted mast position.", "bad")["status"] == "accepted"
    request_rows = ReviewProject(project.folder("evidence")).requests()
    outcomes = [result["outcome"] for row in request_rows for result in row.get("results", [])]
    assert outcomes.count("machine_accepted") == 3 and outcomes.count("checks_rejected") == 1
    result = {"status": "passed", "scope": "Handwritten fixture; not AI generation", "results": summary,
              "checks": ["initial handoff", "measured refinement", "negative control", "protected parent retained", "repair", "all four Docker stages", "immutable replay", "request result links"]}
    (root / "request-bridge-summary.json").write_bytes(encoded(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sandbox-image", required=True)
    parser.add_argument("--docker", type=Path, required=True)
    parser.add_argument("--docker-socket", type=Path, default=Path("/run/docker.sock"))
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.sandbox_image, args.docker, args.docker_socket), indent=2))
