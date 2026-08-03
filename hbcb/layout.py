"""The published artifact layout.

Both the builder and the verifier read these names from here, so the set of
files a build promises and the set the verifier insists on can never drift
apart.
"""

MODEL_BLEND = "model.blend"
MODEL_STL = "model.stl"
MODEL_GLB = "model.glb"
PREVIEW = "preview.png"
QA = "qa.json"
MANIFEST = "manifest.json"

DIAGNOSTIC_VIEWS = ("front", "side", "back")
DIAGNOSTICS_DIR = "diagnostics"

# Artifacts are staged here and moved into place only once the build has
# succeeded, so a failed run cannot leave something that looks finished.
STAGING_DIR = ".hbcb-staging"


def diagnostic(view):
    return "%s/%s.png" % (DIAGNOSTICS_DIR, view)


def diagnostic_paths():
    return {view: diagnostic(view) for view in DIAGNOSTIC_VIEWS}


def expected(output_profile, render_profile):
    """Relative paths a build with these profiles must publish.

    `print-only-v1` drops the preview renders and the GLB: a batch that only
    feeds a slicer does not need them, and skipping the renders is the
    difference between a two-second build and a two-minute one.
    """
    paths = [MODEL_BLEND, MODEL_STL, QA, MANIFEST]
    if output_profile == "complete-v1":
        paths.append(MODEL_GLB)
        if render_profile != "none":
            paths.append(PREVIEW)
            paths.extend(diagnostic(view) for view in DIAGNOSTIC_VIEWS)
    return sorted(paths)
