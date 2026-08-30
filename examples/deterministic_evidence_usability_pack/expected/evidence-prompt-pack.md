# Evidence Prompt Pack

Selected evidence:
- `selected-evidence-ae0cd14257479613` — openqasm_2 — SHA-256 `ae0cd142574796138ef95bd28378ae0a56b611999e3e31369cdacefe51a7b825`
- `selected-evidence-f0b51fc97bc92568` — python_qiskit_source — SHA-256 `f0b51fc97bc9256872868b5b23dc4448a105e73c0c8cb46a2ef09036e85c80f6`

## Supported findings

- Circuit width 2, depth 2, operation count 4, and measurement count 2 were deterministically established within parser bounds.
- Observed motif structures: qiskit.circuit.construction, qiskit.measurement.mapping, qiskit.controlled.operations.
- The explicitly selected Python file was parsed with bounded static AST inspection.
- The input declares OpenQASM 2.0.

## Limitations

- Circuit stage identity is not guessed from structure.
- Repeated operations are not inferred to be a semantic repeated region.
- Static QASM2 syntax only; custom or unsupported statements may be summarized as custom.
- Static source evidence does not prove implementation correctness, completeness, algorithm identity, constructed-circuit behavior, target compatibility, or runtime behavior.

## Unsupported statements

- A structural Grover or QAOA match does not establish complete or correct algorithm identity.
- Circuit correctness, runtime behavior, output-state entanglement, and algorithm identity were not established.
- Constructed circuit behavior, runtime behavior, and result causation were not established.
- No motif evidence was inferred from QASM.

## Bounded next checks

- Supply counts JSON to review factual run results.
- qcoder review local-evidence <redacted-local-path> --python-profile generic_qiskit --out-json local-evidence.json
- Supply an exported OpenQASM 2 file to review constructed circuit facts.
- Supply counts JSON separately to review supplied run evidence.
- qcoder review local-evidence <redacted-local-path> --out-json local-evidence.json

This pack is local, deterministic, share-safe by default, and does not guarantee an assistant's answer.
