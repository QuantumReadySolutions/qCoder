# qCoder

qCoder 0.6.0a24 is a behavior-changing pre-release successor to public qCoder 0.6.0a22. Public
qCoder 0.6.0a22 is its customer upgrade predecessor. Frozen qCoder 0.6.0a23 at commit
`9c984936ab0067d2109eb24b9b1ea072b09b686d` is the implementation lineage predecessor; a23 is
unpublished, consumed, terminal, do-not-publish evidence and is not a customer release.

The a24 product correction basis is commit `75babdcc27f894094f776bc9e3d1382ab9e1496f`,
tree `6887f0fbdf27cfce7c2316f2eed336f663ac2bf2`. That exact basis → a24 relationship
preserves runtime implementation and product behavior except for release identity, release-truth
documentation, mechanically resulting package metadata, and release-only verification. The public
a22 → a24 and terminal a23 → a24 relationships are behavior-changing.

Relative to a23, qCoder 0.6.0a24 corrects the customer-visible distinction between a configured
client workspace and a connected client. Managed setup now reports `qCoder configured`. A bounded
verification command reports `qCoder connected` only after an actual client initializes both
canonical MCP servers, discovers exactly twelve public tools plus two private operations, and
completes a successful read-only qCoder request. Direct server smoke is only a credential and
server-readiness preflight. Evidence Review, Algorithm Blueprint, Current Loop, Binding MCP v12,
Current Step Contract v11, request semantics v5, and state schema v16 are preserved. The umbrella
connected-assistant contract advances from binding v47 / schema 46 to binding v48 / schema 47.

Plain 0.6.0a19 remains intentionally reserved and has no accepted frozen or public candidate.
Plain 0.6.0a20 and plain 0.6.0a21 are immutable, unpublished, technically qualified,
publication-truth-rejected, terminal, do-not-publish candidates. They are retained evidence, not
customer releases or upgrade predecessors, and must not be repaired, rebuilt, replaced, tagged,
published, or selected again.

Frozen qCoder 0.6.0a23 is the sole implementation lineage predecessor for a24. It must not be
published, repaired, rebuilt, replaced, tagged, or treated as a customer release.

## Upgrading from qCoder 0.6.0a22

Install qCoder 0.6.0a24 for a new installation or before starting a new Current Loop. If qCoder
0.6.0a22 already has an active Current Loop, upgrade only at a clean Current Loop boundary:
before a new loop begins or after the current loop has reached a truthful terminal boundary.

Do not upgrade while any binding v45 / Current Step Contract v11 step, completion, continuation
capsule, pending receipt, or recovery action remains outstanding. Finish the outstanding step on
qCoder 0.6.0a22, or explicitly abandon it and restart the work under qCoder 0.6.0a24 at a clean
boundary.

qCoder does not support or claim mid-step migration from binding v45 / Current Step Contract v11
to binding v48 / Current Step Contract v11. A v45/v11 operation receipt, authority grant,
completion input, continuation capsule, or pending step must not be reused or reinterpreted under
v48/v11. Project evidence history may remain; this boundary applies to the active step.

This release makes no latency, speed, p95, responsiveness, overhead, quiet-operation, or
consistency guarantee; does not establish universal framework neutrality, general framework
qualification, or general PennyLane qualification; and does not activate Tested, First-class,
Client Compatibility, CL-023, named-client support, website, or marketing claims. Publication,
deployment, qualification evidence, public applicability, and support claims remain separate
lifecycle and product decisions.

`qcoder` is a local, deterministic quantum circuit evidence CLI.

The current public local path is **qCoder OSS**. OSS commands run locally and do not call hosted services, upload telemetry, or run QPU/simulator jobs.

## Public CLI surface

- `qcoder analyze`
- `qcoder batch`
- `qcoder context`
- `qcoder review` (including the local selected-evidence journey)
- `qcoder blueprint` (machine-local selected-source evidence)
- `qcoder current-loop` (explicit assistant-driven coordination for one current IDE build)
- `qcoder explorer` (Explorer Beta account-backed status/demo/evidence checks)
- `qcoder context-bridge` (token-backed Context Bridge MCP adapter for eligible Explorer users)
- `qcoder student` (temporary compatibility alias for Explorer Beta)
- `qcoder pro` (archived pilot/bootstrap client contract; non-confidential local plumbing only, not a current public product path)

