#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from qiskit import QuantumCircuit
from qiskit.qasm2 import dumps

from qcoder.engines.feature_extraction.adapters.qiskit_intake import (
    extract_features_from_qiskit_circuit,
)


def main() -> None:
    out = Path("examples/circuits/bell_qiskit_export.qasm")
    out.parent.mkdir(parents=True, exist_ok=True)

    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure_all()

    fv = extract_features_from_qiskit_circuit(qc)
    feature_map = dict(zip(fv.feature_names, fv.features))
    print(f"schema={fv.schema_version} features={len(feature_map)}")

    out.write_text(dumps(qc), encoding="utf-8")
    print(f"wrote {out}")
    print(
        "boundary: structure/export intake only; no simulator/hardware execution, "
        "no LLM calls, no uploads/telemetry/retrieval/embeddings."
    )


if __name__ == "__main__":
    main()
