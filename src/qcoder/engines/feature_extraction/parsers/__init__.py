from __future__ import annotations

from ..ir import CircuitIR
from ..qasm2_regex_parser import parse_qasm2_file, parse_qasm2_text

__all__ = ["parse_circuit_file", "parse_qasm2_file", "parse_qasm2_text"]


def parse_circuit_file(path: str) -> CircuitIR:
    """
    Parser routing point.
    Today: OpenQASM2 (regex parser).
    Future: OpenQASM3, QIR, other IR adapters.
    """
    ir = parse_qasm2_file(path)

    # For now: we accept qasm2 and unknown headers (still parseable),
    # but explicitly reject qasm3 until implemented.
    if ir.qasm_format == "qasm3":
        raise NotImplementedError("OpenQASM 3 parsing is not implemented yet.")
    return ir
