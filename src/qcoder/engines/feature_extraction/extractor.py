from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .features.compute_v0 import FeatureVector, compute_features_v0
from .ir import CircuitIR
from .labeling import infer_function
from .parsers import parse_circuit_file


@dataclass(frozen=True)
class CircuitExample:
    id: str | None
    name: str | None
    function_hint: str           # small normalized label
    function_source: str         # "name" | "qasm" | "unknown"
    qasm_path: str
    ir: CircuitIR
    global_features: FeatureVector


def extract_example(
    qasm_path: str,
    *,
    circuit_id: str | None = None,
    circuit_name: str | None = None,
) -> CircuitExample:
    p = Path(qasm_path)
    ir = parse_circuit_file(str(p))
    fv = compute_features_v0(ir)

    function_hint, function_source = infer_function(circuit_name, ir)

    return CircuitExample(
        id=circuit_id,
        name=circuit_name,
        function_hint=function_hint,
        function_source=function_source,
        qasm_path=str(p),
        ir=ir,
        global_features=fv,
    )