## Current product boundaries

qCoder combines **OSS local commands**, Explorer compatibility commands, and the Context Bridge
adapter for eligible Explorer users. Pro is not launched and is not a current public product path.

- **OSS commands** (`analyze`, `batch`, `context`, `review`) are Apache-2.0, local-first/offline, and useful without an account or token. They do not upload data, call a qCoder hosted service, or run QPU/simulator jobs.
- **Explorer Beta commands** (`qcoder explorer status`, `qcoder explorer demo`, `qcoder explorer evidence`) are account-backed checks for Explorer Beta status, built-in guided evidence samples, and derived-context guided evidence for user-owned OpenQASM 2 artifacts. The older `qcoder student ...` commands remain available as beta compatibility aliases.
- **Context Bridge adapter commands** (`qcoder context-bridge setup`, `qcoder context-bridge verify-connection`, `qcoder context-bridge mcp serve`, `qcoder context-bridge mcp smoke`) are for eligible Explorer users who create a display-once token through Account Center. Support handles revocation and lost-token replacement. Setup configures the canonical two-server 12+2 topology and verifies credential/server readiness. It does not claim that a client connected. Connection requires client-originated initialization, exact discovery, and a successful read-only qCoder request. Client qualification remains separate.
- Explorer Beta custom evidence uses locally derived qCoder context/features. The CLI may read QASM locally, but the hosted request must not include raw QASM, raw source text, local paths, operation lists, raw counts, notebooks, prompts, tokens, auth headers, or cookies.
- Explorer Beta custom evidence is stateless in this v0 slice; it does not create persistent Explorer history.
- **`qcoder pro` bootstrap/workflow commands** are archived pilot/client-contract surfaces. They are not a Pro purchase path, not a current public signup path, and not generally available hosted Pro.
- There is **no generally available production hosted Pro service**, Pro account/token issuance, artifact/source upload, telemetry/training ingest, confidential local analyzer/cards, QPU/provider execution, or launched Pro V0.0 behavior in this public-main surface.
- **No confidential Pro analysis or cards** are bundled in this package. Token-gating is **access control only**, not a secrecy boundary.

## Explorer Context Loop

The complete IDE-first loop is:

**Human Intent → AI-Generated Python → Logical Circuit / QASM → Run Results →
Evidence-Grounded Next Intent**

The user and a connected assistant work through the IDE. The local SDK constructs the circuit. A
simulator, runtime, or QPU produces results only through an externally authorized run. qCoder
reviews bounded evidence from explicitly selected or supplied artifacts, and the user decides what
should govern the next iteration. qCoder does not independently generate the Python, construct or
compile the circuit, execute the run, recover hidden intent, prove correctness, or automatically
adopt a blueprint decision.

The everyday path uses Assist: the customer explicitly activates qCoder for one build, the Current
Loop Contract governs exact authorized output collection and local derivation, and qCoder surfaces
material decisions or separate authority boundaries.
Adaptive generation is the default; Blueprint-required governance is available. Evidence
revisions, snapshots, and current or prior Run Summaries are bounded to that active loop and are
purged on close. The optional local contract editor uses the same canonical contract as the IDE.
Narrowing applies immediately; broadening requires explicit confirmation.

Finish or restart an active qCoder loop before upgrading. The version boundary fails closed
instead of silently reinterpreting old authority data.

Version 0.6.0a24 preserves qCoder 0.6.0a22's routine source terminal-closure behavior and Current
Step Contract v11 while advancing the connected-assistant binding to v48 for truthful connection
state, managed setup, and first-value dialogue. Frozen a23 is consumed, terminal, and
do-not-publish. Plain 0.6.0a19 remains intentionally reserved. Plain 0.6.0a20 and plain
0.6.0a21 remain immutable, unpublished, technically qualified, publication-truth rejected,
terminal, and do-not-publish. Package publication does not activate a named-client support,
compatibility, or performance claim.

Version 0.6.0a18 gives Algorithm Intent clarification recovery one atomic qCoder-supplied
copy-through capsule under binding v44. qCoder 0.6.0a18 is a behavior-changing pre-release
successor to public 0.6.0a16. Package publication does not activate a named-client support claim.
Plain 0.6.0a17 remains immutable historical failure evidence; its release candidate was rejected
and must not be published.

