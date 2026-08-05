# qCoder architecture notes (public)

**qCoder** maps circuit sources onto repeatable structured output: a `schema_version`, `feature_names`, and paired numeric `features` consumed from the extractor.

- Primary OSS path: OpenQASM / QASM text analyzed on the developer machine.
- Optional OSS path: `qcoder[qiskit]`, `qcoder[cirq]`, and `qcoder[pennylane]` ingest framework exports into the same extractor as OpenQASM.

The field glossary is defined in `src/qcoder/engines/feature_extraction/features/schema_v0.py` (`FEATURE_NAMES_V0`). The qcoder.ai manual summarizes each field name.

## Current public package surface

The public `qcoder` package on `main` ships:

- `qcoder analyze` and `qcoder batch` — deterministic structural extraction for local artifacts.
- Optional `--guidance` — heuristic starting points derived from `feature_map` (non-guaranteed; no backend execution).
- Optional `--profiles` on `analyze --json` and `context` — derived structural taxonomy from `feature_map`.
- `qcoder context` — preflight context artifacts (JSON + Markdown).
- `qcoder review` — post-run review artifacts from user-supplied counts (`qcoder` or `qiskit_counts` formats).
- `qcoder review local-evidence` — one bounded OSS-local presentation composed from existing
  canonical evidence for explicitly selected files; it adds no registry, persistence, or network
  service.
- `qcoder explorer status`, `qcoder explorer demo`, and `qcoder explorer evidence` — primary Explorer Beta commands for account-backed status, built-in evidence, and derived-context custom evidence checks. `qcoder student ...` remains a compatibility alias during beta.
- `qcoder pro` — archived pilot/client-contract plumbing only. Pro is not launched and is not a current public product path.

## OSS boundary

qCoder OSS commands are local/offline after package installation: no LLM calls, no telemetry upload, no QPU/simulator execution, and no card generation in the public package. OSS is the current path for user-owned artifacts.

The local-evidence review accepts explicit files only. It rejects directories, performs no glob or
recursive discovery, does not inspect hidden files or follow imports, and creates no background
state. It composes Development Evidence v0, bounded OpenQASM 2/CircuitIR facts, factual Run Summary
v2, and Help v2. OpenQASM 3 is recognized as unsupported and is not sent through the OpenQASM 2
parser. Active-loop registry semantics remain with Current Loop and are not projected into OSS.

Portable JSON and Markdown artifacts are intended for humans, chat LLMs, and coding tools to consume in user-managed workflows. Ordinary local reports can include customer filenames and paths and are for local inspection; use the applicable share-safe output before sharing. Local OSS artifacts remain independent of hosted integrations. For eligible Explorer users, the separately documented Context Bridge adapter carries bounded current-session Evidence Review tools into Cursor, Claude Code, and Codex. ChatGPT remains a manual share-safe Prompt Context handoff rather than a connected Context Bridge client.

Evidence Review is the Explorer interpretation capability that organizes explicitly supplied evidence into observations, user-provided facts, bounded inferences, assumptions, supported statements, unproven statements, descriptive current-loop changes, and user-controlled next checks. It is not persistence, history, multi-run analysis, repository access, correctness verification, or autonomous execution. Circuit Workbench is a machine-local selected-evidence surface; Context Bridge is the delivery path; the Explorer Evidence Loop is the spanning workflow.

The unreleased Algorithm Blueprint branch adds a guided Explorer build-contract capability on top of that evidence vocabulary. It preserves original intent and provenance, requires explicit user-reviewed confirmation, returns an Implementation Blueprint with a distinct Output Evidence Contract, and creates a Generation Context Pack for code generation outside qCoder. Selected Python Source Evidence is extracted machine-locally with deterministic AST inspection; only compact evidence is eligible for Context Bridge alignment review. Static alignment is not correctness, algorithm identity, circuit construction, or runtime verification. Algorithm Blueprint does not add persistence, source execution, repository discovery, a hosted model, or autonomous generation.

Use `--share-safe` when producing artifacts intended for ChatGPT, Cursor, email, GitHub issues, or support threads. Share-safe mode redacts local paths and token/header-like strings, adds explicit `share_safe` metadata, and marks raw QASM/local paths/tokens as not included. It is designed for safer sharing, but users should still review artifacts before sharing because qCoder cannot guarantee that every sensitive project-specific detail has been removed.

## Explorer Beta boundary

Explorer Beta is the account-backed beta path. The primary public CLI namespace is `qcoder explorer`. During beta, `qcoder student` remains a compatibility alias, and the primary environment variables remain `QCODER_STUDENT_BASE_URL` and `QCODER_STUDENT_TOKEN`.

With no input, `qcoder explorer evidence` uses built-in guided evidence samples. With `--qasm` or `--context-json`, it uses locally derived qCoder context/features for custom guided evidence over a user-owned artifact.

The CLI may read OpenQASM 2 locally, but the Explorer Beta custom evidence request must not include raw QASM, raw source text, local paths, reconstructable operation lists, raw counts, notebooks, prompts, tokens, auth headers, or cookies. The v0 service response is stateless: `persisted=false` and `history_ready=false`.

Raw hosted QASM upload remains out of scope unless a separate privacy and retention design is approved.

## Archived Pro boundary

`qcoder pro` commands are archived pilot/client-contract surfaces. They may store local token/config, validate local package boundaries, or write local dry-run workflow manifests. They do not make Pro purchasable, open, or current.

Token-gating in this slice is access control only, not confidentiality. `qcoder pro workflow --dry-run-manifest` builds a local contract artifact and performs no upload or network calls. Any explicit configured manifest submit is pilot-only, manifest-only, and not a generally available hosted Pro service.

There is no generally available production hosted Pro service, Pro account/token issuance, artifact/source upload, telemetry/training ingest, confidential local analyzer/cards, QPU/provider execution, or launched Pro V0.0 behavior in this public package.

## Canonical schemas

The canonical circuit feature schema remains the nested `features` payload (`schema_version`, `feature_names`, `features`) produced by extraction. Guidance, context, and review outputs are additive artifact layers and do not change canonical feature schema/version/order.

Optional `guidance` and `feature_profiles` blocks are separately versioned and additive. Deterministic guidance values remain authoritative when a bundled local guidance pack is present.

## Product stance

qCoder is an evidence layer for AI-assisted quantum development. It supplies grounded local facts for humans and bring-your-own LLM or IDE workflows, not algorithm identity proofs, correctness proofs, speedup claims, runtime predictions, backend rankings, fidelity claims, or QPU performance claims.

## Release rehearsal

Use `scripts/qcoder-v0-release-check` before any publish action. It builds wheel/sdist, installs the wheel in a clean virtualenv, smokes OSS commands and compatibility shells, and verifies forbidden Pro artifacts are absent from built packages.
