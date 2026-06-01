# 03: Cirq workflow (optional adapter)

Use this when your circuit starts as a Cirq `Circuit`.

## 1) Install with optional extra

```bash
pip install "qcoder[cirq]"
```

## 2) Build Bell circuit, extract features, and export QASM

```python
from pathlib import Path

import cirq

from qcoder.engines.feature_extraction.adapters.cirq_intake import (
    extract_features_from_cirq_circuit,
)

q0, q1 = cirq.LineQubit.range(2)
circuit = cirq.Circuit(
    cirq.H(q0),
    cirq.CNOT(q0, q1),
    cirq.measure(q0, q1, key="m"),
)

fv = extract_features_from_cirq_circuit(circuit)
feature_map = dict(zip(fv.feature_names, fv.features))
print(f"schema={fv.schema_version} features={len(feature_map)}")

Path("examples/circuits/bell_cirq_export.qasm").write_text(
    cirq.qasm(circuit), encoding="utf-8"
)
```

## 3) Run `qcoder context` on exported QASM

```bash
qcoder context examples/circuits/bell_cirq_export.qasm \
  --out-json preflight.cirq.context.json \
  --out-md preflight.cirq.context.md \
  --guidance --profiles
```

## Boundary reminder

The adapter is structure/export intake only. qCoder does not execute Cirq simulators/hardware, does not call an LLM, and does not upload or retrieve data.