The successor preserves the connected-assistant, adaptive-intent input, coordinator-result, and
vocabulary contracts while retaining a17's causal currentness, strict result-manifest lineage, and
exact selected-path transport. This is a local active-loop compatibility boundary, not a migration
of project history or server-side persistence.

The preserved a17 implementation corrected the a16 mixed-revision limitation. Replacing current source or circuit
evidence invalidates dependent downstream currentness while preserving immutable history. Current
result evidence requires a structured manifest with sufficient causal lineage; bare counts fail
closed, and unknown-lineage manifests remain historical and non-current. Exact customer-selected
paths are transported structurally without repository discovery, and recovery of an already-run
pending completion does not authorize another execution.

### Connected-client qualification

This package does not activate a named-client support claim. Qualification applies only to an
exact scenario, delivery-environment profile, workstyle, and qCoder artifact. Connection, MCP tool
discovery, or evidence for a related client does not establish qualification. One-call help and
direct contract or completion routes do not add persistent memory, project history, repository
discovery, or automatic IDE authority.

For a customer-selected named qCoder workflow, canonical preparatory states are non-terminal. The
connected assistant continues only the already-selected workflow until the named customer outcome
is ready, qCoder reports a genuine blocker, or qCoder reaches a real customer authority or decision
boundary. For Evidence Review, `assistant_context_ready` is preparatory;
`result_review_context_card_ready` is the customer outcome. The assistant must not infer customer
authority, broaden artifact selection, discover files, or chain an unrelated qCoder capability.
Canonical structured `process_and_discard` unambiguously means that no customer artifact is
retained for that operation; qualification evidence remains fail-closed when this semantic state
is absent, ambiguous, contradictory, free-form only, or belongs to another operation.
For Algorithm Intent clarification, qCoder returns one atomic continuation capsule bound to the
exact card, revision, and regenerated internal contract. The assistant copies the capsule unchanged
and may submit only all advertised customer-reviewed unresolved fields plus the explicit review
assertion. Malformed, tampered, stale, cross-card, cross-revision, incomplete, forbidden, and
unauthorized continuations fail closed without raw-value echo or retention.

## Context Bridge inventory

qCoder preserves the existing eight Evidence Review operations and adds four Algorithm Blueprint
operations, for exactly twelve Context Bridge capability tools:

- `get_guided_evidence_context`
- `create_prompt_context`
- `create_evidence_context_pack`
- `create_context_session_card`
- `create_run_readiness_card`
- `create_result_review_context_card`
- `create_next_check_plan`
- `create_single_loop_evidence_diff`
- `create_algorithm_intent_card`
- `create_implementation_blueprint`
- `create_generation_context_pack`
- `create_source_blueprint_alignment_review`

`create_prompt_context` supports `explain`, `review`, `revise`, `troubleshoot`, and `plan_next_checks` modes; omitting the mode preserves the default behavior. Context Bridge uses only evidence explicitly supplied for the current request, processes it without retaining artifacts, and does not scan repositories, edit files, execute circuits or next checks, keep history or memory, score correctness, or perform autonomous work.

## Review current evidence

### Review local evidence

qCoder 0.6.0a15 composes existing canonical qCoder evidence into one local, account-free review.
It reads only the files named explicitly on the command line; it does not
accept a directory, expand a glob, recurse, discover hidden files, follow Python imports, scan a
workspace, start a watcher, or call a network service.

Discover the journey and review fixed public samples:

```bash
qcoder review local-evidence --help
qcoder review local-evidence examples/fixtures/local_evidence_bell.py
qcoder review local-evidence \
  examples/circuits/bell.qasm \
  examples/fixtures/bell_counts_qiskit.json \
  --out-json local-evidence.json \
  --out-md local-evidence.md
qcoder review local-evidence examples/circuits/bell.qasm --local-help
```

The report presents review scope, provenance, bounded QASM and circuit facts, Python-only motif
evidence, the canonical factual Run Summary when supplied results are present, limitations,
unsupported states, share-safe choices, and exact next actions. OpenQASM 2 evidence extraction is
bounded. OpenQASM 3 is recognized but evidence extraction is not supported; it is never passed to
the OpenQASM 2 parser or reported as a complete circuit.

No qCoder account, no qCoder token, no Explorer service, and no MCP connection are required. The
local report does not establish IDE/client qualification. It creates no project memory or hidden
persistence.

