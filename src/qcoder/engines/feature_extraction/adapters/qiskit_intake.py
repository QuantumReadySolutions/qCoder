"""
Optional Qiskit QuantumCircuit intake via OpenQASM 2 export.

Qiskit is imported only when functions in this module are called.
"""

from __future__ import annotations

from typing import Any

from ..features.compute_v0 import FeatureVector, compute_features_v0
from ..ir import CircuitIR
from ..qasm2_regex_parser import parse_qasm2_text


def _load_qiskit() -> tuple[type, Any]:
    try:
        from qiskit import QuantumCircuit
        from qiskit.qasm2 import dumps
    except ImportError as e:
        raise ImportError(
            "qcoder: Qiskit is not installed. "
            "Install with: pip install qiskit  or  pip install 'qcoder[qiskit]' "
            "(optional extra)."
        ) from e
    return QuantumCircuit, dumps


def circuit_ir_from_qiskit(qc: Any) -> CircuitIR:
    """
    Export ``qc`` with ``qiskit.qasm2.dumps`` and parse as OpenQASM 2 text.

    Raises ImportError when Qiskit is not installed (only at call time).
    Raises TypeError if ``qc`` is not a ``qiskit.QuantumCircuit``.
    Raises RuntimeError when export fails or exported text cannot be parsed by qCoder's QASM parser.
    """
    QuantumCircuit, dumps = _load_qiskit()
    if not isinstance(qc, QuantumCircuit):
        raise TypeError(f"expected qiskit.QuantumCircuit, got {type(qc).__name__}")

    try:
        qasm_text = dumps(qc)
    except Exception as e:
        raise RuntimeError(
            "qcoder: OpenQASM 2 export failed via qiskit.qasm2.dumps. "
            "Try a circuit supported by OpenQASM 2 export or inspect the circuit for unsupported constructs."
        ) from e

    try:
        return parse_qasm2_text(qasm_text, source_label="qiskit.qasm2.dumps")
    except Exception as e:  # pragma: no cover - defensive adapter boundary
        raise RuntimeError(
            "qcoder: qiskit.qasm2.dumps exported OpenQASM that qCoder could not parse. "
            "Try simplifying unsupported operations or inspect the exported QASM text."
        ) from e


def extract_features_from_qiskit_circuit(qc: Any) -> FeatureVector:
    """``circuit_ir_from_qiskit`` + ``compute_features_v0`` (same schema as file intake)."""
    ir = circuit_ir_from_qiskit(qc)
    return compute_features_v0(ir)
