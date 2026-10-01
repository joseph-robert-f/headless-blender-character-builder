"""This is an optional developer CLI. It is not the stable builder CLI."""
import argparse
import json
from pathlib import Path
from .controller import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    review=commands.add_parser("review",help="Open the local review program. The program does not run source.")
    review.add_argument("--store",type=Path,required=True);review.add_argument("--port",type=int,default=0)
    build_parser=commands.add_parser("build",help="Build a source revision again and do its verification checks.")
    for field in ("source", "params", "policy", "store"):
        build_parser.add_argument("--" + field, type=Path, required=True)
    build_parser.add_argument("--revision", required=True)
    build_parser.add_argument("--parent")
    build_parser.add_argument("--requirements", type=Path, help="Versioned project rules. The first build prevents changes to these rules.")
    build_parser.add_argument("--intent", default="", help="Description of the change that you want. The program records it with the evidence.")
    build_parser.add_argument("--blender", default="blender")
    build_parser.add_argument("--trusted-reviewed-source", action="store_true", help='Not safe for generated code or source without review. Give permission to run all source in this bundle.')
    build_parser.add_argument("--sandbox-image", help="Use the complete local Docker image ID sha256:.... The program cannot fall back to native execution.")
    build_parser.add_argument("--skip-renders", action="store_true")
    args = parser.parse_args()
    try:
        if args.command=="review":
            from .review_server import serve
            serve(args.store,args.port)
            return 0
        result = build(source=args.source, params=args.params, policy_path=args.policy, store=args.store,
                       revision=args.revision, parent=args.parent, blender=args.blender,
                       trusted_reviewed_source=args.trusted_reviewed_source, renders=not args.skip_renders, intent=args.intent, sandbox_image=args.sandbox_image, requirements_path=args.requirements)
        print(json.dumps({k: result[k] for k in ("status", "revision", "failures")}, indent=2))
        if "error" in result: print(result["error"])
        return 0 if result["status"] == "accepted" else 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
