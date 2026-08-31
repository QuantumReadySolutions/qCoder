# OpenQASM 3 static evidence

- Schema: `qcoder.openqasm3_static_evidence.v1`
- Parser: `qcoder.openqasm3.bounded_parser.v1`
- Standard-gate vocabulary: `qcoder.openqasm3.stdgates_3_0.v1`
- Declared version: `3.0`
- Selected artifact: `bell.qasm3`
- Source SHA-256: `184dd326ce8be48a625a92bf6d0d37f9847801cdf6f1530f69b3ff7db76908cb`
- Support status: `supported`
- Selection: explicit file argument

## Established declarations

- qubit `q`: size `2`, base `0` (supported)
- bit `c`: size `2`, base `0` (supported)

## Construct classifications

- `construct-0001` include `stdgates.inc`: `supported`
- `construct-0002` qubit_declaration `q`: `supported`
- `construct-0003` bit_declaration `c`: `supported`
- `construct-0004` quantum_operation `h`: `supported`
- `construct-0005` quantum_operation `cx`: `supported`
- `construct-0006` measurement `measure`: `supported`

## Derived facts

- quantum_width: `2` — `exact`
- classical_width: `2` — `exact`
- operation_count: `4` — `exact`
- measurement_count: `2` — `exact`
- depth: `3` — `exact`
- interaction_graph: `[[0, 1]]` — `exact`
- gate_statistics: `{"cx": 1, "h": 1, "measure": 2}` — `exact`

## Limitations

- Only the D-118 bounded static OpenQASM 3.0 subset is interpreted.
- Unsupported, unrecognized, and recovered-malformed regions qualify or withhold dependent facts.
- Custom-gate bodies are preserved structurally and are not recursively expanded.

## Non-claims

- No source or circuit was executed.
- This is not full OpenQASM 3 language support or a language-compliance claim.
- No conversion, semantic equivalence, algorithm correctness, or expected output was established.
- No hardware compatibility, backend suitability, runtime, resource, fidelity, shot-count, or statistical-sufficiency conclusion was established.
- Observed OpenQASM structure does not establish user intent, author intent, or algorithm identity.

This evidence was produced without executing the source or circuit.
