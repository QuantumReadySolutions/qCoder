#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import cirq

from qcoder.engines.feature_extraction.adapters.cirq_intake import (
    extract_features_from_cirq_circuit,
)


def main() -> None:
    out = Path("examples/circuits/bell_cirq_export.qasm")
    out.parent.mkdir(parents=True, exist_ok=True)

    q0, q1 = cirq.LineQubit.range(2)
    circuit = cirq.Circuit(
        cirq.H(q0),
        cirq.CNOT(q0, q1),
        cirq.measure(q0, q1, key="m"),
    )

    fv = extract_features_from_cirq_circuit(circuit)
    feature_map = dict(zip(fv.feature_names, fv.features))
    print(f"schema={fv.schema_version} features={len(feature_map)}")

    out.write_text(cirq.qasm(circuit), encoding="utf-8")
    print(f"wrote {out}")
    print(
        "boundary: structure/export intake only; no simulator/hardware execution, "
        "no LLM calls, no uploads/telemetry/retrieval/embeddings."
    )


if __name__ == "__main__":
    main()
