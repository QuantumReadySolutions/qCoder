from __future__ import annotations

from dataclasses import dataclass

from ..ir import CircuitIR


@dataclass(frozen=True)
class InteractionGraph:
    n_qubits: int
    edges: dict[tuple[int, int], int]  # (u,v)->weight, u<v


def build_interaction_graph(ir: CircuitIR) -> InteractionGraph:
    edges: dict[tuple[int, int], int] = {}
    for op in ir.operations:
        if op.is_measure or op.is_barrier or op.is_reset:
            continue
        if len(op.qubits) < 2:
            continue
        qs = op.qubits
        # connect all pairs for multi-qubit ops
        for i in range(len(qs)):
            for j in range(i + 1, len(qs)):
                u, v = qs[i], qs[j]
                if u == v:
                    continue
                a, b = (u, v) if u < v else (v, u)
                edges[(a, b)] = edges.get((a, b), 0) + 1
    return InteractionGraph(n_qubits=ir.n_qubits, edges=edges)
