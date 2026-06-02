# qCoder architecture notes (public)

**qCoder** maps circuit sources onto **repeatable structured output**: a **`schema_version`**, **`feature_names`**, and paired numeric **`features`** consumed from the extractor.

- Primary path: **OpenQASM / QASM** text analyzed on the developer machine.
- Optional path: **`qcoder[qiskit]`**, **`qcoder[cirq]`**, and **`qcoder[pennylane]`** ingest framework exports into the **same extractor** as OpenQASM.

The field glossary is defined in **`src/qcoder/engines/feature_extraction/features/schema_v0.py`** (`FEATURE_NAMES_V0`). The [qcoder.ai manual — Feature reference](https://qcoder.ai/manual/feature-reference/) summarizes each field name.

## Public package surface (Option 3)

The public `qcoder` package on `main` ships:

- **`qcoder analyze`** and **`qcoder batch`** — deterministic structural extraction.
- Optional **`--guidance`** — heuristic starting points derived from `feature_map` (non-guaranteed; no backend execution).
- Optional **`--profiles`** on **`analyze --json`** and **`context`** — derived structural taxonomy from `feature_map`.
- **`qcoder context`** — preflight context artifacts (JSON + Markdown).
- **`qcoder review`** — post-run review artifacts from user-supplied counts (`qcoder` or `qiskit_counts` formats).
- **`qcoder pro`** — **service-backed Pro bootstrap shell** (`signup`, `login`, `install`, `status`, `validate`, `workflow` dry-run manifest + hosted stub). Local commands provide non-confidential entitlement/bootstrap plumbing only; confidential Pro analysis and cards are **not** bundled in this package.

Free commands are **local/offline**: no LLM calls, no telemetry upload, no QPU/simulator execution, and no card generation in the public package.

Token-gating in this slice is access control only, not a secrecy boundary. `qcoder pro workflow --dry-run-manifest` builds a local contract artifact and performs no upload or hosted execution. Source file contents are not included. The hosted Pro engine is not implemented in the public repo line yet.

## Canonical schemas

The canonical circuit feature schema remains the nested **`features`** payload (`schema_version`, `feature_names`, `features`) produced by extraction. Guidance, context, and review outputs are additive artifact layers and do not change canonical feature schema/version/order.

Optional **`guidance`** and **`feature_profiles`** blocks are separately versioned and additive. Deterministic guidance values remain authoritative when a bundled local guidance pack is present.

## Product stance

qCoder is a **local evidence layer** for AI-assisted quantum development. It supplies grounded local facts for humans and bring-your-own (BYO) LLM workflows — not algorithm identity proofs, correctness proofs, speedup claims, or QPU performance claims.

Public Free qCoder focuses on **structure and user-supplied execution counts**. Pro Preview (paid product offered free during Preview) will add card-enabled analysis through a protected service boundary; that logic is not distributed in PyPI wheels or this public source tree. The dry-run workflow manifest is a bootstrap/public contract surface, not the sellable hosted Pro product.

## Local Pro / cards

Local private-alpha Pro implementation (cards, MCP tools, and confidential analysis commands) is **not** distributed in this public repository or PyPI package. **`qcoder pro`** in this release is a service-backed bootstrap shell only.

## Release rehearsal

Use **`scripts/qcoder-v0-release-check`** before any publish action. It builds wheel/sdist, installs the wheel in a clean virtualenv, smokes Free commands and the Pro Preview shell, and verifies forbidden Pro artifacts are absent from built packages.
