from __future__ import annotations

from dataclasses import dataclass

from ..ir import CircuitIR


@dataclass(frozen=True)
class DepthStats:
    estimated_depth: int   # gate statements count (excludes measure/barrier/reset)
    real_depth: int        # per-qubit timeline depth proxy
    avg_parallel_gates: float
    parallelism_factor: float


def compute_depth_stats(ir: CircuitIR) -> DepthStats:
    t = [0] * max(ir.n_qubits, 1)

    gate_ops = 0
    for op in ir.operations:
        if op.is_measure or op.is_barrier or op.is_reset:
            continue
        if not op.qubits:
            continue
        gate_ops += 1
        mx = 0
        for q in op.qubits:
            if 0 <= q < len(t):
                if t[q] > mx:
                    mx = t[q]
        nxt = mx + 1
        for q in op.qubits:
            if 0 <= q < len(t):
                t[q] = nxt

    real_depth = max(t) if t else 0
    estimated_depth = gate_ops

    avg_parallel = (gate_ops / real_depth) if real_depth > 0 else 0.0
    parallelism_factor = (gate_ops / (real_depth * ir.n_qubits)) if (real_depth > 0 and ir.n_qubits > 0) else 0.0

    return DepthStats(
        estimated_depth=estimated_depth,
        real_depth=real_depth,
        avg_parallel_gates=float(avg_parallel),
        parallelism_factor=float(parallelism_factor),
    )
