# 04: PennyLane workflow (optional adapter)

Use this when your circuit starts as a PennyLane QNode.

## 1) Install with optional extra

```bash
pip install "qcoder[pennylane]"
```

## 2) Build Bell-style QNode, extract features, and export QASM

```python
from pathlib import Path

import pennylane as qml

from qcoder.engines.feature_extraction.adapters.pennylane_intake import (
    extract_features_from_pennylane_circuit,
)

dev = qml.device("default.qubit", wires=2)


@qml.qnode(dev)
def bell():
    qml.Hadamard(wires=0)
    qml.CNOT(wires=[0, 1])
    return qml.expval(qml.PauliZ(0))


fv = extract_features_from_pennylane_circuit(bell)
feature_map = dict(zip(fv.feature_names, fv.features))
print(f"schema={fv.schema_version} features={len(feature_map)}")

exported = qml.to_openqasm(bell, measure_all=True)
qasm_text = exported() if callable(exported) else exported
Path("examples/circuits/bell_pennylane_export.qasm").write_text(
    qasm_text, encoding="utf-8"
)
```

## 3) Run `qcoder context` on exported QASM

```bash
qcoder context examples/circuits/bell_pennylane_export.qasm \
  --out-json preflight.pennylane.context.json \
  --out-md preflight.pennylane.context.md \
  --guidance --profiles
```

## Boundary reminder

The adapter is structure/export intake only. qCoder does not execute PennyLane devices/hardware here, does not call an LLM, and does not upload or retrieve data.
