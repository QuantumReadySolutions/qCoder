from __future__ import annotations

from dataclasses import dataclass

from ..ir import CircuitIR, Operation

BASIS_CHANGE_NAMES = frozenset({"h", "rx", "ry", "u", "u1", "u2", "u3"})
DIAGONAL_NAMES = frozenset({"z", "s", "sdg", "t", "tdg", "rz", "u1", "cp", "cz", "ccz", "rzz"})
T_LIKE_NAMES = frozenset({"t", "tdg"})
CLIFFORD_LIKE_ANGLE_TOKENS = frozenset({
    "pi/2", "-pi/2", "pi", "-pi", "0", "pi/4", "-pi/4", "pi/8", "-pi/8", "0.0",
})


def _is_gate_op(op: Operation) -> bool:
    return not (op.is_measure or op.is_barrier or op.is_reset) and len(op.qubits) > 0


@dataclass(frozen=True)
class GateSetStats:
    n_basis_change_ops: int
    basis_change_qubit_coverage: float
    n_diagonal_gate_ops: int
    diagonal_gate_fraction: float
    n_t_like_ops: int
    n_distinct_angles: int
    angle_genericity_ratio: float
    is_certified_diagonal_only: int  # 0 or 1


def compute_gate_set_stats(ir: CircuitIR) -> GateSetStats:
    gate_ops = [op for op in ir.operations if _is_gate_op(op)]
    n_gate_ops = len(gate_ops)

    n_basis_change_ops = 0
    basis_change_qubits: set[int] = set()
    n_diagonal_gate_ops = 0
    n_t_like_ops = 0
    all_diagonal = True

    for op in gate_ops:
        name = op.name.lower().strip()
        if name in BASIS_CHANGE_NAMES:
            n_basis_change_ops += 1
            basis_change_qubits.update(op.qubits)
        if name in DIAGONAL_NAMES:
            n_diagonal_gate_ops += 1
        else:
            all_diagonal = False
        if name in T_LIKE_NAMES:
            n_t_like_ops += 1

    n_q = max(ir.n_qubits, 1)
    basis_change_qubit_coverage = len(basis_change_qubits) / n_q if n_q else 0.0
    diagonal_gate_fraction = n_diagonal_gate_ops / max(n_gate_ops, 1)

    angle_tokens: set[str] = set()
    for op in gate_ops:
        for p in op.params:
            t = p.strip()
            if t:
                angle_tokens.add(t)

    n_distinct_angles = len(angle_tokens)
    if n_distinct_angles == 0:
        angle_genericity_ratio = 0.0
    else:
        non_clifford = sum(1 for t in angle_tokens if t not in CLIFFORD_LIKE_ANGLE_TOKENS)
        angle_genericity_ratio = non_clifford / n_distinct_angles

    is_certified_diagonal_only = 1 if (n_gate_ops > 0 and all_diagonal) else 0

    return GateSetStats(
        n_basis_change_ops=n_basis_change_ops,
        basis_change_qubit_coverage=basis_change_qubit_coverage,
        n_diagonal_gate_ops=n_diagonal_gate_ops,
        diagonal_gate_fraction=diagonal_gate_fraction,
        n_t_like_ops=n_t_like_ops,
        n_distinct_angles=n_distinct_angles,
        angle_genericity_ratio=angle_genericity_ratio,
        is_certified_diagonal_only=is_certified_diagonal_only,
    )
