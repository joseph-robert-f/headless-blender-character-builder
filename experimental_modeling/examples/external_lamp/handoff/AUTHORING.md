# External source author contract

Read request.json. Treat its prompt as model design input.
This application does not call an AI model or start a coding agent.
Use your chosen external coding agent to write a separate proposal directory.
Do not execute generated source on the host.

The proposal has two entries: source/ and params.json.
The source directory must contain builder.py.
Use modular Blender Python and local assets as necessary.
The program starts builder.py with --params FILE --output SCENE.BLEND.
Save the scene to the supplied output path.
Use Blender 4.5.12 and meters. Set scene unit scale to 1.
Give each mesh part a unique semantic_id object property.
Realize instances. Use constant Principled material values.
The source limit is 16 MiB and 512 files.
Permitted extensions: .py, .json, .png, .jpg, .jpeg, .txt, .md.
Do not add hidden files, agent configuration, links, setup scripts, or downloads.
The source job has no network and no project history access.

The context files are fixed evidence, not editable project inputs.
A repair can refer to a rejected model while its execution parent stays accepted.
Preserve parts and regions that the reviewed rules protect.
Propose policy changes separately for operator review.
Generated source cannot change verification rules or declare success.
The operator selects the policy and exact runtime before execution.
The app independently inspects, exports, reopens and checks the saved model.
Machine verification covers the declared checks only.
Human review remains necessary for appearance and uncovered prompt requirements.
