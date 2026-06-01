from __future__ import annotations

from dataclasses import dataclass

from ..ir import CircuitIR


@dataclass(frozen=True)
class SpanStats:
    avg_span: float
    max_span: int
    span_std: float
    nearest_neighbor_ratio: float
    long_range_ratio: float  # span > 1
    long_range_ratio_early: float
    long_range_ratio_late: float
    avg_span_early: float
    avg_span_late: float


def compute_span_stats(ir: CircuitIR) -> SpanStats:
    gate_ops = [
        op
        for op in ir.operations
        if (not op.is_measure and not op.is_barrier and not op.is_reset and bool(op.qubits))
    ]
    split = len(gate_ops) // 2
    early_gate_ops = gate_ops[:split]
    late_gate_ops = gate_ops[split:]

    def _half_stats(ops: list) -> tuple[float, float]:
        half_spans: list[int] = []
        for op in ops:
            if len(op.qubits) != 2:
                continue
            a, b = op.qubits
            half_spans.append(abs(a - b))
        if not half_spans:
            return 0.0, 0.0
        n_half = len(half_spans)
        avg_half = sum(half_spans) / n_half
        lr_half = sum(1 for x in half_spans if x > 1) / n_half
        return float(lr_half), float(avg_half)

    long_range_ratio_early, avg_span_early = _half_stats(early_gate_ops)
    long_range_ratio_late, avg_span_late = _half_stats(late_gate_ops)

    spans: list[int] = []
    for op in ir.operations:
        if op.is_measure or op.is_barrier or op.is_reset:
            continue
        if len(op.qubits) != 2:
            continue
        a, b = op.qubits
        spans.append(abs(a - b))

    if not spans:
        return SpanStats(
            0.0,
            0,
            0.0,
            0.0,
            0.0,
            long_range_ratio_early,
            long_range_ratio_late,
            avg_span_early,
            avg_span_late,
        )

    n = len(spans)
    avg = sum(spans) / n
    mx = max(spans)
    var = sum((x - avg) ** 2 for x in spans) / n
    std = var ** 0.5

    nn = sum(1 for x in spans if x == 1) / n
    lr = sum(1 for x in spans if x > 1) / n

    return SpanStats(
        float(avg),
        int(mx),
        float(std),
        float(nn),
        float(lr),
        long_range_ratio_early,
        long_range_ratio_late,
        avg_span_early,
        avg_span_late,
    )