Ordinary terminal, JSON, and Markdown reports may contain customer filenames and paths and are
intended for local inspection. Use `--share-safe-json` or `--share-safe-md` before sharing;
share-safe defaults remove filenames, paths, and raw/private artifacts.

Create a derived-only share-safe export explicitly and inspect it before sharing:

```bash
qcoder review local-evidence examples/circuits/bell.qasm \
  --share-safe-json local-evidence.share-safe.json
```

Raw/private categories remain excluded by default. Each applicable category has its own explicit
opt-in, such as `--include-original-qasm`, `--include-source-excerpts`, `--include-raw-counts`,
`--include-customer-filenames`, or `--include-customer-paths`; there is no include-everything
switch and no automatic transmission. On the currently proven POSIX-style path flow, dot-prefixed
selected or resolved path segments are rejected, including hidden symlink targets. Windows hidden
attributes and alternate data streams are not qualified. See
[`docs/local-evidence-review.md`](docs/local-evidence-review.md) for the complete commands and
section meanings.

This section describes behavior present in qCoder 0.6.0a18. Package publication and public client-
claim status remain separate facts governed outside the package documentation.

### Explorer Evidence Review

Evidence Review is an Explorer capability for understanding what explicitly supplied current evidence supports, what remains unproven, what changed within one bounded workflow, and what the user may choose to check next. It uses the existing Context Bridge operations:

- before an external run, use `create_run_readiness_card`;
- for a compact user-provided result summary, use `create_result_review_context_card`;
- for two explicitly supplied points in one workflow, use `create_single_loop_evidence_diff`;
- for ordered user-controlled follow-up, use `create_next_check_plan`;
- for assistant handoff, use `create_prompt_context` with `review`, `troubleshoot`, or `plan_next_checks`.

Core Evidence Review output uses these provenance and evidence-status labels: **Observed**, **User-provided**, **Inferred**, **Assumed**, **Not proven**, and **Suggested next check**. They are not confidence percentages, assurance ratings, or correctness scores. “What the evidence supports” is a bounded interpretation, not independent verification. “What changed” is a descriptive comparison of explicit inputs, not history, causality, or multi-run analysis. Suggested checks remain user-controlled and are not executed by qCoder.

Local qCoder OSS commands provide deterministic local analysis and review artifacts. Circuit
Workbench is the machine-local selected-evidence surface for explicitly supplied artifacts. Explorer
Evidence Review supplies bounded current-session interpretation within the complete Explorer
Context Loop; Context Bridge carries the operations into a client whose connection has been
verified, but does not own the workflow or retain lineage. ChatGPT uses a manual share-safe Prompt Context handoff and is
not a connected Context Bridge client.

See the sanitized [`Evidence Review walkthrough`](examples/08_evidence_review.md).

## Prepare an Algorithm Blueprint

Algorithm Blueprint is an Explorer capability for turning explicitly supplied human intent into a
reviewable, user-confirmed Qiskit-first build contract before code generation, then reviewing
compact static Python evidence against that contract. The current workflow uses:

- `create_algorithm_intent_card` to preserve original intent, provenance, clarification questions,
  and explicit user-reviewed confirmation;
- `create_implementation_blueprint` to return an Implementation Blueprint and a distinct Output
  Evidence Contract without adding another tool;
- `create_generation_context_pack` to prepare requirements for an external, user-selected code
  generation assistant or a manual handoff;
- external, user-controlled Python generation outside qCoder;
- `qcoder blueprint source-evidence` for deterministic machine-local AST extraction from one
  selected `.py` file or bounded stdin; and
- `create_source_blueprint_alignment_review` to review only compact supplied static evidence.

The available profiles are Generic Qiskit Blueprint, Grover Search, and QAOA. Profiles ask
deterministic questions and surface alternatives; they do not silently choose an oracle, QAOA
depth, mixer, optimizer, backend, shots, or parameter strategy. Static motif observations do not
prove algorithm identity, correctness, completeness, executability, or runtime behavior. qCoder
does not scan a repository, import or execute selected source, generate code, edit files, invoke a
simulator/backend/QPU, retain artifacts, or retrieve prior artifacts.

See the synthetic [`Algorithm Blueprint walkthrough`](examples/09_algorithm_blueprint.md).

## Quick start

