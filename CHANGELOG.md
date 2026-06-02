# Changelog

All notable changes to this project will be documented in this file.

The format is based on common practice for pre-1.0 semantic versioning: **`MAJOR.MINOR.PATCH`** with **`aN`** for alpha prereleases.

## Unreleased

### Added

- Add public-safe qCoder Pro bootstrap plumbing: local token config, install/login/status/validate, no confidential Pro analysis bundled.
- Add `qcoder pro workflow --dry-run-manifest` public contract/bootstrap output: local manifest generation with QASM hashes/bytes plus local Free analysis, no upload, no hosted execution, and no confidential Pro analysis bundled.
- Add explicit manifest-only service submit path: `qcoder pro workflow --submit` with `--service-url` override and optional `--manifest-out`; submit remains opt-in, strips sensitive fields/paths, and does not implement artifact upload/background upload/confidential local analysis.

## 0.5.0a1 (alpha — public Free + Pro Preview shell)

First public package version for the **Option 3 product line**: local/offline Free CLI plus a service-backed Pro Preview shell. Version **`0.5.0a1`** is distinct from the internal frozen local private-alpha RC **`0.4.0a4`** (not shipped here).

### Changed

- **Package version** — public Free + service-backed Pro Preview shell ships as **`0.5.0a1`**.
- **Public package** — Free local/offline CLI (`analyze`, `batch`, `context`, `review`) with no cards; confidential local Pro implementation is not included.
- **`qcoder pro` shell** — service-backed Pro Preview stub (`signup`, `status`, `login`, `workflow`); no local cards or Pro analysis in the wheel.
- **Release-check** — public Free + Pro shell smoke; wheel/sdist scanned for forbidden Pro artifacts.

### Scope / boundaries

- Free qCoder remains local/offline and useful without Pro.
- Pro Preview service is not implemented in this repository slice.

---

## 0.4.0a2 (alpha)

### Added

- **Local Guidance Pack shadow metadata** — optional **`guidance_metadata`** records the bundled local resource-guidance candidate pack, including pack identity, version/hash metadata, caveats, and **`shadow_guidance`** with **`applied: false`**; deterministic guidance remains authoritative.

### Improved

- **Free Single-Run Intelligence** and **BYO LLM** artifact examples clarify that shadow guidance is metadata only.
- **Release notes** — this alpha has no hosted qCoder compute, no telemetry upload, no qCoder-hosted LLM, no runtime ML dependency, and no optimality, fidelity, runtime, hardware, backend-ranking, or causal-savings claims.

## 0.4.0a1 (alpha)

qCoder **0.4.0a1** adds opt-in derived **feature profiles**, mixed-width **review** checks, and a **5‑minute preflight→review** path.

### Added

- **`--profiles`** on **`qcoder analyze --json`** and **`qcoder context`** — deterministic derived **`feature_profiles`** from **`feature_map`**, emitted with **`feature_profiles_schema_version: "0.1"`** and **`basis: "deterministic_formula_from_feature_map"`**; **`not_guarantees: true`**.
- **`bitstring_width_consistency`** check in **`qcoder review`** — warns when observed bitstring key lengths disagree; derived metrics still use observed counts (also covers **`qcoder`** and **`qiskit_counts`** normalization paths).

### Improved

- **README — First 5 minutes** — quick install → Bell QASM → **`qcoder context --guidance --profiles`** → **`qcoder review`** with sample counts.
- **`examples/`** — Bell OpenQASM, illustrative counts fixture, copy-paste workflow docs, and optional **Qiskit / Cirq / PennyLane** export scripts (structure/export only).
- **Profile label polish** — `connected_small_graph` for tiny circuits instead of misleading `connected_high_density`; **`statevector_scale`** tier key (replacing `circuit_width`); **`llm_summary_profile`** rendered as short sub-bullets in preflight Markdown.
- **Execution review Markdown** — explicit that counts are user-provided and qCoder did not execute the circuit; **Assumptions and Limits** section when present.

### Unchanged / scope

- **Canonical feature schema** — same version, field order, and feature vector layout as **`0.3.0a1`** (`schema_v0`/compute path); profiles are additive only and do not alter canonical **`features`**.

### Local-only boundaries

- No LLM calls, telemetry, uploads, retrieval, or embeddings; no simulator or hardware execution, transpilation, or runtime execution in these CLI flows. Artifacts are local files under your control.

## 0.3.0a1 (alpha)

Optional Cirq and PennyLane intake alongside the existing Qiskit adapter. All adapters follow the same structural rules: framework object → OpenQASM 2 text → qCoder's shared parser pipeline.

### Added

- **`qcoder[cirq]`** — optional **Cirq** `Circuit` intake via OpenQASM 2 export (`cirq.qasm`) into the same canonical extractor used for `.qasm` files.
- **`qcoder[pennylane]`** — optional **PennyLane** intake (`QNode`, and **`QuantumScript`** where the installed version exposes it) via OpenQASM 2 export into the same canonical extractor used for `.qasm` files.

### Changed

- **Adapter error handling** — Qiskit intake wraps **`qiskit.qasm2.dumps`** failures and QASM-parse failures at the adapter boundary in actionable **`RuntimeError`** messages aligned with Cirq and PennyLane adapters.

### Unchanged / scope

- **Canonical feature schema** — same version, field order, and feature vector layout as **`0.2.0a1`** (`schema_v0`/compute path).
- **Intake semantics** — Qiskit, Cirq, and PennyLane adapters are **structure/export intake only**: no transpiler upload, execution, simulator/hardware runs, telemetry, LLM calls, retrieval, or embeddings inside qCoder for these flows.

## 0.2.0a1 (alpha)

Local-only deterministic CLI tooling for quantum circuit analysis and LLM-ready workflow artifacts.

### Added

- **CLI help fixes** — consistent subcommands and help text (`analyze`, `batch`, `context`, `review`).
- **`feature_map`** — derived `name → value` view alongside canonical nested `features` in machine-readable analyze output for readability.
- **`--guidance`** — optional heuristic resource guidance on `qcoder analyze` and `qcoder batch` for shot budgets and simulator / MPS starting points (deterministic from structure only; non-guaranteed).
- **`qcoder context`** — preflight artifacts as **Markdown + JSON** (optional `--guidance`, optional **`--full-features`** glossary appendix).
- **`qcoder review`** — post-execution artifacts as **Markdown + JSON** from user-supplied counts; optional linkage to preflight JSON.
- **`qcoder.counts.v0`** counts schema and **`qiskit_counts`** normalization into the same deterministic review pipeline.
- **Feature glossary** — short deterministic definitions aligned with schema v0 feature names; surfaced in context bundles and **`--full-features`** appendix.
- **Conservative `shots_total` handling** — when declared `shots_total` disagrees with `sum(counts)`, review-derived probabilities use the observed sum, with explicit **`shots_total_match` check**, warning text, and `declared_shots_total` / `shots_total_basis` fields.

### Behaviour

- **Local-only** — no LLM calls, no telemetry, no network, no retrieval or embeddings, no simulator or hardware execution within these CLI flows. Artifacts are files for you to attach or paste into tools of your choice.

### Unchanged

- Canonical circuit feature schema (version, order, and vector layout in `features`) is unchanged for this release.
