# Evidence Prompt Pack

Selected evidence:
- `selected-evidence-184dd326ce8be48a` — openqasm_3 — SHA-256 `184dd326ce8be48a625a92bf6d0d37f9847801cdf6f1530f69b3ff7db76908cb`

## Supported findings

- Bounded static support status: supported.
- Classical width: 2 (exact static evidence).
- Depth: 2 (exact static evidence).
- Measurement count: 2 (exact static evidence).
- Operation count: 4 (exact static evidence).
- Quantum width: 2 (exact static evidence).
- The explicitly selected input declares OpenQASM 3.0.

## Limitations

- Custom-gate bodies are preserved structurally and are not recursively expanded.
- Only the D-118 bounded static OpenQASM 3.0 subset is interpreted.
- Unsupported, unrecognized, and recovered-malformed regions qualify or withhold dependent facts.

## Unsupported statements

- Execution is outside this static evidence path.
- Full-language compliance, conversion, semantic equivalence, correctness, and expected output were not established.
- Hardware suitability, backend ranking, runtime, resources, fidelity, shot count, and statistical sufficiency were not established.
- Observed OpenQASM structure did not establish intent or algorithm identity.

## Bounded next checks

- Review the bounded diagnostics and select a corrected file if more complete evidence is required.
- qcoder review local-evidence <redacted-local-path> --out-json local-evidence.json

This pack is local, deterministic, share-safe by default, and does not guarantee an assistant's answer.
