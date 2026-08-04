# qCoder

`qcoder` is a local, deterministic quantum circuit evidence CLI.

The current public local path is **qCoder OSS**. OSS commands run locally and do not call hosted services, upload telemetry, or run QPU/simulator jobs.

## Public CLI surface

- `qcoder analyze`
- `qcoder batch`
- `qcoder context`
- `qcoder review`
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
- **Context Bridge adapter commands** (`qcoder context-bridge mcp serve`, `qcoder context-bridge mcp smoke`) are for eligible Explorer users who create a display-once token through Account Center. Support handles revocation and lost-token replacement. The adapter exposes bounded current-evidence context tools to configured Cursor, Claude Code, and Codex clients and reads the token from a local token file.
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

The everyday path uses Assist with quiet operation: the customer explicitly activates qCoder for
one build, the Current Loop Contract governs exact authorized output collection and local
derivation, and qCoder interrupts only for material decisions or separate authority boundaries.
Adaptive generation is the default; Blueprint-required governance is available. Evidence
revisions, snapshots, and current or prior Run Summaries are bounded to that active loop and are
purged on close. The optional local contract editor uses the same canonical contract as the IDE.
Narrowing applies immediately; broadening requires explicit confirmation.

### Upgrading an active Current Loop

qCoder 0.6.0a8 is an unpublished source candidate that preserves the exact reviewed 0.6.0a7
runtime and corrects only version and release-history metadata. It is not published, accepted,
qualified, deployed, the current public release, or publicly installable. Version 0.6.0a7 was
frozen, terminally rejected, retained, and unpublished because of an immutable candidate-control
truthfulness defect. Version 0.6.0a6 remains frozen, rejected, retained, and unpublished. Neither
candidate may be rebuilt, replaced, relabeled, or used as a customer installation pin. The
published 0.6.0a5 release remains the current official public release. Finish or restart an active
qCoder loop before upgrading once a corrected release is published. An outstanding pre-v4
operation receipt cannot be reused. When an old receipt is outstanding, the IDE must provide a
fresh authority grant for the new runtime. qCoder fails closed instead of silently reinterpreting
old authority data. This is a local active-loop compatibility boundary, not a migration of project
history or server-side persistence.

### Connected-client qualification

- **Cursor Desktop:** full active Current Loop support.
- **Cursor terminal/CLI:** connection and Desktop parity are distinct; full active-loop support is
  not claimed.
- **Codex CLI and Claude Code:** only exact-release bounded capabilities may be claimed after their
  separate client proofs; full active-loop support is not claimed here.
- **Generic MCP clients:** no support claim.

Connection alone is not qualification. One-call help and direct contract or completion routes do
not add persistent memory, project history, repository discovery, or automatic IDE authority.

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

Evidence Review is an Explorer capability for understanding what explicitly supplied current evidence supports, what remains unproven, what changed within one bounded workflow, and what the user may choose to check next. It uses the existing Context Bridge operations:

- before an external run, use `create_run_readiness_card`;
- for a compact user-provided result summary, use `create_result_review_context_card`;
- for two explicitly supplied points in one workflow, use `create_single_loop_evidence_diff`;
- for ordered user-controlled follow-up, use `create_next_check_plan`;
- for assistant handoff, use `create_prompt_context` with `review`, `troubleshoot`, or `plan_next_checks`.

Core Evidence Review output uses these provenance and evidence-status labels: **Observed**, **User-provided**, **Inferred**, **Assumed**, **Not proven**, and **Suggested next check**. They are not confidence percentages, assurance ratings, or correctness scores. “What the evidence supports” is a bounded interpretation, not independent verification. “What changed” is a descriptive comparison of explicit inputs, not history, causality, or multi-run analysis. Suggested checks remain user-controlled and are not executed by qCoder.

Local qCoder OSS commands provide deterministic local analysis and review artifacts. Circuit
Workbench is the machine-local selected-evidence surface in supported Cursor setup. Explorer
Evidence Review supplies bounded current-session interpretation within the complete Explorer
Context Loop; Context Bridge carries the operations into supported coding clients but does not own
the workflow or retain lineage. ChatGPT uses a manual share-safe Prompt Context handoff and is
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
- `create_generation_context_pack` to prepare requirements for code generation in Cursor, Claude
  Code, Codex, or a manual ChatGPT handoff;
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

Install:

```bash
python -m pip install "qcoder==0.6.0a5"
```

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
python -m qcoder current-loop --help
qcoder pro --help
```

Run the Context Bridge commands in the Python environment where qCoder is installed. The default smoke prints a concise connection result. Add `--json` for structured troubleshooting, or `--full` for the exhaustive support/release diagnostic; full mode stops without automatic retry when the current rate window requires a pause.

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
