from __future__ import annotations

from pathlib import Path

from ..ir import CircuitIR
from ..openqasm3_bounded_parser import (
    OpenQASM3ParseResult,
    parse_openqasm3_bytes,
    parse_openqasm3_text,
)
from ..qasm2_regex_parser import parse_qasm2_file, parse_qasm2_text

__all__ = [
    "OpenQASM3ParseResult",
    "parse_circuit_file",
    "parse_openqasm3_bytes",
    "parse_openqasm3_text",
    "parse_qasm2_file",
    "parse_qasm2_text",
]


def parse_circuit_file(path: str) -> CircuitIR:
    """
    Parser routing point.
    OpenQASM2 keeps its established parser. Fully supported OpenQASM 3 may
    produce the same complete CircuitIR; partial evidence never does.
    """
    raw = Path(path).read_bytes()
    if raw.lstrip().startswith((b"OPENQASM 3;", b"OPENQASM 3.0;")):
        result = parse_openqasm3_bytes(raw, artifact_label=Path(path).name)
        if result.circuit_ir is None:
            raise ValueError("openqasm3_complete_circuit_ir_not_established")
        return result.circuit_ir
    return parse_qasm2_file(path)
