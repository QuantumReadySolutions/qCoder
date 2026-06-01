from __future__ import annotations

from qcoder.core.schema import make_schema

# Schema 0.4.0: PURE circuit-derived features (no backend/precision/threshold).
FEATURE_NAMES_V0 = [
    # basic sizes
    "n_qubits",
    "n_cbits",
    "n_ops",

    # gate arity counts (exclude measure/barrier/reset)
    "n_gate_ops",
    "n_1q_gate_ops",
    "n_2q_gate_ops",
    "n_3p_gate_ops",   # 3+ qubit gate ops
    "n_param_ops",
    "n_custom_ops",

    # control ops
    "n_measure_ops",
    "n_barrier_ops",
    "n_reset_ops",

    # depth proxies
    "estimated_depth",
    "real_depth",
    "avg_parallel_gates",
    "parallelism_factor",

    # interaction graph
    "ig_n_edges",
    "ig_edge_density",

    # span stats (2Q only)
    "span_avg",
    "span_max",
    "span_std",
    "span_nearest_neighbor_ratio",
    "span_long_range_ratio",

    # Phase 2: cut profile (natural qubit order only)
    "cut_max",
    "cut_mean",
    "cut_std",
    "cut_entropy",
    "n_active_cuts",
    "max_span_in_order",

    # Quantumness v1: gate set + angles + basis/diagonal
    "n_basis_change_ops",
    "basis_change_qubit_coverage",
    "n_diagonal_gate_ops",
    "diagonal_gate_fraction",
    "n_t_like_ops",
    "n_distinct_angles",
    "angle_genericity_ratio",
    "is_certified_diagonal_only",

    # Quantumness v1: IG degree/connectivity metrics (unweighted)
    "ig_max_degree",
    "ig_avg_degree",
    "ig_degree_std",
    "ig_degree_entropy",
    "ig_n_components",
    "ig_largest_cc_frac",
    "ig_is_connected",

    # Quantumness v1: entangling depth/layers
    "entangling_depth",
    "n_entangling_layers",
    "avg_2q_per_entangling_layer",
    "max_2q_per_entangling_layer",

    # Phase 3: temporal span + weighted pair-reuse features (append-only)
    "span_long_range_ratio_early",
    "span_long_range_ratio_late",
    "span_avg_early",
    "span_avg_late",
    "ig_pair_reuse_hhi",
    "ig_pair_reuse_top1_frac",
]

SCHEMA_V0 = make_schema(FEATURE_NAMES_V0)
