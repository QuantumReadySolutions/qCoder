from __future__ import annotations

from .schema_v0 import FEATURE_NAMES_V0

# Short deterministic explanations for schema_v0 feature names.
FEATURE_GLOSSARY_V0: dict[str, str] = {
    "n_qubits": "Number of declared qubits in the circuit.",
    "n_cbits": "Number of declared classical bits in the circuit.",
    "n_ops": "Total number of parsed operations in the circuit IR.",
    "n_gate_ops": "Count of non-measure/non-barrier/non-reset gate operations.",
    "n_1q_gate_ops": "Count of one-qubit gate operations.",
    "n_2q_gate_ops": "Count of two-qubit gate operations.",
    "n_3p_gate_ops": "Count of gate operations acting on three or more qubits.",
    "n_param_ops": "Count of gate operations with numeric parameters.",
    "n_custom_ops": "Count of operations parsed as custom or unknown gate names.",
    "n_measure_ops": "Count of measurement operations.",
    "n_barrier_ops": "Count of barrier operations.",
    "n_reset_ops": "Count of reset operations.",
    "estimated_depth": "Depth proxy based on sequential operation layering.",
    "real_depth": "Computed circuit depth from operation scheduling.",
    "avg_parallel_gates": "Average number of simultaneously executable gates per depth layer.",
    "parallelism_factor": "Ratio describing observed gate parallelism.",
    "ig_n_edges": "Number of edges in the interaction graph built from multi-qubit gates.",
    "ig_edge_density": "Interaction-graph edge density over all possible qubit pairs.",
    "span_avg": "Average qubit-index span of two-qubit interactions.",
    "span_max": "Maximum qubit-index span of two-qubit interactions.",
    "span_std": "Standard deviation of two-qubit interaction spans.",
    "span_nearest_neighbor_ratio": "Fraction of two-qubit interactions with nearest-neighbor span.",
    "span_long_range_ratio": "Fraction of two-qubit interactions with long-range span.",
    "cut_max": "Maximum cut value across natural qubit-order cuts.",
    "cut_mean": "Mean cut value across natural qubit-order cuts.",
    "cut_std": "Standard deviation of cut values across natural qubit-order cuts.",
    "cut_entropy": "Entropy of normalized cut-profile distribution.",
    "n_active_cuts": "Number of cuts with non-zero interaction crossing.",
    "max_span_in_order": "Maximum interaction span under natural qubit ordering.",
    "n_basis_change_ops": "Count of basis-change style gate operations.",
    "basis_change_qubit_coverage": "Fraction of qubits touched by basis-change operations.",
    "n_diagonal_gate_ops": "Count of diagonal gate operations.",
    "diagonal_gate_fraction": "Fraction of gate operations that are diagonal.",
    "n_t_like_ops": "Count of T-like phase operations.",
    "n_distinct_angles": "Number of distinct parameter angles encountered.",
    "angle_genericity_ratio": "Ratio of nontrivial/distinct angle usage.",
    "is_certified_diagonal_only": "Indicator that all parsed gates are diagonal-only.",
    "ig_max_degree": "Maximum node degree in the interaction graph.",
    "ig_avg_degree": "Average node degree in the interaction graph.",
    "ig_degree_std": "Standard deviation of interaction-graph node degrees.",
    "ig_degree_entropy": "Entropy of interaction-graph degree distribution.",
    "ig_n_components": "Number of connected components in the interaction graph.",
    "ig_largest_cc_frac": "Fraction of qubits in the largest connected component.",
    "ig_is_connected": "Indicator that the interaction graph is fully connected.",
    "entangling_depth": "Depth considering only entangling (multi-qubit) layers.",
    "n_entangling_layers": "Number of depth layers containing entangling gates.",
    "avg_2q_per_entangling_layer": "Average two-qubit gates per entangling layer.",
    "max_2q_per_entangling_layer": "Maximum two-qubit gates in a single entangling layer.",
    "span_long_range_ratio_early": "Long-range interaction ratio in early circuit segment.",
    "span_long_range_ratio_late": "Long-range interaction ratio in late circuit segment.",
    "span_avg_early": "Average interaction span in early circuit segment.",
    "span_avg_late": "Average interaction span in late circuit segment.",
    "ig_pair_reuse_hhi": "Herfindahl-like concentration index for qubit-pair reuse.",
    "ig_pair_reuse_top1_frac": "Fraction of interactions on the most reused qubit pair.",
}

STRUCTURAL_SUMMARY_FEATURES = (
    "real_depth",
    "entangling_depth",
    "n_2q_gate_ops",
    "span_max",
    "cut_max",
    "ig_edge_density",
)


def selected_feature_definitions(feature_names: tuple[str, ...] | list[str]) -> dict[str, str]:
    selected = {}
    for name in feature_names:
        if name in FEATURE_GLOSSARY_V0:
            selected[name] = FEATURE_GLOSSARY_V0[name]
    return selected


def full_feature_definitions() -> dict[str, str]:
    return {name: FEATURE_GLOSSARY_V0[name] for name in FEATURE_NAMES_V0 if name in FEATURE_GLOSSARY_V0}


def glossary_unknown_keys() -> set[str]:
    return set(FEATURE_GLOSSARY_V0) - set(FEATURE_NAMES_V0)