qCoder 0.6.0a24 is a pre-release. It is not a stable or generally available release. Package
publication and named-client support claims are governed separately. The commands below describe
behavior present in this pre-release; public qCoder 0.6.0a22 remains the public upgrade
predecessor; plain a17 remains a rejected immutable candidate; terminal plain a20, a21, and a23
are not publication targets.

Analyze a circuit:

```bash
qcoder analyze path/to/circuit.qasm --json
```

Create local context and review artifacts:

```bash
qcoder context path/to/circuit.qasm --out-json preflight.context.json --out-md preflight.context.md
qcoder review --counts-json counts.json --format qiskit_counts --preflight-json preflight.context.json --out-json execution.review.json --out-md execution.review.md
qcoder blueprint source-evidence --source-file selected_generated.py
```

Or use the coherent local selected-evidence journey:

```bash
qcoder review local-evidence path/to/selected.py path/to/circuit.qasm path/to/counts.json
```

For artifacts you intend to paste into ChatGPT, Cursor, email, GitHub issues, or support threads, add `--share-safe`:

```bash
qcoder analyze path/to/circuit.qasm --json --share-safe
qcoder context path/to/circuit.qasm --out-json preflight.context.json --out-md preflight.context.md --share-safe
qcoder review --counts-json counts.json --format qiskit_counts --preflight-json preflight.context.json --out-json execution.review.json --out-md execution.review.md --share-safe
```

Share-safe mode is designed for safer sharing: it redacts local paths and token/header-like strings, adds `share_safe=true`, and marks raw QASM/local paths/tokens as not included. Review artifacts before sharing; this is not a guarantee that all sensitive project content has been removed.

Explorer Beta compatibility checks and archived Pro bootstrap:

```bash
qcoder explorer status
qcoder explorer demo
qcoder explorer evidence
qcoder explorer evidence --qasm path/to/circuit.qasm
qcoder explorer evidence --context-json preflight.context.json
qcoder explorer evidence --qasm path/to/circuit.qasm --out-json explorer.json --out-md explorer.md --share-safe
python -m qcoder context-bridge mcp serve --help
python -m qcoder context-bridge mcp smoke --token-file ~/.qcoder/context-bridge/token.txt
qcoder context-bridge setup --workspace /exact/trusted/workspace
qcoder context-bridge verify-connection --workspace /exact/trusted/workspace
python -m qcoder current-loop --help
qcoder pro --help
```

Run the Context Bridge commands in the Python environment where qCoder is installed. The default
smoke is a direct credential/server-readiness preflight; it does not establish a client
connection. Add `--json` for structured troubleshooting, or `--full` for the exhaustive
support/release diagnostic; full mode stops without automatic retry when the current rate window
requires a pause.

Managed setup returns `qCoder configured` after the credential selection and canonical
`qcoder-context-bridge` plus `qcoder-current-loop` definitions are verified. Reload the configured
client, ask it `Use qCoder to check this connection.`, then run `verify-connection` for the same
exact workspace. The verifier waits only when `--wait-seconds` is supplied (maximum 30 seconds),
returns a bounded category on incomplete or invalid evidence, and reports `qCoder connected` only
after that client initializes both servers, discovers exact 12+2, and completes one successful
read-only qCoder request. Add `--json` for sanitized diagnostics. Neither configured nor connected
creates a named-client qualification or support claim.

Connected clients receive an explicit opt-in Current Loop instruction from the local Context Bridge
server. The instruction activates only after the customer asks to use qCoder or accepts an offer,
uses the same configured Python runtime to invoke `qcoder current-loop`, and keeps IDE write/run
permission and exact-artifact review permission separate. It never contains the Context Bridge
token.

**Support-safe checklist**

Safe to share with QRS support:

- `qcoder --version`
- command name
- HTTP status or CLI error code
- `job_id`, if produced
- redacted output
- manifest schema/version

Do not share:

- bearer tokens
- secrets
- source code
- repository archives
- notebooks
- private prompts or chat transcripts
- raw QASM/source artifacts through unsupported paths

Architecture notes: [`docs/architecture.md`](docs/architecture.md).

## Optional extras

```bash
pip install "qcoder[qiskit]"
pip install "qcoder[cirq]"
pip install "qcoder[pennylane]"
```

## License

Apache-2.0 (see `LICENSE` and `NOTICE`).
