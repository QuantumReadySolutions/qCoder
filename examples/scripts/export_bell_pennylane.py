#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import pennylane as qml

from qcoder.engines.feature_extraction.adapters.pennylane_intake import (
    extract_features_from_pennylane_circuit,
)


def main() -> None:
    out = Path("examples/circuits/bell_pennylane_export.qasm")
    out.parent.mkdir(parents=True, exist_ok=True)

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
    out.write_text(qasm_text, encoding="utf-8")
    print(f"wrote {out}")
    print(
        "boundary: structure/export intake only; no simulator/hardware execution, "
        "no LLM calls, no uploads/telemetry/retrieval/embeddings."
    )


if __name__ == "__main__":
    main()
