from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import List

from ..ir import CircuitIR, Operation


def _is_gate_op(op: Operation) -> bool:
    return not (op.is_measure or op.is_barrier or op.is_reset) and len(op.qubits) > 0


def _is_entangling_op(op: Operation) -> bool:
    return _is_gate_op(op) and len(op.qubits) >= 2


@dataclass(frozen=True)
class EntanglingLayerStats:
    entangling_depth: int
    n_entangling_layers: int
    avg_2q_per_entangling_layer: float
    max_2q_per_entangling_layer: int


def compute_entangling_layer_stats(ir: CircuitIR) -> EntanglingLayerStats:
    n = max(ir.n_qubits, 1)
    t: List[int] = [0] * n

    # layer -> count of 2Q ops in that layer
    layer_2q_count: dict[int, int] = defaultdict(int)
    total_2q_ops = 0

    for op in ir.operations:
        if not _is_entangling_op(op):
            continue
        qubits = [q for q in op.qubits if 0 <= q < n]
        if not qubits:
            continue
        layer = 1 + max(t[q] for q in qubits)
        for q in qubits:
            t[q] = layer
        if op.arity == 2:
            layer_2q_count[layer] += 1
            total_2q_ops += 1

    entangling_depth = max(t) if t else 0
    n_entangling_layers = len(layer_2q_count)
    avg_2q = total_2q_ops / max(n_entangling_layers, 1)
    max_2q = max(layer_2q_count.values()) if layer_2q_count else 0

    return EntanglingLayerStats(
        entangling_depth=entangling_depth,
        n_entangling_layers=n_entangling_layers,
        avg_2q_per_entangling_layer=float(avg_2q),
        max_2q_per_entangling_layer=max_2q,
    )
