from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass
from typing import List

from .interaction_graph import InteractionGraph


@dataclass(frozen=True)
class InteractionGraphMetrics:
    ig_max_degree: int
    ig_avg_degree: float
    ig_degree_std: float
    ig_degree_entropy: float
    ig_n_components: int
    ig_largest_cc_frac: float
    ig_is_connected: int  # 0 or 1
    ig_pair_reuse_hhi: float
    ig_pair_reuse_top1_frac: float


def compute_interaction_graph_metrics(ig: InteractionGraph) -> InteractionGraphMetrics:
    n = max(1, ig.n_qubits)  # treat n_qubits <= 0 as 1 node for safety

    if n == 1:
        return InteractionGraphMetrics(
            ig_max_degree=0,
            ig_avg_degree=0.0,
            ig_degree_std=0.0,
            ig_degree_entropy=0.0,
            ig_n_components=1,
            ig_largest_cc_frac=1.0,
            ig_is_connected=1,
            ig_pair_reuse_hhi=0.0,
            ig_pair_reuse_top1_frac=0.0,
        )

    # Build adjacency lists (undirected); nodes 0..n-1
    adj: List[List[int]] = [[] for _ in range(n)]
    for (u, v), _ in ig.edges.items():
        if 0 <= u < n and 0 <= v < n and u != v:
            adj[u].append(v)
            adj[v].append(u)

    # Unweighted degree = number of unique neighbors
    degrees = [len(neighbors) for neighbors in adj]

    # Components via BFS
    visited = [False] * n
    components: List[List[int]] = []
    for start in range(n):
        if visited[start]:
            continue
        comp: List[int] = []
        q: deque[int] = deque([start])
        visited[start] = True
        while q:
            node = q.popleft()
            comp.append(node)
            for nei in adj[node]:
                if not visited[nei]:
                    visited[nei] = True
                    q.append(nei)
        components.append(comp)

    ig_n_components = len(components)
    largest_size = max(len(c) for c in components) if components else 0
    ig_largest_cc_frac = largest_size / n
    ig_is_connected = 1 if ig_n_components == 1 else 0

    # Degree stats
    ig_max_degree = max(degrees)
    ig_avg_degree = sum(degrees) / n
    variance = sum((d - ig_avg_degree) ** 2 for d in degrees) / n
    ig_degree_std = math.sqrt(variance) if variance >= 0 else 0.0

    # Normalized degree entropy: distribution over degree values
    # p_k = count(nodes with degree k) / n; H = -sum p_k log(p_k); normalize by log(m), m = distinct degree values
    hist = Counter(degrees)
    distinct_degree_values = len(hist)
    if distinct_degree_values <= 1:
        ig_degree_entropy = 0.0
    else:
        h = 0.0
        for k, count in hist.items():
            p_k = count / n
            if p_k > 0:
                h -= p_k * math.log(p_k)
        ig_degree_entropy = h / math.log(distinct_degree_values)

    # Weighted interaction-pair reuse concentration from pair counts.
    total_pair_count = sum(int(w) for w in ig.edges.values() if int(w) > 0)
    if total_pair_count > 0:
        probs = [int(w) / total_pair_count for w in ig.edges.values() if int(w) > 0]
        ig_pair_reuse_hhi = sum(p * p for p in probs)
        ig_pair_reuse_top1_frac = max(int(w) for w in ig.edges.values() if int(w) > 0) / total_pair_count
    else:
        ig_pair_reuse_hhi = 0.0
        ig_pair_reuse_top1_frac = 0.0

    return InteractionGraphMetrics(
        ig_max_degree=ig_max_degree,
        ig_avg_degree=ig_avg_degree,
        ig_degree_std=ig_degree_std,
        ig_degree_entropy=ig_degree_entropy,
        ig_n_components=ig_n_components,
        ig_largest_cc_frac=ig_largest_cc_frac,
        ig_is_connected=ig_is_connected,
        ig_pair_reuse_hhi=ig_pair_reuse_hhi,
        ig_pair_reuse_top1_frac=ig_pair_reuse_top1_frac,
    )
