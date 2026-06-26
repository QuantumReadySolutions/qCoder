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
- `qcoder student status`, `qcoder student demo`, and `qcoder student evidence` — temporary Explorer Beta compatibility commands for account-backed status, built-in evidence, and derived-context custom evidence checks.
- `qcoder pro` — archived pilot/client-contract plumbing only. Pro is not launched and is not a current public product path.

## OSS boundary

qCoder OSS commands are local/offline after package installation: no LLM calls, no telemetry upload, no QPU/simulator execution, and no card generation in the public package. OSS is the current path for user-owned artifacts.

Portable JSON and Markdown artifacts are intended for humans, chat LLMs, and agentic IDEs to consume in user-managed workflows. Productized Cursor, Claude Code, Codex, or MCP integration is not part of this public package surface unless separately implemented and documented.

## Explorer Beta boundary

Explorer Beta is the account-backed beta path. During beta, the public CLI compatibility namespace remains `qcoder student`, and the primary environment variables remain `QCODER_STUDENT_BASE_URL` and `QCODER_STUDENT_TOKEN`.

With no input, `qcoder student evidence` uses built-in guided evidence samples. With `--qasm` or `--context-json`, it uses locally derived qCoder context/features for custom guided evidence over a user-owned artifact.

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
