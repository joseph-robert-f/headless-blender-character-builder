"""The `hbcb` command line.

This is the part a new user meets first, so it tries to need as little from
them as possible: no config file, no JSON to author, no Blender path to set. It
finds Blender, launches it headless with the runner script, and forwards the
runner's exit code.

    hbcb build --preset facet-bot -o build/facet-bot
    hbcb build --preset cocoa-cub --height 120 --print-profile resin-standard -o out
    hbcb verify build/facet-bot
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

from . import __version__, blender_finder, layout, presets, print_profiles, spec
from .exit_codes import BLENDER_FAILED, INVALID_REQUEST, USAGE, BuildError
from .spec import REPO_ROOT

RUNNER = os.path.join(REPO_ROOT, "blender", "runner.py")

# Blender flags that make a run reproducible and safe: no user preferences, no
# add-ons, no auto-run of embedded Python, no network.
BLENDER_FLAGS = (
    "--background",
    "--factory-startup",
    "--offline-mode",
    "--disable-autoexec",
    "--python-exit-code",
    "1",
)

# Cycles writes a progress line per sample update; useful when debugging, noise
# the rest of the time.
_NOISE_PREFIXES = ("Fra:", "Blender quit", "Info: Deleted", "Timer '")

_EXIT_SENTINEL = "__HBCB_EXIT__"


def _looks_like_noise(line):
    return any(line.startswith(prefix) for prefix in _NOISE_PREFIXES)


def _run_blender(executable, arguments, verbose):
    """Run the runner script inside Blender, streaming filtered output.

    The runner prints a sentinel carrying its intended exit code. Relying on
    the process status alone is fragile -- Blender does not consistently
    propagate a script's `sys.exit` value across versions and platforms -- so
    the sentinel wins when present.
    """
    command = [executable] + list(BLENDER_FLAGS) + ["--python", RUNNER, "--"] + list(arguments)
    if verbose:
        print("+ %s" % " ".join(command))

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    reported = None
    for line in process.stdout:
        line = line.rstrip("\n")
        if line.startswith(_EXIT_SENTINEL):
            try:
                reported = int(line.split()[1])
            except (IndexError, ValueError):
                reported = None
            continue
        if verbose or not _looks_like_noise(line):
            print(line)
    process.wait()
    return process.returncode if reported is None else reported


def _run_in_process(arguments):
    """Fallback path: Blender is installed as the `bpy` Python module."""
    sys.path.insert(0, REPO_ROOT)
    from blender import runner  # noqa: WPS433  (import is deliberately lazy)

    return runner.main(["hbcb"] + list(arguments))


def _dispatch(arguments, verbose):
    """Send `arguments` to the runner via whichever Blender is available."""
    executable = blender_finder.find()
    if executable:
        installed = blender_finder.version(executable)
        from . import MINIMUM_BLENDER

        if installed and installed < MINIMUM_BLENDER:
            raise BuildError(
                BLENDER_FAILED,
                "found Blender %s at %s, but %s or newer is required (the 4.2+ "
                "export operators are not present in older releases)"
                % (
                    blender_finder.format_version(installed),
                    executable,
                    blender_finder.format_version(MINIMUM_BLENDER),
                ),
            )
        if verbose:
            print(
                "using Blender %s at %s"
                % (blender_finder.format_version(installed) if installed else "?", executable)
            )
        return _run_blender(executable, arguments, verbose)

    if blender_finder.bpy_module_available():
        if verbose:
            print("using the bpy Python module (no Blender executable found)")
        return _run_in_process(arguments)

    raise BuildError(BLENDER_FAILED, blender_finder.INSTALL_HINT)


def _apply_overrides(raw, args):
    """Apply the convenience flags on top of a request document.

    These exist so the common tweaks -- make it taller, print it in resin --
    do not require opening a JSON file.
    """
    character = raw.setdefault("spec", {})
    if args.height is not None:
        character["height_mm"] = args.height
    if args.style is not None:
        character["style"] = args.style
    if args.name is not None:
        character["name"] = args.name
    if args.print_profile is not None:
        raw.setdefault("print_profile", {})["preset"] = args.print_profile
    if args.no_renders:
        raw["output_profile"] = "print-only-v1"
    if args.advisory:
        raw["quality_profile"] = "advisory-v1"
    return raw


def _load_raw(args):
    if args.preset:
        try:
            return presets.get(args.preset)
        except KeyError:
            raise BuildError(
                INVALID_REQUEST,
                "unknown preset %r (available: %s)" % (args.preset, ", ".join(presets.names())),
            ) from None
    return spec.load_request_file(args.request)


def command_build(args):
    raw = _apply_overrides(_load_raw(args), args)
    # Resolve on the host as well as inside Blender: a bad request should fail
    # in milliseconds with a clear message, not after Blender has started.
    request = spec.resolve(raw)

    output = os.path.abspath(args.output)
    print(
        "building %s: %s, %.0f mm, %s"
        % (
            request.spec["name"],
            request.spec["style"],
            request.spec["height_mm"],
            print_profiles.describe(request.print_profile),
        )
    )

    # Overrides may have produced a document that matches no preset, so the
    # effective request is handed to the runner as a file. It goes to a
    # temporary path rather than into the output directory: the published tree
    # should contain exactly the artifacts the manifest lists, and the resolved
    # request is already embedded in the manifest anyway.
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="hbcb-request-", delete=False, encoding="utf-8"
    )
    try:
        json.dump(raw, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.close()
        code = _dispatch(["build", "--request", handle.name, "--output", output], args.verbose)
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    if code == 0:
        print("\nartifacts in %s" % output)
        for relative in layout.expected(request.output_profile, request.render_profile):
            print("  %s" % relative)
        print("\nNext: open %s in a slicer, or run  hbcb verify %s" % (layout.MODEL_STL, output))
    return code


def command_verify(args):
    return _dispatch(["verify", "--output", os.path.abspath(args.output)], args.verbose)


def command_selftest(args):
    """Run the geometry test suite inside Blender.

    Exposed as a command so contributors do not have to remember the Blender
    invocation, and so a user who suspects their Blender build is the problem
    can check it in one step.
    """
    return _dispatch(["selftest"], args.verbose)


def command_validate(args):
    request = spec.resolve_file(args.request)
    print("%s is a valid BuildRequest" % args.request)
    print(
        "  character     %s (%s, %.0f mm)"
        % (request.spec["name"], request.spec["style"], request.spec["height_mm"])
    )
    print("  print profile %s" % print_profiles.describe(request.print_profile))
    print("  request hash  %s" % request.request_sha256[:16])
    return 0


def command_presets(args):
    if args.name:
        try:
            document = presets.get(args.name)
        except KeyError:
            raise BuildError(
                INVALID_REQUEST,
                "unknown preset %r (available: %s)" % (args.name, ", ".join(presets.names())),
            ) from None
        json.dump(document, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    print("Bundled presets:\n")
    for name, summary in presets.listing():
        print("  %-15s %s" % (name, summary))
    print("\nBuild one with:  hbcb build --preset <name> -o build/<name>")
    print("Print its JSON:  hbcb preset <name> > my-character.json")
    return 0


def command_profiles(args):
    print("Print profiles:\n")
    for name in sorted(print_profiles.PRESETS):
        print(
            "  %-18s %s" % (name, print_profiles.describe(print_profiles.resolve({"preset": name})))
        )
    print("\nSelect one with:  hbcb build --preset facet-bot --print-profile <name> -o out")
    return 0


def command_doctor(args):
    """Report what the tool can see, so setup problems are self-diagnosing."""
    print("hbcb %s" % __version__)
    print("python %s" % sys.version.split()[0])

    executable = blender_finder.find()
    if executable:
        installed = blender_finder.version(executable)
        print("blender executable: %s" % executable)
        print(
            "blender version:    %s"
            % (blender_finder.format_version(installed) if installed else "unreadable")
        )
    else:
        print("blender executable: not found")

    print(
        "bpy python module:  %s"
        % ("available" if blender_finder.bpy_module_available() else "not installed")
    )
    print("schemas:            %s" % spec.SCHEMA_DIR)
    print("runner:             %s" % RUNNER)

    ready = bool(executable) or blender_finder.bpy_module_available()
    if ready:
        print("\nReady. Try:  hbcb build --preset facet-bot -o build/facet-bot")
        return 0
    print("\n%s" % blender_finder.INSTALL_HINT)
    return BLENDER_FAILED


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hbcb",
        description="Generate printable 3D characters with headless Blender.",
    )
    parser.add_argument("--version", action="version", version="hbcb %s" % __version__)
    parser.add_argument("-v", "--verbose", action="store_true", help="show Blender's full output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build a character into an output directory")
    source = build.add_mutually_exclusive_group(required=True)
    source.add_argument("--preset", help="a bundled preset name (see: hbcb presets)")
    source.add_argument("--request", help="path to a BuildRequest JSON file")
    build.add_argument("-o", "--output", required=True, help="output directory")
    build.add_argument("--height", type=float, help="override the height in millimetres")
    build.add_argument(
        "--style", choices=["geometric", "low_poly", "chibi"], help="override the style"
    )
    build.add_argument("--name", help="override the character name")
    build.add_argument(
        "--print-profile",
        choices=sorted(print_profiles.PRESETS),
        help="printer constraints to build and check against",
    )
    build.add_argument(
        "--no-renders",
        action="store_true",
        help="skip preview renders and the GLB; much faster when you only want the STL",
    )
    build.add_argument(
        "--advisory",
        action="store_true",
        help="report failed print checks instead of failing the build",
    )
    build.set_defaults(handler=command_build)

    verify = subparsers.add_parser(
        "verify", help="re-check a finished build in a fresh Blender process"
    )
    verify.add_argument("output", help="a build output directory")
    verify.set_defaults(handler=command_verify)

    validate = subparsers.add_parser(
        "validate", help="check a BuildRequest file without building it"
    )
    validate.add_argument("request", help="path to a BuildRequest JSON file")
    validate.set_defaults(handler=command_validate)

    listing = subparsers.add_parser("presets", help="list the bundled character presets")
    listing.set_defaults(handler=command_presets, name=None)

    show = subparsers.add_parser("preset", help="print one preset as JSON")
    show.add_argument("name")
    show.set_defaults(handler=command_presets)

    profiles = subparsers.add_parser("profiles", help="list the printer profiles")
    profiles.set_defaults(handler=command_profiles)

    doctor = subparsers.add_parser("doctor", help="check that everything needed is present")
    doctor.set_defaults(handler=command_doctor)

    selftest = subparsers.add_parser("selftest", help="run the geometry test suite inside Blender")
    selftest.set_defaults(handler=command_selftest)

    return parser


def main(argv=None):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return USAGE if error.code else 0

    try:
        return args.handler(args)
    except BuildError as error:
        sys.stderr.write("error: %s\n" % error.message)
        return error.code
    except KeyboardInterrupt:
        sys.stderr.write("\ninterrupted\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
