from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, List

from .interaction_graph import InteractionGraph


@dataclass(frozen=True)
class CutProfileStats:
    # raw cut array (len = max(n_qubits-1, 0)), natural order only
    cut_profile: tuple[float, ...]
    # summary metrics
    cut_max: float
    cut_mean: float
    cut_std: float
    cut_entropy: float
    n_active_cuts: int
    max_span_in_order: int


def compute_cut_profile_stats(ig: InteractionGraph) -> CutProfileStats:
    """
    Natural-order cut profile.

    Qubit order: [0, 1, ..., n-1]
    Cut k is between qubits k and k+1, for k=0..n-2.

    For each interaction edge (u, v) with u < v and weight w:
      it crosses cuts k in [u, v-1]
      add w to each crossed cut bucket.
    """
    n = int(ig.n_qubits)
    m = max(n - 1, 0)
    cut: List[float] = [0.0] * m

    max_span = 0

    if m > 0:
        for (u, v), w_int in ig.edges.items():
            # ig guarantees u < v, but keep deterministic safety
            a, b = (u, v) if u <= v else (v, u)
            if a == b:
                continue
            if a < 0 or b < 0 or a >= n or b >= n:
                continue

            w = float(w_int)
            if w == 0.0:
                continue

            span = b - a
            if span > max_span:
                max_span = span

            # crosses cuts a, a+1, ..., b-1
            # (each cut index k corresponds to boundary between k and k+1)
            for k in range(a, b):
                if 0 <= k < m:
                    cut[k] += w

    # metrics over ALL cuts (including zeros)
    if not cut:
        return CutProfileStats(
            cut_profile=tuple(),
            cut_max=0.0,
            cut_mean=0.0,
            cut_std=0.0,
            cut_entropy=0.0,
            n_active_cuts=0,
            max_span_in_order=0,
        )

    cut_max = max(cut)
    cut_mean = sum(cut) / len(cut)

    # population std (matches spans.py style: divide by n)
    var = sum((x - cut_mean) ** 2 for x in cut) / len(cut)
    cut_std = var**0.5

    n_active = sum(1 for x in cut if x > 0.0)

    # normalized Shannon entropy over distribution p_i = cut_i / sum(cut)
    total = sum(cut)
    if total <= 0.0 or len(cut) <= 1:
        cut_entropy = 0.0
    else:
        H = 0.0
        for x in cut:
            if x <= 0.0:
                continue
            p = x / total
            H -= p * math.log(p)
        denom = math.log(len(cut))
        cut_entropy = (H / denom) if denom > 0.0 else 0.0

    return CutProfileStats(
        cut_profile=tuple(float(x) for x in cut),
        cut_max=float(cut_max),
        cut_mean=float(cut_mean),
        cut_std=float(cut_std),
        cut_entropy=float(cut_entropy),
        n_active_cuts=int(n_active),
        max_span_in_order=int(max_span),
    )
