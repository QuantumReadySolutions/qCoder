# Review local evidence

A bounded local qCoder OSS review of only the files explicitly selected on the command line.

## Review scope

- Selected artifacts: `1`
- Inspected: explicitly listed files only
- Deliberately not inspected: directories, hidden files, imports, the workspace, or related files
- Network access: `false`
- Persistent project state: `false`

## Provenance

- Artifact 1: `<redacted-local-path>` — kind `openqasm_3`, status `established_with_qualifications`
  - Inspected: OpenQASM 3 version and lexical structure, bounded supported declarations and operations, construct support classifications, derived-fact exactness, complete CircuitIR boundary
  - Established: The explicitly selected input declares OpenQASM 3.0.
  - Established: Bounded static support status: supported.
  - Established: Quantum width: 2 (exact static evidence).
  - Established: Classical width: 2 (exact static evidence).
  - Established: Operation count: 4 (exact static evidence).
  - Established: Measurement count: 2 (exact static evidence).
  - Established: Depth: 2 (exact static evidence).
  - Not established: Execution is outside this static evidence path.
  - Not established: Full-language compliance, conversion, semantic equivalence, correctness, and expected output were not established.
  - Not established: Hardware suitability, backend ranking, runtime, resources, fidelity, shot count, and statistical sufficiency were not established.
  - Not established: Observed OpenQASM structure did not establish intent or algorithm identity.

## QASM evidence

- Artifact 1: `openqasm_3` — `established_with_qualifications`
  - The explicitly selected input declares OpenQASM 3.0.
  - Bounded static support status: supported.
  - Quantum width: 2 (exact static evidence).
  - Classical width: 2 (exact static evidence).
  - Operation count: 4 (exact static evidence).
  - Measurement count: 2 (exact static evidence).
  - Depth: 2 (exact static evidence).
  - Execution is outside this static evidence path.
  - Full-language compliance, conversion, semantic equivalence, correctness, and expected output were not established.
  - Hardware suitability, backend ranking, runtime, resources, fidelity, shot count, and statistical sufficiency were not established.
  - Observed OpenQASM structure did not establish intent or algorithm identity.

## Circuit facts

- Artifact 1 bounded OpenQASM 3 static facts:
  - quantum_width: `2` — `exact`
  - classical_width: `2` — `exact`
  - operation_count: `4` — `exact`
  - measurement_count: `2` — `exact`
  - depth: `2` — `exact`
  - interaction_graph: `[[0, 1]]` — `exact`
  - gate_statistics: `{'cx': 1, 'h': 1, 'measure': 2}` — `exact`
  - complete CircuitIR: `True`
- Artifact 1 deterministic metrics:
  - width: `2`
  - classical_width: `2`
  - depth: `2`
  - operation_count: `4`
  - gate_count: `2`
  - multi_qubit_gate_count: `1`
  - measurement_count: `2`

## Motif evidence

- No Python/Qiskit source was selected; QASM and results do not emit motifs.

## Factual Run Summary

- No supported supplied-counts or run-result artifact was selected.

## Revision evidence

- No explicit current/prior relationship was supplied; none was inferred.

## Warnings and unsupported state

- Artifact 1: Only the D-118 bounded static OpenQASM 3.0 subset is interpreted.
- Artifact 1: Unsupported, unrecognized, and recovered-malformed regions qualify or withhold dependent facts.
- Artifact 1: Custom-gate bodies are preserved structurally and are not recursively expanded.

## Bounded local planning guidance

- Status: `not_requested`
- This section is separate from evidence facts.
- It is not optimality proof, fidelity proof, backend ranking, causal savings, or a protected recommendation.

## Share-safe export

A derived-only share-safe JSON or Markdown export is available only when requested.
Raw or private categories require separate explicit opt-ins. Inspect every export before sharing.
No export is transmitted automatically.

## Supported next actions

- `qcoder review local-evidence <redacted-local-path>`
- `qcoder review local-evidence <redacted-local-path> --out-json local-evidence.json`
- `qcoder review local-evidence <redacted-local-path> --share-safe-json local-evidence.share-safe.json`
- `qcoder review local-evidence <redacted-local-path> --local-help`

## Local qCoder Help

- Installed qCoder version: `0.6.0a24.post0.dev9+semantic.only.first.value.v1`
- Mode: local OSS; no qCoder account, qCoder token, Explorer service, or MCP is required.
- This evidence review does not establish qualification for an IDE or assistant client.

