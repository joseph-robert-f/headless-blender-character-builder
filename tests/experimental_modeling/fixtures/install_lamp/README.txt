DESK LAMP REVIEW DEMO

This portable project contains four actual isolated build results:
- lamp-r0: initial 260 mm lamp
- lamp-r1: accepted 290 mm height refinement
- lamp-slim-bad: rejected 170 mm base-width change
- lamp-slim-repair: accepted repair with a 160 mm base and 8 mm stem

The final model is about 290 mm high. The base is 160 x 120 x 18 mm.
The complete base geometry, transform, and material match the accepted earlier models.
Human acceptance is not recorded. Examine the model and its evidence yourself.
This is a visual scene. It is not an electrical product or a print-ready design.

OPEN WITH THE READ-ONLY REVIEW PREVIEW

1. Extract the complete ZIP into a new local folder.
2. Find the desk-lamp-demo folder that contains modeling-project.json.
3. Open a terminal in the previously supplied review-preview program folder.
4. Start that program with the extracted project folder.

Windows PowerShell example:
.\hbcb-review-preview.exe --project "C:\Projects\desk-lamp-demo"

Mac terminal example:
./hbcb-review-preview --project "$HOME/Projects/desk-lamp-demo"

Replace the example path with your extracted project path.
Open the local address that the program shows in your browser.
Keep the terminal open. To stop, type q and press Enter, or press Ctrl-C.
Do not bypass an OS or antivirus warning.

The read-only preview can display saved geometry, measurements, renders, and history.
It can download the existing GLB. It cannot generate models or record decisions.
Blender, a provider account, and a model API key are not necessary for this review.

The project was checked with the PR27 source reader at commit 2cd8f5c.
This ZIP was not opened with the native Windows or Mac program during these checks.
The older reader does not show the new request-result links.
It displays all four revisions and their recorded check results.

EVIDENCE

Source commit: 6ad24b641b2a2f7e8742d3f88e873207eba2dc2d
Source tree: 49d0962cdf139f2b9eac8ae0001bea8006f171a1
CI run: https://github.com/joseph-robert-f/headless-blender-character-builder/actions/runs/36940918404

All immutable result files and their required logs are retained without changes.
The ZIP contains explicit entries for the required empty project directories.
Transient launcher state and lease files are excluded.
verification-summary.json is the original CI measurement summary.
The model source came from an external assistant. The app made no model call.
