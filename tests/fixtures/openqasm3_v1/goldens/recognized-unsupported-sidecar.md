# OpenQASM 3 static evidence

- Schema: `qcoder.openqasm3_static_evidence.v1`
- Parser: `qcoder.openqasm3.bounded_parser.v1`
- Standard-gate vocabulary: `qcoder.openqasm3.stdgates_3_0.v1`
- Declared version: `3.0`
- Selected artifact: `timing_calibration_extensions.qasm3`
- Source SHA-256: `407101c45adf37e0999f6258cf1d28a7c9e2ec2bdcb286ca11fc6b65acd953b0`
- Support status: `partial`
- Selection: explicit file argument

## Established declarations

- qubit `q`: size `1`, base `0` (supported)

## Construct classifications

- `construct-0001` qubit_declaration `q`: `supported`
- `construct-0002` timing_delay `delay`: `recognized_but_unsupported`
- `construct-0003` timing_box `box`: `recognized_but_unsupported`
- `construct-0004` duration `duration`: `recognized_but_unsupported`
- `construct-0005` stretch `stretch`: `recognized_but_unsupported`
- `construct-0006` durationof `durationof`: `recognized_but_unsupported`
- `construct-0007` calibration_grammar `defcalgrammar`: `recognized_but_unsupported`
- `construct-0008` calibration `cal`: `recognized_but_unsupported`
- `construct-0009` calibration `defcal`: `recognized_but_unsupported`
- `construct-0010` pragma `pragma`: `recognized_but_unsupported`
- `construct-0011` later_version_construct `nop`: `recognized_but_unsupported`

## Derived facts

- quantum_width: `1` — `exact`
- classical_width: `0` — `exact`
- operation_count: `0` — `lower_bound`
- measurement_count: `0` — `lower_bound`
- depth: `null` — `not_established`
- interaction_graph: `[]` — `partial`
- gate_statistics: `{}` — `partial`

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
