# 02: Qiskit workflow (optional adapter)

Use this only when you already have a Qiskit `QuantumCircuit` in Python.

## 1) Install with optional extra

```bash
pip install "qcoder[qiskit]"
```

## 2) Build Bell circuit, extract features, and export QASM

```python
from pathlib import Path

from qiskit import QuantumCircuit
from qiskit.qasm2 import dumps

from qcoder.engines.feature_extraction.adapters.qiskit_intake import (
    extract_features_from_qiskit_circuit,
)

qc = QuantumCircuit(2, 2)
qc.h(0)
qc.cx(0, 1)
qc.measure_all()

fv = extract_features_from_qiskit_circuit(qc)
feature_map = dict(zip(fv.feature_names, fv.features))
print(f"schema={fv.schema_version} features={len(feature_map)}")

Path("examples/circuits/bell_qiskit_export.qasm").write_text(
    dumps(qc), encoding="utf-8"
)
```

## 3) Run `qcoder context` on exported QASM

```bash
qcoder context examples/circuits/bell_qiskit_export.qasm \
  --out-json preflight.qiskit.context.json \
  --out-md preflight.qiskit.context.md \
  --guidance --profiles
```

## Boundary reminder

The adapter is structure/export intake only. qCoder does not execute Qiskit simulators/hardware, does not call an LLM, and does not upload or retrieve data.
