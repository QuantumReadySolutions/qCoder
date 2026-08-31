# OpenQASM 3 static-evidence replay

These original qCoder examples are never executed. `bell.qasm3` is fully inside the bounded static
subset. `partial-control-flow.qasm3` deliberately includes an unsupported `if` body so dependent
facts remain qualified and no complete CircuitIR is emitted.

Run the existing local surfaces:

```bash
qcoder review local-evidence examples/openqasm3_static_evidence/bell.qasm3
qcoder review usability-pack \
  examples/openqasm3_static_evidence/bell.qasm3 \
  --out-dir openqasm3-evidence-output
```

The six usability-pack outputs must match `expected/` byte for byte. The prompt pack is a bounded,
share-safe assistant input; it does not guarantee assistant quality. The readiness checklist is an
evidence view, not execution success. The intent card keeps observed structure separate from user
intent. No model, client, service, repository scan, source execution, circuit execution, or
persistent memory is involved.
