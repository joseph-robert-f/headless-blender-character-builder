"""Explicit opt-in developer CLI, separate from the stable builder CLI."""
import argparse
import json
from pathlib import Path
from .controller import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build"])
    for field in ("source", "params", "policy", "store"):
        parser.add_argument("--" + field, type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--parent")
    parser.add_argument("--intent", default="", help="Human-readable requested revision, recorded with evidence")
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--trusted-reviewed-source", action="store_true", help="Unsafe for generated/unreviewed code. Explicitly trust this entire source bundle.")
    parser.add_argument("--sandbox-image", help="Exact local Docker image ID sha256:..., no native fallback")
    parser.add_argument("--skip-renders", action="store_true")
    args = parser.parse_args()
    try:
        result = build(source=args.source, params=args.params, policy_path=args.policy, store=args.store,
                       revision=args.revision, parent=args.parent, blender=args.blender,
                       trusted_reviewed_source=args.trusted_reviewed_source, renders=not args.skip_renders, intent=args.intent, sandbox_image=args.sandbox_image)
        print(json.dumps({k: result[k] for k in ("status", "revision", "failures")}, indent=2))
        if "error" in result: print(result["error"])
        return 0 if result["status"] == "accepted" else 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
