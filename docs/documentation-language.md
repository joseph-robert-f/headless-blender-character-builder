# Documentation language

Use ASD-STE100 Issue 9 (2025-01-15) for maintained user-facing prose in this project.
The standard includes writing rules and a dictionary.
Short sentences alone do not show conformity.

Read the official [ASD-STE100 information](https://www.asd-ste100.org/about_STE.html) and [Issue 9 standard](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf).
The repository does not include the standard or its dictionary.
The project checker is not an ASD-approved checker or a certification service.

## Scope

[The scope inventory](documentation-scope.json) identifies each maintained Markdown file and each preserved file.
It also identifies guidance in the CLI, UI, issue forms, configuration examples, schemas, and generated reports.
The packaged `README.md` comes from [HBCB REVIEW PREVIEW](review-preview.md).
Change that source guide before a new package build.

Keep these records without language changes:

- License texts, legal quotations, and third-party notices
- Historical decisions, execution logs, and dated test evidence
- Machine identifiers, commands, paths, versions, hashes, and status codes
- Hash-bound report text that is part of a versioned evidence contract.

Do not change a command to satisfy a prose rule.
Do not translate an existing UI label when the instruction quotes that label.
Do not change old evidence to make it agree with current guidance.
A change to hash-bound report text must include contract-version and migration work.
That work is not part of a documentation-only revision.

Some files contain current instructions and historical records.
The inventory identifies those files and their preserved sections.
Examine the current sections manually.
The checker does not certify their historical text.

## Write and review prose

1. Identify the reader, purpose, and task.
2. Keep the technical meaning, conditions, permissions, risks, and limits.
3. Use the approved dictionary meaning and part of speech for each ordinary word.
4. Use a technical term only for its defined technical meaning.
5. Give instructions in the imperative.
6. Put a necessary condition before its instruction.
7. Use a maximum of 20 words in an instruction sentence.
8. Use a maximum of 25 words in a description sentence.
9. Give each paragraph one topic and a maximum of six sentences.
10. Use active voice when the actor is known.
11. Use one instruction in each sentence unless the actions occur at the same time.
12. Use short noun groups unless the full official technical name is necessary.
13. Do not use contractions, semicolons, or complex verb forms in ordinary prose.
14. Use an `-ing` form only when the standard permits that word or its technical-noun use.
15. Keep safety commands and their consequences together.
16. Examine links and commands after each revision.

A shorter sentence can be incorrect.
For example, an API that binds to loopback does not connect only to loopback.
Binding describes the listener address.
The API can use internal database and storage connections.

Do not change optional advice into a mandatory instruction without authority.
Do not change an unknown test result into a failure or a pass.
Keep the difference between model generation, machine verification, and human acceptance.

## Project technical terms

The terms below identify software, documentation, geometry, or legal concepts.
Their use follows the technical-noun categories in rule 1.5.
A noun entry does not approve a verb, adjective, or adverb with the same spelling.
Use official product names and quoted identifiers without changes.

| Term | Project meaning | Category |
|---|---|---|
| advisory family | The OSV identifiers and aliases for one vulnerability | Computer science, 19 |
| acceptance | A recorded machine or human decision about a model revision | Computer science, 19 |
| API | Application programming interface | Computer science, 19 |
| attempt | A recorded execution of the model-generation pipeline | Computer science, 19 |
| artifact | A file that a build makes as output or evidence | Computer science, 19 |
| artifact tree | The directory structure that contains build artifacts | Computer science, 19 |
| authentication | A check of the caller's identity or credentials | Computer science, 19 |
| backend | The server-side implementation of an operation | Computer science, 19 |
| build | A software operation that makes a model or package | Computer science, 19 |
| candidate | A model revision before acceptance | Computer science, 19 |
| capability | A Linux process privilege or a specified runtime function | Computer science, 19 |
| checksum | A calculated value for file-integrity comparison | Computer science, 19 |
| CLI | Command-line interface | Computer science, 19 |
| commit | A Git source-history record | Computer science, 19 |
| constraint | A mathematical condition for model acceptance | Mathematics, 7 |
| container | An isolated OS process environment | Computer science, 19 |
| corresponding source | Source material applicable to distribution-license obligations | Law, 21 |
| CSRF | Cross-site request forgery | Computer science, 19 |
| daemon | A background system process, such as Docker | Computer science, 19 |
| disposition | An expiring vulnerability decision bound to a target, package, advisory, and evidence | Computer science, 19 |
| disposition context | Runtime-control digest in the image policy identity | Computer science, 19 |
| dependency | Software that a different software component uses | Computer science, 19 |
| descriptor | The project metadata file | Computer science, 19 |
| DCO sign-off | The commit declaration under Developer Certificate of Origin 1.1 | Law, 21 |
| evidence | Data that record a build, test, measurement, or decision | Documentation, 15 |
| fingerprint | Selected geometry, structure, material, or transform data for comparison | Computer science, 19 |
| fixture | Controlled input for a repeatable software test | Computer science, 19 |
| in-place upgrade | A version change against an existing data store without an empty-target restore | Computer science, 19 |
| image digest | The immutable digest of a container image or manifest | Computer science, 19 |
| generator | Software that makes model geometry | Computer science, 19 |
| hash | A calculated digest of specified data | Computer science, 19 |
| Host | The quoted HTTP request-header name | Quoted text, 10 |
| IAM | Identity and access management | Computer science, 19 |
| index | The Git staging record, or a numbered geometry position where specified | Computer science, 19 / mathematics, 7 |
| junction | A Windows filesystem reparse-point directory link | Computer science, 19 |
| lease | Temporary ownership of a resource under a concurrency protocol | Computer science, 19 |
| loopback | The network interface for communication on the same host | Computer science, 19 |
| manifest | A record of artifact identities, properties, and hashes | Computer science, 19 |
| mesh | Vertices, edges, and faces that define model geometry | Mathematics, 7 |
| namespace | A named isolation or identification domain | Computer science, 19 |
| Origin | The quoted HTTP request-header name | Quoted text, 10 |
| outbox | Transactional storage for messages that await queue dispatch | Computer science, 19 |
| pipeline | An ordered set of software-processing stages | Computer science, 19 |
| policy identity | Digest of image content, configuration, labels, revision, and applicable runtime controls | Computer science, 19 |
| policy | A versioned set of acceptance or access rules | Computer science, 19 |
| provenance | Recorded source, runtime, and build identities | Documentation, 15 |
| QA | Quality assurance through defined checks | Documentation, 15 |
| quiescence | Service state with intake stopped and no active build work | Computer science, 19 |
| read-only mode | Access mode that prevents data changes | Computer science, 19 |
| retention | Age-based deletion through the database and specified object versions | Computer science, 19 |
| request | Input for a software operation | Computer science, 19 |
| review | Human examination of a change, model, or evidence | Documentation, 15 |
| rollback | Restoration to a previous software or data state under the documented procedure | Computer science, 19 |
| runtime | The executable software environment | Computer science, 19 |
| sandbox | An isolation boundary for code execution | Computer science, 19 |
| schema | The rules for a data structure | Computer science, 19 |
| semantic ID | The stable identifier for a model part | Computer science, 19 |
| shell | A model surface, or a command interpreter where specified | Mathematics, 7 / computer science, 19 |
| slicer | Software that prepares a model for a 3D printer | Computer science, 19 |
| snapshot | A fixed copy of data at one time | Computer science, 19 |
| state | A software component's recorded condition | Computer science, 19 |
| source bundle | Source files and permitted assets for model construction | Computer science, 19 |
| structural fingerprint | Object names, counts, transforms, bounds, materials, and topology summary used by the stable verifier | Computer science, 19 |
| support | The documented maintenance scope, or physical model supports where specified | Product support, 20 / engineering, 7 |
| symlink | A filesystem symbolic link | Computer science, 19 |
| winding | The order of vertices that defines a mesh face orientation | Mathematics, 7 |
| topology | Connectivity of mesh vertices, edges, and faces | Mathematics, 7 |
| trust boundary | The limit between components with different authority | Computer science, 19 |
| UI | User interface | Computer science, 19 |
| verification | Comparison of software evidence with defined requirements | Computer science, 19 |
| worker | The process that executes queued build jobs | Computer science, 19 |

Read [Character and request contract](character-spec.md) and [Source-directed modeling](experimental-source-modeling.md) for the measurements in each fingerprint.
The term does not imply full shape equivalence.
Read [Dependency maintenance](dependency-maintenance.md) and [Deployment](deployment.md) for policy identity, disposition, and recovery contracts.

Technical verbs follow rule 1.12 and the ordinary verb-form rules.
Use an approved ordinary verb when it gives the same precise meaning.
Use these computer-process verbs only for the specified operations:

| Verb | Permitted technical use |
|---|---|
| bind | Assign a server listener to an address, or attach a hash to its recorded data |
| build | Execute the named software build operation |
| cache | Store validated data for subsequent reuse |
| compile | Translate source into executable or intermediate code |
| deserialize | Convert serialized input into an in-memory data structure |
| download / upload | Transfer files through the specified computer interface |
| execute / run | Start the specified program, command, or test |
| export / import | Convert or load data through a specified software-format operation |
| hash | Calculate the specified cryptographic digest |
| merge | Combine Git history through the named Git operation |
| normalize | Convert data to the contract's canonical representation |
| initialize | Set up the specified software state or resource |
| parse | Interpret input according to its syntax |
| poll | Send repeated status queries through a software protocol |
| quiesce | Stop service intake and get an idle state for maintenance |
| render | Calculate an image from a 3D scene |
| sign | Make a cryptographic signature for the specified software artifact |
| stage | Add a file to the Git index or a defined temporary publication area |
| serialize | Convert data into a specified storage or transport format |
| validate | Apply schema or software-contract rules to input |
| vendor | Put dependency source in the build's vendor tree |
| verify | Execute the defined artifact or evidence verification procedure |

These entries do not permit arbitrary synonyms or general-purpose jargon.
For a new term, record its meaning, part of speech, applicable category, and source contract.
Examine each occurrence in context.

## Local checks and limits

From the repository root, run:

```sh
./scripts/check-documentation-language
python3 -m unittest discover -s tests/documentation -v
```

For a focused check, give one or more Markdown paths to the script.
Use `--inventory-only` to examine Markdown coverage.
The checker finds selected sentence, paragraph, contraction, punctuation, and verb-form problems.
It treats code fences and identifiers as literal data.
Its word counts are estimates.

The checker does not validate the full dictionary, parts of speech, approved meanings, noun groups, or all technical-term uses.
It cannot reliably identify each procedural sentence or distinguish a condition from a description.
It does not validate safety meaning or the truth of a claim.
A human must do those checks against the official standard and the software behavior.
Do not describe a heuristic pass as full conformity or certification.
