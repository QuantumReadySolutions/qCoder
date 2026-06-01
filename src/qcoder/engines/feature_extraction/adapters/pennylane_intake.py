"""
Optional PennyLane circuit intake via OpenQASM 2 export.

PennyLane is imported only when functions in this module are called.
"""

from __future__ import annotations

from typing import Any

from ..features.compute_v0 import FeatureVector, compute_features_v0
from ..ir import CircuitIR
from ..qasm2_regex_parser import parse_qasm2_text


def _load_pennylane() -> tuple[type, type | None, Any]:
    try:
        import pennylane as qml
        from pennylane import QNode
        from pennylane.io import to_openqasm
    except ImportError as e:
        raise ImportError(
            "qcoder: PennyLane is not installed. "
            "Install with: pip install pennylane  or  pip install 'qcoder[pennylane]' "
            "(optional extra)."
        ) from e

    # Optional: support QuantumScript when available on this PennyLane version.
    try:
        from pennylane.tape import QuantumScript
    except Exception:  # pragma: no cover - version-dependent optional type
        QuantumScript = None

    _ = qml  # reserved for future adapter diagnostics
    return QNode, QuantumScript, to_openqasm


def circuit_ir_from_pennylane(circuit: Any, *args: Any, **kwargs: Any) -> CircuitIR:
    """
    Export ``circuit`` with ``qml.to_openqasm(..., measure_all=True)`` and parse as OpenQASM 2 text.

    Raises ImportError when PennyLane is not installed (only at call time).
    Raises TypeError if ``circuit`` is not a supported PennyLane circuit object.
    Raises RuntimeError when export fails or exported text cannot be parsed by qCoder.
    """
    QNode, QuantumScript, to_openqasm = _load_pennylane()
    accepted_types: tuple[type, ...] = (QNode,) if QuantumScript is None else (QNode, QuantumScript)
    if not isinstance(circuit, accepted_types):
        raise TypeError(
            "expected pennylane.QNode"
            + ("" if QuantumScript is None else " or pennylane.tape.QuantumScript")
            + f", got {type(circuit).__name__}"
        )

    try:
        exported = to_openqasm(circuit, measure_all=True)
        # QNode export returns a callable (to supply call args).
        qasm_text = exported(*args, **kwargs) if callable(exported) else exported
    except Exception as e:
        raise RuntimeError(
            "qcoder: PennyLane OpenQASM export failed via qml.to_openqasm. "
            "Try a simpler circuit (QASM2-supported ops) or verify provided QNode arguments."
        ) from e

    if not isinstance(qasm_text, str):
        raise RuntimeError(
            "qcoder: PennyLane OpenQASM export did not return text. "
            "Expected OpenQASM 2 source string from qml.to_openqasm."
        )

    try:
        return parse_qasm2_text(qasm_text, source_label="qml.to_openqasm")
    except Exception as e:  # pragma: no cover - defensive adapter boundary
        raise RuntimeError(
            "qcoder: qml.to_openqasm produced OpenQASM that qCoder could not parse. "
            "Try simplifying unsupported operations or inspect the exported QASM text."
        ) from e


def extract_features_from_pennylane_circuit(
    circuit: Any, *args: Any, **kwargs: Any
) -> FeatureVector:
    """``circuit_ir_from_pennylane`` + ``compute_features_v0`` (same schema as file intake)."""
    ir = circuit_ir_from_pennylane(circuit, *args, **kwargs)
    return compute_features_v0(ir)

