from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Operation:
    name: str
    qubits: tuple[int, ...]
    params: tuple[str, ...]
    line_index: int
    op_index: int
    is_measure: bool = False
    is_barrier: bool = False
    is_reset: bool = False
    is_custom: bool = False

    @property
    def arity(self) -> int:
        return len(self.qubits)


@dataclass(frozen=True)
class QRegDecl:
    name: str
    size: int
    base: int


@dataclass(frozen=True)
class CircuitIR:
    n_qubits: int
    n_cbits: int
    operations: tuple[Operation, ...]
    qasm_format: str  # "qasm2" | "qasm3" | "unknown"
    qregs: tuple[QRegDecl, ...] = ()

    @property
    def source_format(self) -> str:
        # Future-facing alias (QIR, QASM3, etc.)
        return self.qasm_format

    @property
    def n_ops(self) -> int:
        return len(self.operations)

    def iter_ops(self) -> Sequence[Operation]:
        return self.operations
