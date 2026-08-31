# OpenQASM 3 static evidence

- Schema: `qcoder.openqasm3_static_evidence.v1`
- Parser: `qcoder.openqasm3.bounded_parser.v1`
- Standard-gate vocabulary: `qcoder.openqasm3.stdgates_3_0.v1`
- Declared version: `3.0`
- Selected artifact: `control_flow.qasm3`
- Source SHA-256: `e449377bf01e6635bf892a94ab877217c37a864600b6201df0737c8bbb1d1250`
- Support status: `partial`
- Selection: explicit file argument

## Established declarations

- qubit `q`: size `2`, base `0` (supported)

## Construct classifications

- `construct-0001` include `stdgates.inc`: `supported`
- `construct-0002` qubit_declaration `q`: `supported`
- `construct-0003` quantum_operation `h`: `supported`
- `construct-0004` control_flow_if `if`: `recognized_but_unsupported`
- `construct-0005` control_flow_else `else`: `recognized_but_unsupported`
- `construct-0006` quantum_operation `cx`: `supported`

## Derived facts

- quantum_width: `2` — `exact`
- classical_width: `0` — `exact`
- operation_count: `2` — `lower_bound`
- measurement_count: `0` — `lower_bound`
- depth: `null` — `not_established`
- interaction_graph: `[[0, 1]]` — `partial`
- gate_statistics: `{"cx": 1, "h": 1}` — `partial`

## Limitations

- Only the D-118 bounded static OpenQASM 3.0 subset is interpreted.
- Unsupported, unrecognized, and recovered-malformed regions qualify or withhold dependent facts.
- Custom-gate bodies are preserved structurally and are not recursively expanded.
- The selected file is partial evidence and is not a complete CircuitIR projection.

## Non-claims

- No source or circuit was executed.
- This is not full OpenQASM 3 language support or a language-compliance claim.
- No conversion, semantic equivalence, algorithm correctness, or expected output was established.
- No hardware compatibility, backend suitability, runtime, resource, fidelity, shot-count, or statistical-sufficiency conclusion was established.
- Observed OpenQASM structure does not establish user intent, author intent, or algorithm identity.

This evidence was produced without executing the source or circuit.
