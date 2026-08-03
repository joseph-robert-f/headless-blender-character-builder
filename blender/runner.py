"""Entry point executed inside Blender.

Invoked as:

    blender --background --factory-startup --offline-mode --disable-autoexec \\
      --python blender/runner.py -- build --request req.json --output build/demo

Blender consumes its own arguments and passes everything after `--` to the
script, which is why the parsing below looks for that separator. The module
also runs correctly under the `bpy` PyPI module, where there is no separator
and `sys.argv` is an ordinary argument list.
"""

import argparse
import os
import sys
import traceback

# Blender does not put the script's project root on sys.path, so the shared
# `hbcb` package has to be located explicitly.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Absolute imports throughout: Blender executes this file as __main__ with no
# parent package, so `from . import ...` would fail.
from hbcb import spec as spec_module  # noqa: E402
from hbcb.exit_codes import INTERNAL, USAGE, BuildError  # noqa: E402


def script_argv(argv=None):
    """Arguments intended for this script.

    Everything after a bare `--` when Blender launched us; the whole list minus
    the program name otherwise.
    """
    argv = list(sys.argv if argv is None else argv)
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    return argv[1:]


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="hbcb-runner",
        description="Build a character from a BuildRequest inside Blender.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build a request into an output directory")
    source = build.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", help="path to a BuildRequest JSON file")
    source.add_argument("--preset", help="name of a bundled preset")
    build.add_argument("--output", required=True, help="directory to publish artifacts into")
    build.add_argument(
        "--mode",
        default="native",
        choices=["native", "container"],
        help="recorded in the manifest as the execution mode",
    )

    verify = subparsers.add_parser(
        "verify", help="re-open and re-import a finished build in this fresh process"
    )
    verify.add_argument("--output", required=True, help="directory containing a finished build")

    subparsers.add_parser("selftest", help="run the Blender integration test suite")

    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(script_argv(argv))
    except SystemExit as error:
        # argparse exits 2 for usage errors, which already matches USAGE.
        return USAGE if error.code else 0

    try:
        if args.command == "build":
            from blender import build as build_module

            if args.preset:
                request = spec_module.resolve_preset(args.preset)
            else:
                request = spec_module.resolve_file(args.request)
            build_module.run(request, args.output, mode=args.mode)
            return 0

        if args.command == "selftest":
            from tests.blender.run import main as run_tests

            return run_tests()

        from blender import verify as verify_module

        return verify_module.run(args.output)
    except BuildError as error:
        sys.stderr.write("error: %s\n" % error.message)
        return error.code
    except KeyboardInterrupt:
        sys.stderr.write("error: interrupted\n")
        return INTERNAL
    except Exception:
        traceback.print_exc()
        sys.stderr.write("error: unexpected failure inside the Blender runner\n")
        return INTERNAL


def _run_as_script():
    code = main()
    # Blender does not reliably propagate a --python script's sys.exit value,
    # so the intended code is also printed for the host CLI to read back.
    sys.stdout.write("__HBCB_EXIT__ %d\n" % code)
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(code)


if __name__ == "__main__":
    _run_as_script()
