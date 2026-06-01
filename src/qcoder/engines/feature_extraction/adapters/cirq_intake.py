"""
Optional Cirq Circuit intake via OpenQASM 2 export.

Cirq is imported only when functions in this module are called.
"""

from __future__ import annotations

from typing import Any

from ..features.compute_v0 import FeatureVector, compute_features_v0
from ..ir import CircuitIR
from ..qasm2_regex_parser import parse_qasm2_text


def _load_cirq() -> tuple[type, Any]:
    try:
        from cirq import Circuit, qasm
    except ImportError as e:
        raise ImportError(
            "qcoder: Cirq is not installed. "
            "Install with: pip install cirq-core  or  pip install 'qcoder[cirq]' "
            "(optional extra)."
        ) from e
    return Circuit, qasm


def circuit_ir_from_cirq(circuit: Any) -> CircuitIR:
    """
    Export ``circuit`` with ``cirq.qasm`` and parse as OpenQASM 2 text.

    Raises ImportError when Cirq is not installed (only at call time).
    Raises TypeError if ``circuit`` is not a ``cirq.Circuit``.
    Raises RuntimeError when exported text cannot be parsed by qCoder's QASM parser.
    """
    Circuit, qasm = _load_cirq()
    if not isinstance(circuit, Circuit):
        raise TypeError(f"expected cirq.Circuit, got {type(circuit).__name__}")

    qasm_text = qasm(circuit)
    try:
        return parse_qasm2_text(qasm_text, source_label="cirq.qasm")
    except Exception as e:  # pragma: no cover - defensive adapter boundary
        raise RuntimeError(
            "qcoder: cirq.qasm exported OpenQASM that qCoder could not parse. "
            "Try simplifying unsupported operations or inspect the exported QASM text."
        ) from e


def extract_features_from_cirq_circuit(circuit: Any) -> FeatureVector:
    """``circuit_ir_from_cirq`` + ``compute_features_v0`` (same schema as file intake)."""
    ir = circuit_ir_from_cirq(circuit)
    return compute_features_v0(ir)

